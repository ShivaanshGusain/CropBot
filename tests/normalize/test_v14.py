"""Schema v1.4 in step 10: durations, purpose, week offsets and word ratios read by code, the bait strength and
carrier, the formulation table (and what it never overrides), repeat_offsets, the endemic_area condition and a
ControlMeasure with no specific target."""

import pytest

from kg.normalize import build, instruction
from kg.normalize.link import Linker
from kg.normalize.units import canon_duration_unit, formulation_code, period_offset, ratio_words
from kg.schema.concepts import ActiveIngredient, Disease, Fertilizer, Label, Pest
from tests.normalize.test_v13 import NODES, finish, raw

NODES14 = NODES + [
    ActiveIngredient(id="ai:carbofuran", name_en="Carbofuran", review_status="needs_review"),
    ActiveIngredient(id="ai:chlorpyrifos", name_en="Chlorpyrifos", review_status="needs_review"),
    ActiveIngredient(id="ai:beauveria_bassiana", name_en="Beauveria bassiana", review_status="needs_review"),
    ActiveIngredient(id="ai:quinalphos", name_en="Quinalphos", review_status="needs_review"),
    ActiveIngredient(id="ai:malathion", name_en="Malathion", review_status="needs_review"),
    ActiveIngredient(id="ai:bromadiolone", name_en="Bromadiolone", review_status="needs_review"),
    Disease(id="disease:tungro", name_en="Rice tungro", pathogen_type="virus", review_status="needs_review"),
    Label(concept_id="disease:tungro", text="tungro", lang="en", script="Latn", kind="canonical",
          review_status="needs_review"),
    Pest(id="pest:green_leafhopper", name_en="Green leafhopper", pest_type="insect", review_status="approved"),
    Fertilizer(id="fertilizer:kcl_x", name_en="KCl solution", review_status="needs_review", source="x"),
]
L14 = Linker(NODES14)
L_NO_TUNGRO = Linker([n for n in NODES14 if "tungro" not in str(getattr(n, "id", "")) + str(getattr(n, "concept_id", ""))])


@pytest.mark.parametrize("printed, unit", [("h", "hours"), ("hrs", "hours"), ("minutes", "minutes"), ("days", "days"),
                                           ("weeks", None), ("overnight", None)])
def test_duration_units(printed, unit):
    got = canon_duration_unit(printed)
    assert (got.value if got else None) == unit


def test_word_table_readings():
    assert period_offset("a week before harvest")[:2] == (-1, "weeks")       # one week, never seven days
    assert period_offset("7 days before harvest") is None
    assert ratio_words("in equal volume")[:2] == (1, 1) and ratio_words("in plenty of water") is None
    assert [formulation_code(x) for x in ("1.5% DP", "3% CG", "0.3% G", "17.8 SL", "talc based", "48%FS", None)] == [
        "DP", "CG", "G", "SL", None, None, None]


def option(i, target, formulation, operation="spraying", **kw):
    return {"order": 1, "alt_group": 1, "alt_option": i, "operation": operation,
            "applies": [{"target": target, "formulation": formulation, "value": 25, "unit": "kg", "basis": "/ha",
                         "raw": "%s %s 25 kg" % (target, formulation), **kw}]}


def test_granules_and_dusts_in_a_spray_list_follow_their_code():
    f = raw(subtype="ControlMeasure", control_class="chemical", targets=["BPH"],
            steps=[option(1, "Carbofuran", "3% CG"), option(2, "Quinalphos", "1.5% D"), option(3, "Malathion", "50% EC")])
    d = build(f, L14, "crop:rice", {})
    assert [s["operation"] for s in d["steps"]] == ["application", "dusting", "spraying"]
    assert "operation_from_formulation" in d["extraction_flags"] and not f.blocks


def test_other_verbs_carriers_and_mixed_lists():
    beauveria = raw(subtype="ControlMeasure", control_class="biological", targets=["BPH"],
                    steps=[option(1, "Beauveria bassiana", "1.15 WP", operation="application")])
    d = build(beauveria, L14, "crop:rice", {})
    assert d["steps"][0]["operation"] == "application" and "operation_from_formulation" not in d["extraction_flags"]
    straw = raw(subtype="ControlMeasure", control_class="chemical", targets=["BPH"],
                steps=[option(1, "chlorpyriphos", "1.5% DP", operation="application", carrier_raw="chopped paddy straw")])
    d = build(straw, L14, "crop:rice", {})
    assert d["steps"][0]["operation"] == "application" and d["steps"][0]["applies"][0]["carrier_raw"] == "chopped paddy straw"
    assert "on chopped paddy straw" in instruction(d["steps"][0], {"ai:chlorpyrifos": "chlorpyriphos"})
    mixed = raw(subtype="ControlMeasure", control_class="chemical", targets=["BPH"],
                steps=[{**option(1, "Quinalphos", "1.5% D", operation=None), "method": "Dust/ spray"},
                       {**option(2, "Malathion", "50% EC", operation=None), "method": "Dust/ spray"},
                       {**option(3, "Neem seed kernel extract", None, operation=None), "method": "Dust/ spray"}])
    d = build(mixed, L14, "crop:rice", {})
    assert [s["operation"] for s in d["steps"]] == ["dusting", "spraying", None]
    assert mixed.blocks[-1] == "step 1 has no operation; method 'Dust/ spray'"     # the option with no code


def test_durations_purpose_week_offsets_and_word_ratios():
    f = raw(subtype="SeedTreatment", steps=[
        {"order": 1, "operation": "seed_treatment", "duration_min": 12, "duration_max": 16, "duration_unit": "h",
         "duration_raw": "for 12 - 16 h", "purpose_raw": "adapting specific gravity grading",
         "applies": [{"target": "KCl", "conc_value": 1, "conc_unit": "%", "conc_raw": "1% KCl solution",
                      "ratio_raw": "in equal volume"}]},
        {"order": 2, "operation": "seed_treatment", "duration_raw": "overnight"}])
    d = build(f, L14, "crop:rice", {})
    s1, s2 = d["steps"]
    assert (s1["duration_min"], s1["duration_max"], s1["duration_unit"]) == (12, 16, "hours")
    assert s1["applies"][0]["ratio_part"] == 1 and s1["applies"][0]["ratio_whole"] == 2
    assert s2["duration_raw"] == "overnight" and "duration_min" not in s2 and not f.blocks
    assert "(adapting specific gravity grading)" in instruction(s1, {})
    finish(f, d)                                       # validates against the schema model
    harvest = raw(subtype="HarvestRule", steps=[{"order": 1, "operation": "harvest", "anchor": "harvest",
                                                 "timing_raw": "a week before harvest"}])
    s = build(harvest, L14, "crop:rice", {})["steps"][0]
    assert (s["offset_min"], s["offset_max"], s["offset_unit"]) == (-1, -1, "weeks")


def test_repeat_offsets_must_match_their_count_words():
    def step(words):
        return {"order": 1, "alt_group": 1, "alt_option": 1, "operation": "spraying", "anchor": "transplanting",
                "offset_min": 15, "offset_max": 15, "repeat_offsets": [15, 30], "repeat_raw": words,
                "timing_raw": "15 and 30 days after transplanting",
                "applies": [{"target": "Carbofuran", "formulation": "50% EC", "value": 1, "unit": "kg",
                             "basis": "/ha", "raw": "1 kg"}]}
    ok = raw(subtype="ControlMeasure", control_class="chemical", targets=["GLH"], steps=[step("twice")])
    s = build(ok, Linker(NODES14 + [Label(concept_id="pest:green_leafhopper", text="GLH", lang="en", script="Latn",
                                          kind="abbreviation", review_status="approved")]), "crop:rice", {})["steps"][0]
    assert (s["repeat_offsets"], s["repeat_count"]) == ([15, 30], 2)
    bad = raw(subtype="ControlMeasure", control_class="chemical", targets=["BPH"], steps=[step("thrice")])
    build(bad, L14, "crop:rice", {})
    assert any("do not match the 2 stated times" in b for b in bad.blocks)


def test_endemic_area_links_to_a_concept_or_holds():
    clause = {"observation": "GLH", "value": 2, "sampling_unit": "/hill", "raw": "2/hill",
              "conditions": [{"variable": "endemic_area", "op": "==", "value": "tungro", "raw": "in tungro endemic area"}]}
    f = raw(subtype="PestThreshold", pests=["BPH"], clauses=[clause])
    d = build(f, L14, "crop:rice", {})
    assert d["clauses"][0]["conditions"][0]["value"] == "disease:tungro" and not f.blocks
    unseeded = raw(subtype="PestThreshold", pests=["BPH"], clauses=[clause])
    build(unseeded, L_NO_TUNGRO, "crop:rice", {})
    assert any("endemic_area value 'tungro'" in b for b in unseeded.blocks)


def test_a_control_measure_without_a_specific_target_is_held():
    f = raw(subtype="ControlMeasure", control_class="cultural", targets=[],
            steps=[{"order": 1, "operation": "bund_management", "method": "Trim field bunds"}])
    build(f, L14, "crop:rice", {})
    assert f.blocks == ["no specific target printed (prompt v4 writes no generic target; a ControlMeasure needs one)"]
