import argparse
import json
import sys
from pathlib import Path

from kg.registry import read_registry

from . import (ExtractError, build, cached, file_stem, get_unit, ingest, load_units, out_dir)


def _entry(source_id):
    hits = [e for e in read_registry() if e.id == source_id]
    if not hits:
        raise SystemExit("unknown source %s" % source_id)
    return hits[0]


def print_summary(record: dict) -> None:
    s = record["summary"]
    print("=== %s  [%s]" % (record["section_path"], record["unit_id"]))
    print("  model %s, prompt %s, %s" % (record["extraction_model"], record["prompt_version"],
                                         "OK" if record["ok"] else "FAILED CHECKS"))
    if record["parse_error"]:
        print("  answer did not parse:", record["parse_error"])
    print("  facts: %d  by subtype: %s" % (s["facts"], s["by_subtype"]))
    print("  by sub-heading: %s" % s["by_subheading"])
    for key in ("parse_failures", "quote_failures", "quotes_found_more_than_once", "unmapped",
                "basis_inferred", "basis_missing", "basis_from_rule", "quantity_ref", "steps_without_operation"):
        print("  %s: %d" % (key, len(s[key])))
        for x in s[key]:
            print("    ", x)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m kg.extract", description="Step 9: extraction (no API calls)")
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("find", help="list units whose section path contains TEXT")
    f.add_argument("source_id")
    f.add_argument("text")
    for name in ("prepare", "ingest"):
        q = sub.add_parser(name)
        q.add_argument("source_id")
        q.add_argument("--unit", required=True)
        q.add_argument("--model", required=True, help="the model that answers, recorded as extraction_model")
        if name == "ingest":
            q.add_argument("--response", required=True, type=Path, help="file holding the model's answer")
            q.add_argument("--force", action="store_true", help="replace an answer with the same cache key")
    r = sub.add_parser("report", help="summaries of every stored answer")
    r.add_argument("source_id")
    a = p.parse_args(argv)
    entry = _entry(a.source_id)
    try:
        if a.cmd == "find":
            for u in load_units(entry):
                if a.text.lower() in u["section_path"].lower():
                    print("%s  PDF %s  ~%d tokens  %s" % (u["id"], u["pdf_pages"], u["approx_tokens"],
                                                          u["section_path"]))
            return 0
        if a.cmd == "report":
            records = [json.loads(x.read_text(encoding="utf-8")) for x in sorted(out_dir(entry).glob("*.json"))
                       if x.name != "report.json"]
            for rec in records:
                print_summary(rec)
            (out_dir(entry) / "report.json").write_text(json.dumps(
                [{k: rec[k] for k in ("unit_id", "section_path", "extraction_model", "prompt_version",
                                      "ok", "summary")} for rec in records], indent=2, ensure_ascii=False),
                encoding="utf-8")
            return 0 if all(rec["ok"] for rec in records) else 1
        unit = get_unit(entry, a.unit)
        if a.cmd == "prepare":
            built = build(entry, unit, a.model)
            hit = cached(entry, unit, built)
            if hit:
                print("cached: %s (same unit text, prompt and model)" % hit)
                return 0
            path = out_dir(entry) / "prompts" / ("%s.md" % file_stem(unit["id"]))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(built["prompt"], encoding="utf-8")
            print("prompt written: %s (%d chars, %d quote segments)" % (path, len(built["prompt"]),
                                                                        len(built["segments"])))
            return 0
        path, record = ingest(entry, unit, a.model, a.response.read_text(encoding="utf-8"), a.force)
        print_summary(record)
        print("written:", path)
        return 0 if record["ok"] else 1
    except ExtractError as e:
        raise SystemExit(str(e))


if __name__ == "__main__":
    sys.exit(main())
