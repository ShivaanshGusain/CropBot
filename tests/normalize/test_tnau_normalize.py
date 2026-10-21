"""Normalisation of the four hand-run TNAU units. Needs the step 9 v2 runs and the units/tables
(gitignored); skipped when they are missing."""

import pytest

from kg.extract import EXTRACTED_DIR
from kg.normalize import run
from kg.registry import read_registry
from kg.schema import FACT

ENTRY = read_registry()[0]
RUNS = EXTRACTED_DIR / "tnau_agriculture_2020" / "v2"
UNITS = {"8e1d1b38b483", "b879265e483b", "e63c6fbba0e4", "f5b06c9fd3f8"}
pytestmark = pytest.mark.skipif(not all((RUNS / ("%s.json" % u)).exists() for u in UNITS),
                                reason="needs the v2 hand-runs in data/extracted")


@pytest.fixture(scope="module")
def result():
    return run(ENTRY)


def fact(result, unit, index):
    return next(x for x in result["facts"] if x["unit_id"].endswith(unit) and x["raw_index"] == index)


def test_every_fact_is_validated_or_held_with_reasons_and_none_is_approved(result):
    assert len(result["facts"]) + len(result["held"]) == 123      # 124 before the step 8 rebuild removed e63c's
                                                                  # WBPH Pymetrozine fact (the line is BPH's)
    assert all(h["reasons"] for h in result["held"])
    for x in result["facts"]:
        assert x["status"] in ("extracted", "needs_review")
        FACT.validate_python(x["fact"])


def test_inherited_nursery_dap(result):
    a = fact(result, "b879265e483b", 20)["fact"]["steps"][0]["applies"][0]
    assert (a["target_id"], a["value"], a["basis"], a["area_cents"], a["inherited"]) == (
        "fertilizer:dap", 2, "per_cent_nursery", 20, True)


def test_seed_npk_by_convention_and_section_purpose(result):
    x = fact(result, "f5b06c9fd3f8", 11)
    assert [(a["target_id"], a["value"]) for a in x["fact"]["steps"][0]["applies"]] == [
        ("nutrient:n", 150), ("nutrient:p2o5", 50), ("nutrient:k2o", 80)]
    assert x["status"] == "needs_review" and x["purpose_origins"] == {"purpose:seed": ["section"]}
    assert fact(result, "f5b06c9fd3f8", 24)["purpose_origins"] == {"purpose:seed": ["text", "section"]}


def test_generic_targets_and_operations_are_held(result):
    reasons = [r for h in result["held"] for r in h["reasons"]]
    assert any("generic target" in r for r in reasons) and any("has no operation" in r for r in reasons)
