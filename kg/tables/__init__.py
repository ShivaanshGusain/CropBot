"""Tables (step 8, no LLM): rebuild ruled parts from the text layer (kg.tables.rebuild), stitch, check
against the page, pivot variety tables.

  uv run python -m kg.tables source:tnau_agriculture_2020 [--chapters RICE,WHEAT]

Input: data/docling/<id>/document.json and data/units/<id>/units.jsonl (run kg.segment first).
Output: data/tables/<id>/{tables.jsonl, varieties.jsonl, report.json} and data/review/tables.csv
(all gitignored).
"""

import csv
import json
from collections import Counter

from kg.registry import ROOT

from .check import PageChecker
from .rebuild import Rebuilt, crossings, rebuild
from .stitch import Part, Table, stitch_unit
from .varieties import (duration_group_of, duration_outliers, duration_reference, is_variety_table,
                        pivot, possible_duplicates, variety_mentions)

TABLES_DIR = ROOT / "data" / "tables"
REVIEW_CSV = ROOT / "data" / "review" / "tables.csv"
REVIEW_FIELDS = ("source_id", "chapter", "table_ref", "pdf_page", "printed_page", "check", "detail",
                 "docling", "page", "variety_id")
COW_BOX_PAGE = 134       # the COW(W)1 block in "I. SEASON AND VARIETY" of the wheat chapter
COW_BOX_REASON = ("Docling reading order: content of 'I. SEASON AND VARIETY' placed before "
                  "the chapter heading")


def run(entry, docling_dir, units_path, chapters: tuple[str, ...]) -> dict:
    from docling_core.types.doc import DoclingDocument
    doc = DoclingDocument.load_from_json(docling_dir / "document.json")
    items_by_ref = {t.self_ref: t for t in doc.tables}
    units = [json.loads(line) for line in open(units_path, encoding="utf-8")]
    units = [u for u in units if u["chapter"]["title"] in chapters]
    chapter_by_title = {c.path_label(): c for c in entry.chapters}

    checker = PageChecker(ROOT / entry.file)
    rebuilt: dict[str, Rebuilt] = {}         # by part ref, with Docling's own part kept for the checks
    originals: dict[str, Part] = {}

    def prepare(part: Part) -> Part:
        if part.ref not in rebuilt:
            originals[part.ref] = part
            rebuilt[part.ref] = rebuild(part, checker.page(part.pdf_page))
        return rebuilt[part.ref].part

    tables: list[Table] = []
    for u in units:
        tables += stitch_unit(u, items_by_ref, prepare)

    checks, review, checked = [], [], set()
    for t in tables:
        for m in t.merged_rows:
            review.append({"chapter": t.chapter, "check": "row continued across page break",
                           "table_ref": m["part_ref"], "pdf_page": m["pdf_page"],
                           "detail": "row %d merged into %s: %r" % (m["row"], m["into"], m["text"])})
        for part in t.parts:
            if part.ref in checked:          # a split table shares its part with the table before it
                continue
            checked.add(part.ref)
            original, res = originals[part.ref], rebuilt[part.ref]
            summary, problems = checker.check(original)          # the page check reads Docling's own cells
            checks.append(summary)
            review += [{**p, "chapter": t.chapter} for p in problems]
            for p in crossings(original, checker.page(part.pdf_page)):
                fixed = (p["row"], p["col"]) in res.changes
                review.append({**{k: p[k] for k in ("table_ref", "pdf_page", "check", "docling", "page")},
                               "chapter": t.chapter, "detail": "%s (%s)" % (
                                   p["detail"], "resolved by the rebuild" if fixed else "not resolved")})
            for (r, c), (text, new_col) in sorted(res.changes.items()):
                before = next(x for x in original.cells if (x["row"], x["col"]) == (r, c))
                review.append({"chapter": t.chapter, "check": "rebuilt from rulings", "table_ref": part.ref,
                               "pdf_page": part.pdf_page, "docling": before["text"], "page": text,
                               "detail": "row %d col %d%s" % (r, c, ", now col %d span %d" % new_col
                                                              if new_col else "")})
            review += [{"chapter": t.chapter, "check": "rebuild", "table_ref": part.ref,
                        "pdf_page": part.pdf_page, "detail": f}
                       for f in res.flags if not f.startswith("no rulings")]

    reference, reference_ref = duration_reference(tables)
    varieties, seen = [], {}
    for t in (t for t in tables if is_variety_table(t)):
        chapter = chapter_by_title[t.chapter]
        records, rows = pivot(t, entry, chapter, duration_group_of(t.section_path))
        review += [{**r, "chapter": t.chapter} for r in rows]
        for v in records:
            if v.id in seen:
                review.append({"chapter": t.chapter, "check": "variety", "table_ref": t.parts[0].ref,
                               "pdf_page": t.parts[0].pdf_page, "variety_id": v.id,
                               "detail": "same name in two tables; first kept from %s" % seen[v.id]})
                continue
            seen[v.id] = t.parts[0].ref
            varieties.append(v)
            if t.parts[0].pdf_page == COW_BOX_PAGE:
                # p. 134 has two fixes; "corrected" only if the box really landed in its section
                fixed = "> I. SEASON AND VARIETY" in t.section_path and any(
                    f.status == "approved" and f.pdf_page == COW_BOX_PAGE for f in entry.reading_order_fix)
                review.append({"chapter": t.chapter, "check": "variety", "table_ref": t.parts[0].ref,
                               "pdf_page": COW_BOX_PAGE, "variety_id": v.id,
                               "detail": COW_BOX_REASON + (" (corrected by an approved reading-order fix)"
                                                           if fixed else "")})
            if v.crop_id is None:
                review.append({"chapter": t.chapter, "check": "variety", "table_ref": t.parts[0].ref,
                               "pdf_page": t.parts[0].pdf_page, "variety_id": v.id,
                               "detail": "crop_id pending: chapter %r is %s" % (
                                   t.chapter, chapter.status)})

    cow_context = [{"ref": i["ref"], "text": i.get("text"), "section_path": u["section_path"]}
                   for u in units if u["chapter"]["title"] == "WHEAT"
                   for i in u["items"] if i["pdf_page"] == COW_BOX_PAGE and i["kind"] == "text"]
    for r in review:
        r.setdefault("source_id", entry.id)
        r["printed_page"] = entry.printed_page(r["pdf_page"]) if r.get("pdf_page") else None
    return {"tables": tables, "checks": checks, "varieties": varieties, "review": review,
            "duplicates": possible_duplicates(varieties, variety_mentions(units, tables)),
            "duration_reference": {"values": reference, "table_ref": reference_ref},
            "duration_outliers": duration_outliers(varieties, reference),
            "cow_box_context": cow_context, "chapters": chapters}


def table_record(t: Table) -> dict:
    return {"unit_id": t.unit_id, "section_path": t.section_path, "chapter": t.chapter,
            "table_refs": t.refs, "pdf_pages": [p.pdf_page for p in t.parts], "header": t.header,
            "rows": [[{k: c[k] for k in ("text", "part_ref", "row", "col", "row_span", "col_span",
                                         "continued_from") if k in c}
                      for c in row] for row in t.rows],
            "stitch_log": t.stitch_log, "merged_rows": t.merged_rows,
            "original_cells": {p.ref: p.docling_cells or p.cells for p in t.parts}}


def write(entry, result) -> dict:
    out = TABLES_DIR / entry.id.split(":", 1)[1]
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "tables.jsonl", "w", encoding="utf-8") as f:
        for t in result["tables"]:
            f.write(json.dumps(table_record(t), ensure_ascii=False) + "\n")
    with open(out / "varieties.jsonl", "w", encoding="utf-8") as f:
        for v in result["varieties"]:
            f.write(v.model_dump_json() + "\n")
    REVIEW_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(REVIEW_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REVIEW_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(result["review"])
    stitched = [t for t in result["tables"] if len(t.parts) > 1]
    report = {
        "source_id": entry.id, "chapters": list(result["chapters"]),
        "tables": len(result["tables"]), "parts": sum(len(t.parts) for t in result["tables"]),
        "stitched": [{"table_refs": t.refs, "section_path": t.section_path, "log": t.stitch_log}
                     for t in stitched],
        "merged_rows": [{**m, "section_path": t.section_path} for t in result["tables"] for m in t.merged_rows],
        "checks": {"parts_ruled": sum(c["ruled"] for c in result["checks"]),
                   "parts_unruled": sum(not c["ruled"] for c in result["checks"])},
        "varieties": Counter(v.duration_group.value if v.duration_group else "none"
                             for v in result["varieties"]),
        "variety_ids": [v.id for v in result["varieties"]],
        "review_rows": len(result["review"]),
        "review_by_reason": Counter(r["check"] if r["check"] != "variety" else r["detail"].split(":")[0]
                                    for r in result["review"]),
        "possible_duplicates": result["duplicates"],
        "duration_reference": result["duration_reference"],
        "duration_outliers": result["duration_outliers"],
        "cow_box_context": result["cow_box_context"],
        "outputs": {"dir": str(out), "review_csv": str(REVIEW_CSV)},
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def print_report(r: dict) -> None:
    print("=== %s, chapters %s: %d tables from %d parts ===" % (
        r["source_id"], ", ".join(r["chapters"]), r["tables"], r["parts"]))
    print("stitched (%d):" % len(r["stitched"]))
    for s in r["stitched"]:
        print("  %s  %s" % (" + ".join(s["table_refs"]), s["section_path"][-60:]))
    print("rows continued across a page break, merged and sent to review (%d):" % len(r["merged_rows"]))
    for m in r["merged_rows"]:
        print("  %s row %d -> %s  %r" % (m["part_ref"], m["row"], m["into"], m["text"][:70]))
    print("page check: %d ruled parts, %d unruled" % (r["checks"]["parts_ruled"], r["checks"]["parts_unruled"]))
    print("Variety records: %d %s" % (len(r["variety_ids"]), dict(r["varieties"])))
    print("review rows: %d" % r["review_rows"])
    for reason, n in sorted(r["review_by_reason"].items(), key=lambda kv: -kv[1]):
        print("  %4d  %s" % (n, reason))
    print("possible duplicates (not merged): %d" % len(r["possible_duplicates"]))
    for d in r["possible_duplicates"]:
        print("  %r (%s)  ~  %r (%s)" % (d["a"], d["a_id"] or "mention", d["b"], d["b_id"] or "mention"))
    ref = r["duration_reference"]
    print("duration reference %s from %s; outliers: %d" % (ref["values"], ref["table_ref"],
                                                          len(r["duration_outliers"])))
    for o in r["duration_outliers"]:
        print("  %s: %s group, %s days, nearer to %s" % (o["variety"], o["group"], o["duration_days"],
                                                        o["nearer_to"]))
    print("COW(W)1 box context for step 9:")
    for c in r["cow_box_context"]:
        print("  %s %r" % (c["ref"], (c["text"] or "")[:80]))
    print("written:", r["outputs"])
