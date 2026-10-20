"""Step 11 on the normalised TNAU facts (gitignored); skipped when they are missing."""

import pytest

from kg.normalize import NORMALIZED_DIR
from kg.registry import read_registry
from kg.validate import run

ENTRY = read_registry()[0]
pytestmark = pytest.mark.skipif(not (NORMALIZED_DIR / "tnau_agriculture_2020" / "facts.jsonl").exists(),
                                reason="needs data/normalized for the TNAU guide")


@pytest.fixture(scope="module")
def facts():
    return {(f["unit_id"].rsplit(":", 1)[1], f["raw_index"]): f for f in run(ENTRY)["facts"]}


def test_nothing_is_approved_and_failures_mean_review(facts):
    for f in facts.values():
        assert f["status"] in ("extracted", "needs_review")
        if any(c["status"] == "fail" for c in f["checks"].values()):
            assert f["status"] == "needs_review"


def test_suspected_source_typos_fail_the_dose_check(facts):
    for key in (("e63c6fbba0e4", 21), ("e63c6fbba0e4", 35)):                  # Fipronil 80%WG kg, Imidacloprid 70% WG kg
        r = facts[key]["checks"]["value_ranges"]
        assert r["status"] == "fail" and "kg a.i./ha" in r["reason"]


def test_every_applied_ingredient_fails_closed_while_unknown(facts):
    with_ai = [f for f in facts.values() if any(a["target_id"].startswith("ai:") for s in f["fact"]["steps"]
                                                 for a in s["applies"])]
    assert with_ai and all(f["checks"]["ingredients"]["status"] == "fail" for f in with_ai)


def test_nursery_alternatives_wait_for_approved_percentages(facts):
    r = facts[("b879265e483b", 19)]["checks"]["alternatives"]
    assert r["status"] == "skip" and r["applies"] and "no approved percentages" in r["reason"]
    assert any(x.startswith("alternatives:") for x in facts[("b879265e483b", 19)]["review_reasons"])
