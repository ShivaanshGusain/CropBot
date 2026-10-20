"""Load facts (step 13): the validated, verified facts and the step 8 Variety records into Neo4j.

  uv run python -m kg.load.facts source:tnau_agriculture_2020 --check   # build and check every row; no database
  uv run python -m kg.load.facts source:tnau_agriculture_2020           # one write transaction, then the report
  uv run python -m kg.load.facts --snapshot                             # hash of the whole graph, no writes

Input: data/verified/<id>/facts.jsonl (status and verifier), data/validated/<id>/facts.jsonl (the fact and
its review reasons), data/normalized/<id>/facts.jsonl (purpose origins) and data/tables/<id>/varieties.jsonl.
Held facts never reach step 11, so they are never loaded.

Everything is MERGEd on id. Map-shaped fields are flattened (raw{} -> raw_<field>, coefficients{} ->
coef_<name>, Variety cells{} -> cells_json, excluded_regions -> excluded_region_ids/_raws) and any property
that is still not a Neo4j primitive is refused. Refused before any write: a fact with no IN_REGION, no
SourceSpan or no FOR_CROP; an edge to a concept that is not in the graph; two spans with one id and
different properties; a duplicate id; an approved status from code; an unanswered claim.

Revisions (schema "Revisions"): matched on fact_key. Same id = same values: the node is kept, and a human
status (approved, rejected) or reviewed_by is never overwritten. Same fact_key with a new id: the new node
is needs_review with (new)-[:REVISION_OF]->(old), and the old node is left untouched. Any other fact of the
source not in this load is flagged missing_in_latest_run, never deleted. superseded_by stays reserved for
a newer edition.

Conflicts: facts with the same conflict_key (subtype, applicability, identity, step slots and the storage
window) and a different value_key get one CONFLICTS_WITH {origin: "detected"} per pair, from the smaller id
to the larger, and become needs_review. Approved registry [[conflict]] entries add {origin: "review"}.
Writes data/loaded/<id>/report.json (gitignored).
"""

import argparse
import hashlib
import json
from collections import Counter, defaultdict

from kg.extract.quotes import normalise
from kg.normalize import NORMALIZED_DIR
from kg.registry import ROOT, RegistryError, read_registry
from kg.schema import FACT
from kg.validate import VALIDATED_DIR
from kg.verify import VERIFIED_DIR

from .constraints import ensure_constraints
from .db import get_driver
from .seed import is_primitive, read_seed
from .sources import load_sources

TABLES_DIR = ROOT / "data" / "tables"
LOADED_DIR = ROOT / "data" / "loaded"
HUMAN_STATUSES = ["approved", "rejected"]
APPLICABILITY = (("crop_ids", "FOR_CROP"), ("variety_ids", "FOR_VARIETY"), ("season_ids", "IN_SEASON"),
                 ("system_ids", "UNDER_SYSTEM"), ("soil_ids", "ON_SOIL"), ("purpose_ids", "FOR_PURPOSE"),
                 ("stage_ids", "AT_STAGE"))
IDENTITY = (("pest_ids", "FOR_PEST"), ("target_ids", "TARGETS"), ("concerns", "CONCERNS"),
            ("recommends", "RECOMMENDS"))
IDENTITY_FIELDS = ("kind", "control_class", "dose_basis", "storage_term_raw")
WINDOW_FIELDS = ("storage_months_min", "storage_months_max", "storage_months_min_inclusive",
                 "storage_months_max_inclusive")
# fact fields that become nodes or edges (or are set only by people or on create), never properties
NOT_PROPS = {"steps", "conditions", "evidence", "regions", "excluded_regions", "clauses", "raw", "coefficients",
             "revision_of", "alternative_to", "conflicts_with", "status", "reviewed_by", "created_at"} \
    | {k for k, _ in APPLICABILITY} | {k for k, _ in IDENTITY}
CORE_VALUE_SKIP = NOT_PROPS | {"id", "subtype", "fact_key", "summary_en", "extraction_model", "verifier",
                               "verifier_score", "unmapped", "missing_in_latest_run", "valid_from",
                               "superseded_by", "duration_group"} | set(IDENTITY_FIELDS) | set(WINDOW_FIELDS)


class LoadError(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("\n".join(problems))
        self.problems = problems


def sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def flat_array(value) -> bool:
    """A Neo4j property: a primitive, or a flat array of one primitive type (never a map)."""
    if not is_primitive(value):
        return False
    return not isinstance(value, list) or len({type(v) for v in value}) <= 1


# --- reading the inputs ------------------------------------------------------------------------

def _jsonl(path):
    return [json.loads(line) for line in open(path, encoding="utf-8")]


def read_inputs(entry) -> dict:
    name = entry.id.split(":", 1)[1]
    verified = {r["fact_id"]: r for r in _jsonl(VERIFIED_DIR / name / "facts.jsonl")}
    validated = _jsonl(VALIDATED_DIR / name / "facts.jsonl")
    normalized = {r["fact"]["id"]: r for r in _jsonl(NORMALIZED_DIR / name / "facts.jsonl")}
    varieties = _jsonl(TABLES_DIR / name / "varieties.jsonl")
    return {"verified": verified, "validated": validated, "normalized": normalized, "varieties": varieties}


# --- keys for conflicts -------------------------------------------------------------------------

def _conditions(fact: dict) -> list:
    found = list(fact.get("conditions") or [])
    found += [c for s in fact.get("steps") or [] for c in s.get("conditions") or []]
    found += [c for cl in fact.get("clauses") or [] for c in cl.get("conditions") or []]
    return sorted({(c["variable"], c["op"], c["raw"]) for c in found})


def conflict_key(fact: dict) -> str:
    """What two facts must share to contradict each other: subtype, applicability, identity, the
    step slots (operation, method, anchor, targets with formulation) and the storage window. Source,
    section and values are left out, so facts from different books compare."""
    slot = sorted([s["order"], s.get("alt_group"), s.get("alt_option"), s["operation"], s.get("method") or "",
                   s.get("anchor") or "", sorted([a["target_id"], a.get("formulation") or ""] for a in s["applies"])]
                  for s in fact["steps"])
    return "ck:" + sha({
        "subtype": fact["subtype"],
        "applicability": {k: sorted(fact.get(k) or []) for k, _ in APPLICABILITY}
                         | {"regions": sorted(r["id"] for r in fact["regions"]),
                            "duration_group": fact.get("duration_group")},
        "identity": {k: sorted(fact.get(k) or []) for k, _ in IDENTITY}
                    | {k: fact.get(k) for k in IDENTITY_FIELDS} | {"conditions": _conditions(fact)},
        "steps": slot, "window": {k: fact.get(k) for k in WINDOW_FIELDS}})[:24]


def value_key(fact: dict) -> str:
    """The values a conflict compares: subtype values, amounts, offsets, clause and condition values."""
    fields = {k: v for k, v in fact.items() if k not in CORE_VALUE_SKIP}
    steps = sorted([s["order"], s.get("alt_group"), s.get("alt_option"), s.get("offset_min"), s.get("offset_max"),
                    s.get("offset_unit"), s.get("month_start"), s.get("month_end"),
                    sorted([a["target_id"], a.get("formulation"), a.get("value"), a.get("min"), a.get("max"),
                            a.get("unit"), a.get("basis"), a.get("area_cents")] for a in s["applies"]),
                    sorted([c["variable"], c["op"], c["value"], c.get("value_max")] for c in s.get("conditions") or [])]
                   for s in fact["steps"])
    clauses = sorted([c["observation"], c["value"], c["unit"], c.get("sampling_unit"),
                      sorted([x["variable"], x["op"], x["value"], x.get("value_max")] for x in c.get("conditions") or [])]
                     for c in fact.get("clauses") or [])
    return "vk:" + sha({"fields": fields, "coefficients": fact.get("coefficients"), "steps": steps,
                        "clauses": clauses})[:24]


# --- rows -------------------------------------------------------------------------------------------

def _props(d: dict, skip=()) -> dict:
    return {k: v for k, v in d.items() if k not in skip}


def fact_rows(rec: dict, verified: dict, purpose_origins: dict) -> dict:
    """Every node and edge one fact writes, as rows for the Cypher below."""
    fact = rec["fact"]
    rid, h = fact["id"], fact["id"].split(":", 1)[1]
    props = _props(fact, NOT_PROPS)
    props |= {"raw_%s" % k: v for k, v in (fact.get("raw") or {}).items()}
    props |= {"coef_%s" % k: v for k, v in (fact.get("coefficients") or {}).items()}
    props["excluded_region_ids"] = [x["id"] for x in fact.get("excluded_regions") or []]
    props["excluded_region_raws"] = [x["raw"] for x in fact.get("excluded_regions") or []]
    scored = [c for c in verified["claims"] if not c["control"]]
    props |= {"review_reasons": list(rec["review_reasons"]), "verifier": verified["verifier"],
              "verifier_score": verified["verifier_score"], "verifier_claims": [c["claim"] for c in scored],
              "verifier_claim_p_yes": [c["p_yes"] for c in scored], "verifier_notes": list(verified["notes"]),
              "conflict_key": conflict_key(fact), "value_key": value_key(fact), "missing_in_latest_run": False}
    out = {"rec": [{"id": rid, "subtype": fact["subtype"], "status": verified["status"], "props": props,
                    "unanswered": [c["key"] for c in verified["claims"] if c["p_yes"] is None]}],
           "nodes": defaultdict(list), "edges": defaultdict(list)}
    nodes, edges = out["nodes"], out["edges"]

    def condition(owner_label, owner_id, cs, path):
        for j, c in enumerate(cs or []):
            cid = "cond:%s:%s:%d" % (h, path, j)
            nodes["Condition"].append({"id": cid, "props": _props(c)})
            edges[(owner_label, "WHEN", "Condition")].append({"src": owner_id, "dst": cid, "props": {}})

    for i, s in enumerate(fact["steps"]):
        sid = "step:%s:%d" % (h, i)
        nodes["Step"].append({"id": sid, "props": _props(s, {"applies", "conditions"})})
        edges[("Recommendation", "HAS_STEP", "Step")].append({"src": rid, "dst": sid, "props": {}})
        for a in s["applies"]:
            edges[("Step", "APPLIES", "Concept")].append({"src": sid, "dst": a["target_id"],
                                                          "props": _props(a, {"target_id"})})
        condition("Step", sid, s.get("conditions"), "s%d" % i)
    for i, c in enumerate(fact.get("clauses") or []):
        cid = "clause:%s:%d" % (h, i)
        nodes["ThresholdClause"].append({"id": cid, "props": _props(c, {"conditions"})})
        edges[("Recommendation", "HAS_CLAUSE", "ThresholdClause")].append({"src": rid, "dst": cid, "props": {}})
        condition("ThresholdClause", cid, c.get("conditions"), "c%d" % i)
    condition("Recommendation", rid, fact.get("conditions"), "r")
    for r in fact["regions"]:
        edges[("Recommendation", "IN_REGION", "Concept")].append({"src": rid, "dst": r["id"],
                                                                  "props": {"origin": r["origin"]}})
    for key, rel in APPLICABILITY + IDENTITY:
        for target in fact.get(key) or []:
            # FOR_PURPOSE {origin}: a v1.3 item built ahead; a list, since quote and section may both give it
            p = {"origin": sorted(purpose_origins[target])} if rel == "FOR_PURPOSE" else {}
            edges[("Recommendation", rel, "Concept")].append({"src": rid, "dst": target, "props": p})
    for span in fact["evidence"]:
        nodes["SourceSpan"].append({"id": span["id"], "props": _props(span, {"id", "source_id"}),
                                    "source_id": span["source_id"]})
        edges[("Recommendation", "EVIDENCED_BY", "SourceSpan")].append({"src": rid, "dst": span["id"], "props": {}})
    for target in fact.get("alternative_to") or []:
        edges[("Recommendation", "ALTERNATIVE_TO", "Recommendation")].append({"src": rid, "dst": target, "props": {}})
    return out


def variety_rows(v: dict) -> dict:
    props = _props(v, {"id", "raw", "cells", "evidence", "crop_id", "review_status"})
    props |= {"raw_%s" % k: x for k, x in (v.get("raw") or {}).items()}
    props["cells_json"] = json.dumps(v.get("cells") or {}, sort_keys=True, ensure_ascii=False)
    spans = v["evidence"] if isinstance(v["evidence"], list) else [v["evidence"]]
    out = {"variety": [{"id": v["id"], "review_status": v["review_status"], "props": props}],
           "nodes": defaultdict(list), "edges": defaultdict(list)}
    if v.get("crop_id"):
        out["edges"][("Variety", "VARIETY_OF", "Concept")].append({"src": v["id"], "dst": v["crop_id"], "props": {}})
    for span in spans:
        out["nodes"]["SourceSpan"].append({"id": span["id"], "props": _props(span, {"id", "source_id"}),
                                           "source_id": span["source_id"]})
        out["edges"][("Variety", "EVIDENCED_BY", "SourceSpan")].append({"src": v["id"], "dst": span["id"], "props": {}})
    return out


def _match(fact: dict, side) -> bool:
    return (fact["subtype"] == side.subtype and any(
        e["pdf_page"] == side.pdf_page and normalise(e["quote"]) == normalise(side.quote) for e in fact["evidence"]))


def build(entry, inputs: dict, concept_ids: set[str]) -> dict:
    """Every row of the load, the checks, and the conflicts found inside it. Raises LoadError."""
    problems = []
    recs, varieties = [], []
    nodes, edges = defaultdict(dict), defaultdict(list)
    for rec in inputs["validated"]:
        fact = rec["fact"]
        try:
            FACT.validate_python(fact)
        except ValueError as e:
            problems.append("%s: not a valid fact: %s" % (fact["id"], str(e).splitlines()[0]))
            continue
        ver = inputs["verified"].get(fact["id"])
        if ver is None:
            problems.append("%s: not in step 12's output; run kg.verify" % fact["id"])
            continue
        origins = (inputs["normalized"].get(fact["id"]) or {}).get("purpose_origins") or {}
        missing = [p for p in fact.get("purpose_ids") or [] if p not in origins]
        if missing:
            problems.append("%s: no purpose origin for %s" % (fact["id"], missing))
            continue
        rows = fact_rows(rec, ver, origins)
        r = rows["rec"][0]
        if not fact["regions"]:
            problems.append("%s: no IN_REGION" % fact["id"])
        if not fact["evidence"]:
            problems.append("%s: no SourceSpan" % fact["id"])
        if not fact.get("crop_ids"):
            problems.append("%s: no FOR_CROP" % fact["id"])
        if r["status"] in HUMAN_STATUSES:
            problems.append("%s: status %s comes only from a reviewer" % (fact["id"], r["status"]))
        if r["unanswered"]:
            problems.append("%s: unanswered claims %s; run kg.verify" % (fact["id"], r["unanswered"]))
        recs.append({**r, "fact_key": fact["fact_key"], "short": "%s#%d" % (rec["unit_id"].rsplit(":", 1)[1],
                                                                            rec["raw_index"]), "fact": fact})
        _gather(rows, nodes, edges, problems)
    for v in inputs["varieties"]:
        rows = variety_rows(v)
        varieties.append(rows["variety"][0])
        _gather(rows, nodes, edges, problems)
    ids = Counter([r["id"] for r in recs] + [v["id"] for v in varieties])
    problems += ["duplicate id %s" % i for i, n in ids.items() if n > 1]
    for r in recs + varieties:
        problems += ["%s: property %s is not a Neo4j primitive: %r" % (r["id"], k, v)
                     for k, v in r["props"].items() if not flat_array(v)]
    for label, by_id in nodes.items():
        for n in by_id.values():
            problems += ["%s: property %s is not a Neo4j primitive: %r" % (n["id"], k, v)
                         for k, v in n["props"].items() if not flat_array(v)]
    for (src, rel, dst), rows in edges.items():
        for e in rows:
            problems += ["%s -%s-> %s: property %s is not a Neo4j primitive" % (e["src"], rel, e["dst"], k)
                         for k, v in e["props"].items() if not flat_array(v)]
            if dst == "Concept" and e["dst"] not in concept_ids and e["dst"] not in ids:
                problems.append("%s -%s-> %s: no such concept in the graph" % (e["src"], rel, e["dst"]))
    sources = {n["source_id"] for n in nodes["SourceSpan"].values()}
    problems += ["span source %s is not this registry entry" % s for s in sources if s != entry.id]
    reviewer, proposed = [], []
    for i, c in enumerate(entry.conflict):
        sides = [[r for r in recs if _match(r["fact"], side)] for side in (c.a, c.b)]
        for name, hits in zip("ab", sides):
            if len(hits) != 1:
                problems.append("[[conflict]] %d side %s matches %d facts (needs exactly one)" % (i + 1, name, len(hits)))
        if all(len(h) == 1 for h in sides):
            pair = sorted([sides[0][0]["id"], sides[1][0]["id"]])
            row = {"src": pair[0], "dst": pair[1], "note": c.note, "status": c.status,
                   "facts": [sides[0][0]["short"], sides[1][0]["short"]]}
            (reviewer if c.status == "approved" else proposed).append(row)
    if problems:
        raise LoadError(problems)
    groups = defaultdict(list)
    for r in recs:
        groups[r["props"]["conflict_key"]].append(r)
    detected = [{"pair": sorted([a["id"], b["id"]]), "facts": [a["short"], b["short"]]}
                for g in groups.values() for i, a in enumerate(g) for b in g[i + 1:]
                if a["props"]["value_key"] != b["props"]["value_key"]]
    return {"recs": recs, "varieties": varieties, "nodes": nodes, "edges": edges, "reviewer": reviewer,
            "proposed": proposed, "detected_in_load": detected}


def _gather(rows, nodes, edges, problems):
    for label, items in rows["nodes"].items():
        for n in items:
            seen = nodes[label].get(n["id"])
            if seen is not None and (seen["props"], seen.get("source_id")) != (n["props"], n.get("source_id")):
                problems.append("%s %s: same id with different properties" % (label, n["id"]))
            nodes[label][n["id"]] = n
    for key, items in rows["edges"].items():
        edges[key].extend(items)


def counts(built: dict) -> dict:
    nodes = Counter({"Recommendation": len(built["recs"]), "Variety": len(built["varieties"])})
    nodes.update({label: len(by_id) for label, by_id in built["nodes"].items()})
    edges = Counter()
    for (_, rel, _), rows in built["edges"].items():
        edges[rel] += len(rows)
    edges["IN_SOURCE"] = len(built["nodes"]["SourceSpan"])
    return {"nodes": dict(nodes), "edges": dict(sorted(edges.items())),
            "by_subtype": dict(Counter(r["subtype"] for r in built["recs"])),
            "status": dict(Counter(r["status"] for r in built["recs"]))}


# --- writing --------------------------------------------------------------------------------------

def _run(tx, created, query, **params):
    result = tx.run(query, **params)
    rows = [r.data() for r in result]
    c = result.consume().counters
    created["nodes"] += c.nodes_created
    created["relationships"] += c.relationships_created
    return rows


def write(tx, entry, built: dict) -> dict:
    """One transaction: revisions are read first, then every MERGE, then missing, conflicts."""
    created, report = Counter(), {}
    keys = [r["fact_key"] for r in built["recs"]]
    ids = [r["id"] for r in built["recs"]]
    existing = _run(tx, created, "MATCH (o:Recommendation) WHERE o.fact_key IN $keys AND NOT o.id IN $ids "
                    "AND NOT EXISTS { MATCH (x:Recommendation)-[:REVISION_OF]->(o) WHERE NOT x.id IN $ids } "
                    "RETURN o.fact_key AS key, o.id AS id", keys=keys, ids=ids)
    old = defaultdict(list)
    for row in existing:
        old[row["key"]].append(row["id"])
    revisions = [{"src": r["id"], "dst": o} for r in built["recs"] for o in old.get(r["fact_key"], [])]
    revised = {x["src"] for x in revisions}
    for subtype in sorted({r["subtype"] for r in built["recs"]}):
        rows = [{"id": r["id"], "props": r["props"], "status": "needs_review" if r["id"] in revised else r["status"]}
                for r in built["recs"] if r["subtype"] == subtype]
        _run(tx, created, "UNWIND $rows AS row MERGE (n:Recommendation {id: row.id}) "
             "ON CREATE SET n.created_at = datetime() SET n:%s, n += row.props, n.status = "
             "CASE WHEN n.status IN $human THEN n.status ELSE row.status END" % subtype, rows=rows, human=HUMAN_STATUSES)
    _run(tx, created, "UNWIND $rows AS row MERGE (n:Concept:Variety {id: row.id}) SET n += row.props, "
         "n.review_status = CASE WHEN n.review_status = 'approved' THEN n.review_status ELSE row.review_status END",
         rows=built["varieties"])
    for label, by_id in built["nodes"].items():
        _run(tx, created, "UNWIND $rows AS row MERGE (n:%s {id: row.id}) SET n += row.props" % label,
             rows=list(by_id.values()))
    spans = [{"id": i, "source": n["source_id"]} for i, n in built["nodes"]["SourceSpan"].items()]
    matched = _run(tx, created, "UNWIND $rows AS row MATCH (s:SourceSpan {id: row.id}) MATCH (src:Source {id: row.source}) "
                   "MERGE (s)-[:IN_SOURCE]->(src) RETURN count(*) AS n", rows=spans)[0]["n"]
    short = {"IN_SOURCE": len(spans) - matched}
    for (src, rel, dst), rows in sorted(built["edges"].items()):
        matched = _run(tx, created, "UNWIND $rows AS row MATCH (a:%s {id: row.src}) MATCH (b:%s {id: row.dst}) "
                       "MERGE (a)-[r:%s]->(b) SET r += row.props RETURN count(*) AS n" % (src, dst, rel),
                       rows=rows)[0]["n"]
        short[rel] = short.get(rel, 0) + len(rows) - matched
    if revisions:
        _run(tx, created, "UNWIND $rows AS row MATCH (a:Recommendation {id: row.src}) MATCH (b:Recommendation {id: row.dst}) "
             "MERGE (a)-[:REVISION_OF]->(b)", rows=revisions)
    report["edges_not_matched"] = {k: v for k, v in short.items() if v}
    if report["edges_not_matched"]:
        raise LoadError(["edges whose ends are not in the graph: %s" % report["edges_not_matched"]])
    # the old side of a revision is left untouched: it keeps serving (if approved) until its revision is
    missing = _run(tx, created, "MATCH (r:Recommendation)-[:EVIDENCED_BY]->(:SourceSpan)-[:IN_SOURCE]->(:Source {id: $src}) "
                   "WHERE NOT r.id IN $ids AND NOT r.id IN $revised WITH DISTINCT r "
                   "SET r.missing_in_latest_run = true RETURN r.id AS id",
                   src=entry.id, ids=ids, revised=[x["dst"] for x in revisions])
    detected = _run(tx, created,
                    "MATCH (a:Recommendation) MATCH (b:Recommendation {conflict_key: a.conflict_key}) WHERE a.id < b.id "
                    "AND a.value_key <> b.value_key AND NOT EXISTS { (a)-[:REVISION_OF*]-(b) } "
                    "MERGE (a)-[c:CONFLICTS_WITH]->(b) ON CREATE SET c.origin = 'detected' "
                    "SET a.status = CASE WHEN a.status IN $human THEN a.status ELSE 'needs_review' END, "
                    "b.status = CASE WHEN b.status IN $human THEN b.status ELSE 'needs_review' END "
                    "RETURN a.id AS a, b.id AS b", human=HUMAN_STATUSES)
    reviewed = _run(tx, created, "UNWIND $rows AS row MATCH (a:Recommendation {id: row.src}) MATCH (b:Recommendation {id: row.dst}) "
                    "MERGE (a)-[c:CONFLICTS_WITH]->(b) ON CREATE SET c.origin = 'review' "
                    "SET a.status = CASE WHEN a.status IN $human THEN a.status ELSE 'needs_review' END, "
                    "b.status = CASE WHEN b.status IN $human THEN b.status ELSE 'needs_review' END "
                    "RETURN a.id AS a, b.id AS b", rows=built["reviewer"], human=HUMAN_STATUSES)
    report |= {"created": dict(created), "revisions": revisions, "missing_in_latest_run": [m["id"] for m in missing],
               "conflicts_detected": detected, "conflicts_review": reviewed}
    return report


def snapshot(driver, database=None) -> dict:
    """A hash over every node (labels, properties) and relationship (type, ends, properties)."""
    nodes, _, _ = driver.execute_query("MATCH (n) RETURN labels(n) AS l, properties(n) AS p", database_=database)
    rels, _, _ = driver.execute_query("MATCH (a)-[r]->(b) RETURN type(r) AS t, a.id AS a, b.id AS b, properties(r) AS p",
                                      database_=database)
    lines = sorted(json.dumps([sorted(n["l"]), n["p"]], sort_keys=True, default=str) for n in nodes)
    lines += sorted(json.dumps([r["t"], r["a"], r["b"], r["p"]], sort_keys=True, default=str) for r in rels)
    return {"sha256": hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest(), "nodes": len(nodes),
            "relationships": len(rels)}


def load(driver, entry, built: dict, database=None) -> dict:
    """Constraints, the Source node, then one write transaction; snapshots before and after."""
    ensure_constraints(driver, database)
    load_sources(driver, [entry], database)
    before = snapshot(driver, database)
    with driver.session(database=database) as session:
        result = session.execute_write(write, entry, built)
    after = snapshot(driver, database)
    return {"write": result, "snapshot_before": before, "snapshot_after": after,
            "changed": before["sha256"] != after["sha256"]}


# --- command line -----------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m kg.load.facts", description="Step 13: load facts into Neo4j")
    ap.add_argument("source_id", nargs="?")
    ap.add_argument("--check", action="store_true", help="build and check every row; no database")
    ap.add_argument("--snapshot", action="store_true", help="print the graph's snapshot hash; no writes")
    ap.add_argument("--database", help="the Neo4j database to use (default: the server's home database)")
    a = ap.parse_args(argv)
    if a.snapshot:
        with get_driver() as driver:
            print(json.dumps(snapshot(driver, a.database)))
        return 0
    try:
        entries = read_registry()
    except RegistryError as e:
        raise SystemExit("registry is invalid, nothing loaded:\n  " + "\n  ".join(e.problems))
    entry = next((e for e in entries if e.id == a.source_id), None)
    if entry is None:
        raise SystemExit("unknown source %s" % a.source_id)
    concept_ids = {n.id for n in read_seed().nodes}
    try:
        built = build(entry, read_inputs(entry), concept_ids)
    except LoadError as e:
        raise SystemExit("refused, nothing loaded:\n  " + "\n  ".join(e.problems))
    rep = {"counts": counts(built), "detected_in_load": built["detected_in_load"],
           "reviewer_conflicts_approved": built["reviewer"], "reviewer_conflicts_proposed": built["proposed"]}
    print(json.dumps(rep, indent=1, ensure_ascii=False))
    if a.check:
        print("check only: nothing written")
        return 0
    with get_driver() as driver:
        try:
            rep |= load(driver, entry, built, a.database)
        except LoadError as e:
            raise SystemExit("refused, transaction rolled back:\n  " + "\n  ".join(e.problems))
    out = LOADED_DIR / entry.id.split(":", 1)[1]
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("write", "snapshot_before", "snapshot_after", "changed")},
                     indent=1, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
