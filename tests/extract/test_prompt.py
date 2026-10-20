"""Offline tests for prompt v1, rendering, caching and ingest (kg.extract)."""

import json
import re

import pytest

import kg.extract as ex
from kg.extract.model import NESTED, SUBTYPES
from kg.registry import read_registry

ENTRY = read_registry()[0]
UNIT = {
    "id": "unit:tnau_agriculture_2020:abc123", "source_id": ENTRY.id, "kind": "leaf",
    "chapter": {"number": "1", "title": "RICE", "status": "approved"},
    "section_path": "RICE > CROP PROTECTION > A) Pest management > ii) Main field",
    "items": [
        {"ref": "#/texts/1", "kind": "subheading", "text": "Nutrient management", "pdf_page": 30,
         "subheading": "Nutrient management"},
        {"ref": "#/texts/2", "kind": "text", "text": "Apply 40 kg of DAP before the last puddling.",
         "pdf_page": 30, "printed_page": "18", "subheading": "Nutrient management"},
        {"ref": "#/tables/53", "kind": "table", "text": None, "pdf_page": 63, "printed_page": "51"},
        {"ref": "#/tables/54", "kind": "table", "text": None, "pdf_page": 64, "printed_page": "52"},
    ],
    "pdf_pages": [30, 64], "regions": [{"id": "state:33", "origin": "source"}],
    "default_scope": [r.label() for r in ENTRY.default_scope if "per_ha" in r.rule],
}
ETL = {"table_refs": ["#/tables/53", "#/tables/54"], "pdf_pages": [63, 64], "header": ["Pest", "ETL"],
       "rows": [[{"text": "Stem borer", "part_ref": "#/tables/53", "row": 1},
                 {"text": "10% dead hearts", "part_ref": "#/tables/53", "row": 1}],
                [{"text": "Brown planthopper", "part_ref": "#/tables/54", "row": 0},
                 {"text": "1 hopper/ tiller", "part_ref": "#/tables/54", "row": 0}]]}
TABLES = {ref: ETL for ref in ETL["table_refs"]}


def field_names():
    names = set()
    for m in SUBTYPES + NESTED:
        names |= set(m.model_fields)
    return names


def test_prompt_field_reference_matches_the_raw_model():
    text, _ = ex.prompt_template()
    section = text.split("## Field reference", 1)[1].split("\n## ", 1)[0]
    listed = set(re.findall(r"`([a-z_0-9]+)`", section))
    assert listed == field_names(), (sorted(field_names() - listed), sorted(listed - field_names()))


def test_prompt_has_each_slot_once_and_vocabularies_come_from_code():
    text, _ = ex.prompt_template()
    assert all(text.count(s) == 1 for s in ex.SLOTS)
    vocab = ex.render_vocabularies()
    assert "last_puddling" in vocab and "spider_count_per_hill (count, number)" in vocab


def test_render_unit_and_segments():
    text, segments = ex.render_unit(ENTRY, UNIT, TABLES)
    assert "[p.30] ## Nutrient management" in text
    assert "[p.63-64] TABLE #/tables/53 + #/tables/54" in text and text.count("TABLE") == 1
    assert "[#/tables/54 row 0] Brown planthopper | 1 hopper/ tiller" in text
    row = next(s for s in segments if s["ref"] == "#/tables/54 row 0")
    assert (row["pdf_page"], row["printed_page"]) == (64, "52")


def test_missing_table_fails_loudly():
    with pytest.raises(ex.ExtractError, match="run kg.tables first"):
        ex.render_unit(ENTRY, UNIT, {})


def test_default_scope_rule_is_shown_with_its_quote():
    scope = ex.render_default_scope(ENTRY, UNIT)
    assert scope.startswith("- RULE: dose basis = per_ha") and "QUOTE (PDF p. 63)" in scope
    assert ex.render_default_scope(ENTRY, {**UNIT, "default_scope": []}) == "none"


def test_cache_key_depends_on_unit_text_and_model():
    a = ex.build(ENTRY, UNIT, "model-a", TABLES)
    assert a["cache_key"] == ex.build(ENTRY, UNIT, "model-a", TABLES)["cache_key"]
    assert a["cache_key"] != ex.build(ENTRY, UNIT, "model-b", TABLES)["cache_key"]
    changed = {**UNIT, "items": UNIT["items"][:2]}
    assert a["cache_key"] != ex.build(ENTRY, changed, "model-a", TABLES)["cache_key"]
    assert "{{" not in a["prompt"] and "Apply 40 kg of DAP" in a["prompt"]


GOOD = {"subtype": "NutrientDose", "dose_basis": "blanket", "summary_en": "DAP before last puddling",
        "quote": "Apply 40 kg of DAP before the last puddling.",
        "steps": [{"order": 1, "operation": "fertilizer_application", "anchor": "last_puddling",
                   "timing_raw": "before the last puddling", "instruction_en": "Apply DAP.",
                   "applies": [{"target": "DAP", "value": 40, "unit": "kg", "basis": "per 20 cents",
                                "basis_inferred": True, "raw": "40 kg of DAP"}]}]}


def test_ingest_stores_failures_without_fixing_them(tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "EXTRACTED_DIR", tmp_path)
    monkeypatch.setattr(ex, "load_tables", lambda entry: TABLES)
    bad_quote = {**GOOD, "quote": "Apply 40 kg DAP before the last puddling."}
    bad_parse = {**GOOD, "dose_basis": "per_ha"}
    answer = json.dumps([GOOD, bad_quote, bad_parse])
    path, rec = ex.ingest(ENTRY, UNIT, "model-a", answer)
    s = rec["summary"]
    assert not rec["ok"] and [f["index"] for f in s["quote_failures"]] == [1]
    assert [f["index"] for f in s["parse_failures"]] == [2]
    assert s["basis_inferred"][0]["target"] == "DAP"
    assert s["by_subheading"] == {"Nutrient management": 2, "(none)": 1}   # an unfound quote has no place
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["answer"] == answer and stored["facts"][1]["answer"]["quote"] == bad_quote["quote"]
    assert stored["extraction_model"] == "model-a" and stored["prompt_version"] == "v1"
    with pytest.raises(ex.ExtractError, match="already holds an answer"):
        ex.ingest(ENTRY, UNIT, "model-a", answer)


def test_answer_that_is_not_a_json_list(tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "EXTRACTED_DIR", tmp_path)
    monkeypatch.setattr(ex, "load_tables", lambda entry: TABLES)
    _, rec = ex.ingest(ENTRY, UNIT, "model-a", "Here are the facts: []")
    assert not rec["ok"] and rec["parse_error"].startswith("not JSON")
    _, rec = ex.ingest(ENTRY, UNIT, "model-a", json.dumps(GOOD), force=True)
    assert rec["parse_error"] == "the answer must be a JSON list of facts"
    _, rec = ex.ingest(ENTRY, UNIT, "model-a", json.dumps([GOOD]), force=True)
    assert rec["ok"]


def test_file_stem_has_no_colon():
    assert ex.file_stem("unit:tnau_agriculture_2020:abc123-2") == "abc123-2"
