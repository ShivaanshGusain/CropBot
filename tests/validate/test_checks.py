"""Offline tests for the step 11 checks (kg.validate). Failures go to review; nothing is fixed."""

import copy

from kg.extract.model import FACT as RAW
from kg.validate import (check_alternatives, check_ingredients, check_quote_location, check_raw_numbers,
                         check_review_kept, check_value_ranges)
from kg.schema.concepts import ActiveIngredient, Fertilizer

SPAN = {"id": "span:x", "source_id": "source:tnau_agriculture_2020", "pdf_page": 64, "section_path": "s",
        "quote": "q", "table_ref": None, "table_row": None, "table_col": None, "extraction_method": "native_text"}


def step(order=1, applies=(), **kw):
    s = {"order": order, "alt_group": None, "alt_option": None, "alt_priority": None, "operation": "spraying",
         "offset_min": None, "offset_max": None, "offset_unit": "days", "applies": list(applies), "conditions": []}
    return {**s, **kw}


def fact(steps=(), **kw):
    return {"id": "rec:x", "subtype": "ControlMeasure", "status": "extracted", "steps": list(steps),
            "evidence": [copy.deepcopy(SPAN)], **kw}


def qty(target, value=None, unit="kg", basis="per_ha", formulation=None, raw="r", **kw):
    return {"target_id": target, "value": value, "unit": unit, "basis": basis, "formulation": formulation, "raw": raw, **kw}


# 1 quote location
def test_quote_must_be_found_once_and_in_the_row_named():
    qc = {"occurrences": 1, "refs": ["#/tables/56 row 4 + #/tables/57 row 0"]}
    f = fact()
    f["evidence"][0].update(table_ref="#/tables/57", table_row=0)
    assert check_quote_location(f, qc)["status"] == "pass"                         # either piece of a merged row
    f["evidence"][0].update(table_row=3)
    assert check_quote_location(f, qc)["status"] == "fail"
    assert check_quote_location(fact(), {"occurrences": 2, "refs": []})["reason"] == "quote found 2 times in its unit"


# 2 raw numbers
def raw(**fields):
    data = {"subtype": "NutrientDose", "dose_basis": "blanket", "summary_en": "s",
            "quote": "Apply 40 kg of DAP before the last puddling; spray Five packets (1kg/ha) a week later.",
            "steps": [{"order": 1, "operation": "fertilizer_application",
                       "applies": [{"target": "DAP", "value": 40, "unit": "kg", "basis": "x", "raw": "40 kg of DAP"}]}],
            **fields}
    return RAW.validate_python(data).model_dump(mode="json")


def test_every_raw_text_is_in_the_quote_and_every_number_printed():
    ok = raw(steps=[{"order": 1, "operation": "fertilizer_application",
                     "applies": [{"target": "DAP", "value": 40, "unit": "kg", "basis": "x", "raw": "40 kg of DAP"},
                                 {"target": "Azophos", "value": 5, "unit": "packets", "basis": "x",
                                  "raw": "Five packets (1kg/ha)"}]}])
    assert check_raw_numbers(ok)["status"] == "pass"                                 # number words count
    bad = raw(steps=[{"order": 1, "operation": "fertilizer_application", "anchor": "sowing", "offset_min": 7,
                      "offset_max": 7, "timing_raw": "a week later",
                      "applies": [{"target": "DAP", "value": 45, "unit": "kg", "basis": "x", "raw": "40 kg of DAP"},
                                  {"target": "urea", "value": 16, "unit": "kg", "basis": "x", "raw": "16 kg of urea"}]}])
    reason = check_raw_numbers(bad)["reason"]
    assert "DAP value 45 is not printed in '40 kg of DAP'" in reason
    assert "raw of urea '16 kg of urea' is not in the quote" in reason
    assert "offset_min 7 is not printed in 'a week later'" in reason             # "a week" = 7 is an interpretation


# 3 value ranges
def test_moisture_months_offsets_and_doses_within_bounds():
    assert check_value_ranges(fact(subtype="DryingSpec", target_moisture_pct_max=12))["status"] == "pass"
    assert "outside 5-20" in check_value_ranges(fact(target_moisture_pct_max=25))["reason"]
    assert "outside 10-25" in check_value_ranges(fact(threshing_moisture_pct_min=8))["reason"]
    assert "beyond +-72 hours" in check_value_ranges(fact([step(offset_min=96, offset_unit="hours")]))["reason"]
    assert check_value_ranges(fact([step(applies=[qty("nutrient:n", 150)])]))["status"] == "pass"
    assert "above 500" in check_value_ranges(fact([step(applies=[qty("nutrient:n", 600)])]))["reason"]
    assert "above 20" in check_value_ranges(fact([step(applies=[qty("ai:x", 25, "g", "per_kg_seed")])]))["reason"]
    assert "above 50" in check_value_ranges(fact([step(applies=[qty("fertilizer:dap", 60, basis="per_cent_nursery",
                                                                    area_cents=20)])]))["reason"]
    organic = qty("organic_input:fym", 0.08, "t", "per_cent_nursery", area_cents=20)     # 80 kg per cent
    assert check_value_ranges(fact([step(applies=[organic])]))["status"] == "pass"     # organic inputs: up to 100 kg


def test_active_ingredient_per_ha_from_the_formulation():
    good = qty("ai:carbofuran", 25, "kg", formulation="3% CG", raw="Carbofuran 3% CG 25 kg")
    assert check_value_ranges(fact([step(applies=[good])]))["status"] == "pass"            # 0.75 kg a.i.
    typo = {**qty("ai:fipronil", None, "kg", formulation="80%WG", raw="Fipronil 80%WG 50- 62.5 kg"), "min": 50, "max": 62.5}
    r = check_value_ranges(fact([step(applies=[typo])]))
    assert r["status"] == "fail" and "50.00 kg a.i./ha" in r["reason"]
    no_pct = qty("ai:beauveria_bassiana", 2.5, "kg", formulation="1.15 WP")
    r = check_value_ranges(fact([step(applies=[no_pct])]))
    assert r["status"] == "pass" and r["skipped"] == ["ai:beauveria_bassiana: no formulation % to compute a.i."]


# 4 alternatives
FERT = {i: Fertilizer(id=i, name_en=i, n_pct=n, p2o5_pct=p, k2o_pct=0, review_status="approved", source="x")
        for i, n, p in (("fertilizer:dap", 18, 46), ("fertilizer:urea", 46, 0), ("fertilizer:ssp", 0, 16))}


def nursery(urea=16):
    return fact([step(1, [qty("fertilizer:dap", 40)], alt_group=1, alt_option=1),
                 step(1, [qty("fertilizer:urea", urea), qty("fertilizer:ssp", 120)], alt_group=1, alt_option=2)])


def test_alternatives_agree_within_15_percent_on_approved_percentages():
    assert check_alternatives(nursery(), FERT)["status"] == "pass"                   # the schema's worked example
    assert "n totals" in check_alternatives(nursery(urea=30), FERT)["reason"]
    r = check_alternatives(nursery(), {k: v for k, v in FERT.items() if k != "fertilizer:ssp"})
    assert (r["status"], r["applies"]) == ("skip", True) and "fertilizer:ssp" in r["reason"]
    assert check_alternatives(fact([step(applies=[qty("ai:x", 1)])]), FERT)["applies"] is False


# 5 ingredients
def ai(i, status):
    return ActiveIngredient(id=i, name_en=i, use_class="insecticide", reg_status=status, review_status="needs_review")


def test_ingredients_fail_closed():
    f = fact([step(applies=[qty("ai:a", 1), qty("ai:b", 1)])])
    for status in ("unknown", "restricted", "banned"):
        r = check_ingredients(f, {"ai:a": ai("ai:a", "registered"), "ai:b": ai("ai:b", status)})
        assert r["status"] == "fail" and "ai:b=%s" % status in r["reason"]
    assert check_ingredients(f, {"ai:a": ai("ai:a", "registered")})["reason"].endswith("ai:b=not seeded")
    assert check_ingredients(f, {"ai:a": ai("ai:a", "registered"), "ai:b": ai("ai:b", "registered")})["status"] == "pass"
    assert check_ingredients(fact(), {})["status"] == "skip"
    caution = fact(subtype="Caution", concerns=["ai:b"])                         # a caution may name a banned AI
    assert check_ingredients(caution, {"ai:b": ai("ai:b", "banned")})["status"] == "skip"


# 6 review kept
def test_flagged_or_inferred_facts_must_be_needs_review():
    raw_fact = raw(extraction_flags=["shared_amount"])
    rec = {"fact": fact(), "review_reasons": []}
    assert check_review_kept(rec, raw_fact)["status"] == "fail"
    rec["fact"]["status"] = "needs_review"
    assert check_review_kept(rec, raw_fact)["status"] == "pass"
    inherited = {"fact": fact([step(applies=[qty("fertilizer:dap", 2, inherited=True)])]), "review_reasons": []}
    assert check_review_kept(inherited, raw())["status"] == "fail"
