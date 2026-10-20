"""Run segmentation for one source, write units.jsonl and report.json, print the report."""

import json
from pathlib import Path

from . import (TOKEN_LIMIT, UNITS_DIR, build_tree, check_scopes, heading_like_list_items,
               make_units, numbering_gaps, resolve_scopes)

AUDIT = ("caps_decisions", "placeholders", "late_parents", "duplicate_numbers", "promotions",
         "unparsed_headings", "before_chapter_heading", "chapter_heading_not_found",
         "heading_fixes_applied", "running_headers_dropped")


def segment(entry, docling_dir: Path) -> tuple[list[dict], dict]:
    from docling_core.types.doc import DoclingDocument
    doc = DoclingDocument.load_from_json(docling_dir / "document.json")
    built, log = build_tree(doc, entry)
    units = make_units(entry, built)
    checks = check_scopes(entry, built, units)
    resolve_scopes(entry, units, checks)
    largest = sorted(units, key=lambda u: -u["approx_tokens"])
    report = {
        "source_id": entry.id, "docling_dir": str(docling_dir),
        "units": len(units), "chapters": len(built),
        "front_matter_items_skipped": len(log["front_matter_items"]),
        "largest_units": [{"section_path": u["section_path"], "approx_tokens": u["approx_tokens"],
                           "pdf_pages": u["pdf_pages"]} for u in largest[:10]],
        "over_token_limit": [u["section_path"] for u in units if u["approx_tokens"] > TOKEN_LIMIT],
        "units_without_text": [{"section_path": u["section_path"], "tables": len(u["table_refs"]),
                                "pdf_pages": u["pdf_pages"]} for u in units if u["text_items"] == 0],
        "numbering_gaps": numbering_gaps(built),
        "heading_like_list_items": heading_like_list_items(units),
        "scope_checks": [{k: v for k, v in c.items() if not k.startswith("_")} for c in checks],
        **{k: log[k] for k in AUDIT},
    }
    report["failed"] = [c for c in report["scope_checks"] if not c["ok"]]
    return units, report


def write(entry, units, report) -> Path:
    out = UNITS_DIR / entry.id.split(":", 1)[1]
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "units.jsonl", "w", encoding="utf-8") as f:
        for u in units:
            f.write(json.dumps({k: v for k, v in u.items() if not k.startswith("_")},
                               ensure_ascii=False) + "\n")
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def print_report(r: dict, focus: tuple[str, ...] = ("RICE", "WHEAT")) -> None:
    def in_focus(text):
        return any(text.startswith(f) or (" %s " % f) in text for f in focus)

    print("=== %s: %d units in %d chapters (%d front-matter items skipped) ===" % (
        r["source_id"], r["units"], r["chapters"], r["front_matter_items_skipped"]))
    print("largest units (approx tokens):")
    for u in r["largest_units"]:
        print("  %6d  PDF %s  %s" % (u["approx_tokens"], u["pdf_pages"], u["section_path"][:110]))
    print("units over %d approx tokens: %s" % (TOKEN_LIMIT, r["over_token_limit"] or "none"))
    print("units without text: %d" % len(r["units_without_text"]))
    for u in r["units_without_text"]:
        if in_focus(u["section_path"]):
            print("  PDF %s  tables %d  %s" % (u["pdf_pages"], u["tables"], u["section_path"][:110]))
    print("headings that didn't parse: %d" % len(r["unparsed_headings"]))
    for h in r["unparsed_headings"]:
        print("  p.%s %r" % (h["pdf_page"], h["heading"][:80]))
    for key in ("placeholders", "late_parents", "duplicate_numbers", "promotions"):
        rows = [x for x in r[key] if in_focus(x.get("chapter", "")) or x.get("pdf_page", 999) < 137]
        print("%s: %d (rice/wheat: %d)" % (key, len(r[key]), len(rows)))
        for x in rows:
            print("  ", {k: v for k, v in x.items() if k != "chapter"})
    gaps = [g for g in r["numbering_gaps"] if in_focus(g["chapter"])]
    print("numbering gaps: %d (rice/wheat: %d)" % (len(r["numbering_gaps"]), len(gaps)))
    for g in gaps:
        print("   %s: missing %s under %r" % (g["chapter"], ", ".join(g["missing"]), g["under"][:60]))
    lists = [x for x in r["heading_like_list_items"] if in_focus(x["unit"])]
    print("heading-like list items: %d (rice/wheat: %d)" % (len(r["heading_like_list_items"]), len(lists)))
    for x in lists:
        print("   p.%s %r  in %s" % (x["pdf_page"], x["text"][:50], x["unit"][-60:]))
    print("caps decisions: %d" % len(r["caps_decisions"]))
    for c in r["caps_decisions"]:
        if c["pdf_page"] and c["pdf_page"] < 137:
            print("   p.%s %-15s %r %s" % (c["pdf_page"], c["decision"], c["heading"][:55], c["detail"][:60]))
    print("before chapter heading:", [(x["chapter"], x["pdf_page"], len(x["refs"]))
                                      for x in r["before_chapter_heading"]])
    print("chapter heading not found:", [x["chapter"] for x in r["chapter_heading_not_found"]])
    print("running headers dropped: %d" % len(r["running_headers_dropped"]))
    print("heading fixes applied: %d" % len(r["heading_fixes_applied"]))
    print("scope checks:")
    for c in r["scope_checks"]:
        print("  %-4s %-8s %-13s %r PDF %s -> %d match(es), section spans PDF %s" % (
            "ok" if c["ok"] else "FAIL", c["status"], c["kind"], c["heading"][:50], c["pdf_pages"],
            c["matches"], c["section_pdf_pages"]))
    if r["failed"]:
        print("FAILED: %d section scope(s) do not match exactly one section" % len(r["failed"]))
