"""Extraction (step 9): one model call per unit, output in the raw model (kg.extract.model).

  uv run python -m kg.extract find    source:tnau_agriculture_2020 "Wet nursery"
  uv run python -m kg.extract prepare source:tnau_agriculture_2020 --unit <unit_id> --model <name>
  uv run python -m kg.extract ingest  source:tnau_agriculture_2020 --unit <unit_id> --model <name> --response <file>
  uv run python -m kg.extract report  source:tnau_agriculture_2020

No model is called from here: `prepare` writes the filled prompt, a runner (a person, Claude Code,
or later a Sarvam or API runner) answers it, and `ingest` checks and stores the answer.
Input: data/units/<id>/units.jsonl and data/tables/<id>/tables.jsonl (run kg.segment and kg.tables).
Output: data/extracted/<id>/ (gitignored). Checks here: the answer parses into the raw model and
every quote is found in the unit text. Failures are saved and reported, never fixed.
"""

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from kg.registry import ROOT
from kg.schema.vocab import (CONDITION_VARIABLES, Anchor, CautionKind, ConditionOp, ControlClass,
                             DoseBasis, DurationGroup, OffsetUnit, OperationType, Subtype,
                             WeatherAdvice)
from kg.segment import UNITS_DIR
from kg.tables import TABLES_DIR

from .model import FACT
from .quotes import QuoteIndex

EXTRACTED_DIR = ROOT / "data" / "extracted"
PROMPTS_DIR = Path(__file__).parent / "prompts"
PROMPT_VERSION = "v1"
SLOTS = ("{{subtypes}}", "{{vocabularies}}", "{{default_scope}}", "{{unit}}")


class ExtractError(Exception):
    pass


def slug(entry) -> str:
    return entry.id.split(":", 1)[1]


def file_stem(unit_id: str) -> str:
    """unit:<source slug>:<hash>[-n] -> <hash>[-n] (Windows file names cannot hold ':')."""
    return unit_id.split(":", 2)[2]


def load_units(entry) -> list[dict]:
    path = UNITS_DIR / slug(entry) / "units.jsonl"
    if not path.exists():
        raise ExtractError("%s not found: run kg.segment first" % path)
    return [json.loads(line) for line in open(path, encoding="utf-8")]


def load_tables(entry) -> dict[str, dict]:
    """Stitched tables keyed by every part ref."""
    path = TABLES_DIR / slug(entry) / "tables.jsonl"
    out = {}
    if path.exists():
        for line in open(path, encoding="utf-8"):
            t = json.loads(line)
            for ref in t["table_refs"]:
                out[ref] = t
    return out


def get_unit(entry, unit_id: str) -> dict:
    hits = [u for u in load_units(entry) if u["id"] == unit_id]
    if len(hits) != 1:
        raise ExtractError("unit %s found %d times in units.jsonl" % (unit_id, len(hits)))
    return hits[0]


# --- rendering ---------------------------------------------------------------------------

def _pages(lo, hi) -> str:
    return str(lo) if lo == hi else "%s-%s" % (lo, hi)


def render_unit(entry, unit: dict, tables: dict[str, dict]) -> tuple[str, list[dict]]:
    """The unit as the model sees it, and the text segments the quote check searches."""
    lines, segments, done = [], [], set()
    for it in unit["items"]:
        page = it.get("pdf_page")
        base = {"ref": it["ref"], "pdf_page": page, "printed_page": it.get("printed_page"),
                "subheading": it.get("subheading")}
        if it["kind"] == "subheading":
            lines.append("[p.%s] ## %s" % (page, it["text"]))
            segments.append({**base, "text": it["text"]})
        elif it["kind"] == "text":
            lines.append("[p.%s] %s" % (page, it["text"]))
            segments.append({**base, "text": it["text"]})
        elif it["kind"] == "table":
            if it["ref"] in done:
                continue
            t = tables.get(it["ref"])
            if t is None:
                raise ExtractError("table %s of unit %s is not in tables.jsonl: run kg.tables first"
                                   % (it["ref"], unit["id"]))
            done.update(t["table_refs"])
            page_of = dict(zip(t["table_refs"], t["pdf_pages"]))
            lines.append("[p.%s] TABLE %s" % (_pages(min(t["pdf_pages"]), max(t["pdf_pages"])),
                                               " + ".join(t["table_refs"])))
            header = " | ".join(t["header"])
            lines.append("[%s header] %s" % (t["table_refs"][0], header))
            segments.append({**base, "ref": t["table_refs"][0], "text": header})
            for row in t["rows"]:
                part, r = row[0]["part_ref"], row[0]["row"]
                text = " | ".join(c["text"] or "" for c in row)
                lines.append("[%s row %d] %s" % (part, r, text))
                segments.append({**base, "ref": "%s row %d" % (part, r), "pdf_page": page_of[part],
                                 "printed_page": entry.printed_page(page_of[part]), "text": text})
    lo, hi = unit["pdf_pages"]
    printed = [p for p in (entry.printed_page(lo), entry.printed_page(hi)) if p]
    head = ["SECTION: %s" % unit["section_path"], "CHAPTER: %s" % unit["chapter"]["title"],
            "PAGES: PDF %s%s" % (_pages(lo, hi), " (printed %s)" % _pages(*printed) if len(printed) == 2 else ""),
            "", "TEXT:"]
    return "\n".join(head + lines), segments


def render_default_scope(entry, unit: dict) -> str:
    rules = {r.label(): r for r in entry.default_scope}
    out = []
    for label in unit["default_scope"]:
        r = rules[label]
        out.append('- RULE: %s\n  QUOTE (PDF p. %d): "%s"' % (label, r.pdf_page, r.quote))
    return "\n".join(out) or "none"


def render_vocabularies() -> str:
    lines = ["- %s: %s" % (name, ", ".join(v.value for v in enum)) for name, enum in (
        ("operation", OperationType), ("anchor", Anchor), ("offset_unit", OffsetUnit),
        ("op", ConditionOp), ("duration_group", DurationGroup), ("dose_basis", DoseBasis),
        ("control_class", ControlClass), ("advice", WeatherAdvice), ("kind", CautionKind))]
    lines.append("- condition variable (unit, value type):")
    for name, spec in CONDITION_VARIABLES.items():
        lines.append("  - %s (%s, %s)" % (name, spec.unit.value if spec.unit else "no unit",
                                         spec.value_type.value))
    return "\n".join(lines)


def prompt_template(version: str = PROMPT_VERSION) -> tuple[str, str]:
    raw = (PROMPTS_DIR / ("%s.md" % version)).read_bytes()
    return raw.decode("utf-8"), hashlib.sha256(raw).hexdigest()


def build(entry, unit: dict, model: str, tables: dict | None = None) -> dict:
    """The filled prompt, the quote segments and the cache key for one unit."""
    template, prompt_sha = prompt_template()
    for slot in SLOTS:
        if template.count(slot) != 1:
            raise ExtractError("prompt %s must contain %s exactly once" % (PROMPT_VERSION, slot))
    unit_text, segments = render_unit(entry, unit, load_tables(entry) if tables is None else tables)
    scope = render_default_scope(entry, unit)
    unit_sha = hashlib.sha256(("%s\n\n%s" % (scope, unit_text)).encode("utf-8")).hexdigest()
    key = hashlib.sha256(json.dumps([unit_sha, PROMPT_VERSION, prompt_sha, model]).encode()).hexdigest()
    prompt = (template.replace("{{subtypes}}", ", ".join(s.value for s in Subtype))
              .replace("{{vocabularies}}", render_vocabularies())
              .replace("{{default_scope}}", scope).replace("{{unit}}", unit_text))
    return {"prompt": prompt, "segments": segments, "prompt_sha256": prompt_sha,
            "unit_text_sha256": unit_sha, "cache_key": key}


def out_dir(entry) -> Path:
    return EXTRACTED_DIR / slug(entry)


def cached(entry, unit: dict, built: dict) -> Path | None:
    path = out_dir(entry) / ("%s.json" % file_stem(unit["id"]))
    if path.exists() and json.loads(path.read_text(encoding="utf-8")).get("cache_key") == built["cache_key"]:
        return path
    return None


# --- checking an answer ---------------------------------------------------------------------

def _errors(e: ValidationError) -> list[str]:
    return ["%s: %s" % (".".join(map(str, x["loc"])) or "(fact)", x["msg"]) for x in e.errors()]


def check_answer(text: str, segments: list[dict]) -> dict:
    """Parse into the raw model and find every quote. Nothing is corrected."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return {"parse_error": "not JSON: %s" % e, "facts": []}
    if not isinstance(data, list):
        return {"parse_error": "the answer must be a JSON list of facts", "facts": []}
    index, facts = QuoteIndex(segments), []
    for i, item in enumerate(data):
        try:
            fact, errors = FACT.validate_python(item).model_dump(mode="json"), []
        except ValidationError as e:
            fact, errors = None, _errors(e)
        quote = item.get("quote") if isinstance(item, dict) else None
        found = index.find(quote) if isinstance(quote, str) else {"ok": False, "occurrences": 0, "refs": []}
        subs = [s.get("subheading") for s in segments if s["ref"] in found["refs"]]
        facts.append({"index": i, "fact": fact, "answer": item, "parse_errors": errors,
                      "quote_check": found, "subheading": subs[0] if subs else None})
    return {"parse_error": None, "facts": facts}


def summarise(record: dict) -> dict:
    facts = record["facts"]
    ok = [f for f in facts if f["fact"]]
    steps = [(f["index"], s) for f in ok for s in f["fact"]["steps"]]
    qty = [(i, s, q) for i, s in steps for q in s["applies"]]
    return {
        "facts": len(facts),
        "by_subtype": dict(Counter(f["fact"]["subtype"] for f in ok)),
        "by_subheading": dict(Counter(f["subheading"] or "(none)" for f in facts)),
        "parse_failures": [{"index": f["index"], "errors": f["parse_errors"]} for f in facts if not f["fact"]],
        "quote_failures": [{"index": f["index"], "quote": (f["answer"] or {}).get("quote")
                            if isinstance(f["answer"], dict) else None}
                           for f in facts if not f["quote_check"]["ok"]],
        "quotes_found_more_than_once": [f["index"] for f in facts if f["quote_check"]["occurrences"] > 1],
        "unmapped": [{"index": f["index"], "phrase": p} for f in ok for p in f["fact"]["unmapped"]],
        "basis_inferred": [{"index": i, "target": q["target"], "basis": q["basis"], "raw": q["raw"]}
                           for i, _, q in qty if q["basis_inferred"]],
        "basis_missing": [{"index": i, "target": q["target"], "raw": q["raw"]}
                          for i, _, q in qty if q["raw"] and q["basis"] is None],
        "basis_from_rule": [{"index": i, "target": q["target"], "rule": q["basis_rule"]}
                            for i, _, q in qty if q["basis_rule"]],
        "quantity_ref": [{"index": i, "target": q["target"], "step": s["instruction_en"]}
                         for i, s, q in qty if q["quantity_ref"]],
        "steps_without_operation": [{"index": i, "step": s["instruction_en"]}
                                    for i, s in steps if s["operation"] is None],
    }


def ingest(entry, unit: dict, model: str, answer: str, force: bool = False) -> tuple[Path, dict]:
    built = build(entry, unit, model)
    path = out_dir(entry) / ("%s.json" % file_stem(unit["id"]))
    if cached(entry, unit, built) and not force:
        raise ExtractError("%s already holds an answer with this cache key; use --force to replace it" % path)
    checked = check_answer(answer, built["segments"])
    record = {
        "unit_id": unit["id"], "source_id": entry.id, "section_path": unit["section_path"],
        "chapter": unit["chapter"], "pdf_pages": unit["pdf_pages"], "regions": unit["regions"],
        "default_scope": unit["default_scope"],
        "prompt_version": PROMPT_VERSION, "prompt_sha256": built["prompt_sha256"],
        "extraction_model": model, "unit_text_sha256": built["unit_text_sha256"],
        "cache_key": built["cache_key"], "created_at": datetime.now(timezone.utc).isoformat(),
        "answer": answer, "parse_error": checked["parse_error"], "facts": checked["facts"],
    }
    record["summary"] = summarise(record)
    s = record["summary"]
    record["ok"] = not (record["parse_error"] or s["parse_failures"] or s["quote_failures"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return path, record
