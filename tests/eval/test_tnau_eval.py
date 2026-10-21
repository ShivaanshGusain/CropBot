"""Step 15 on the TNAU data (gitignored step 9-12 outputs); skipped when they are missing."""

import pytest

from kg.eval import ADJUDICATIONS, NORMALIZED_DIR, VERIFIED_DIR, calibration, metrics, run
from kg.registry import read_registry

pytestmark = pytest.mark.skipif(not (VERIFIED_DIR / "tnau_agriculture_2020" / "facts.jsonl").exists()
                                or not (NORMALIZED_DIR / "tnau_agriculture_2020" / "facts.jsonl").exists(),
                                reason="needs the step 10 and 12 outputs for the TNAU guide")


@pytest.fixture(scope="module")
def res():
    return run(read_registry()[0])


def test_every_scored_gold_row_is_found(res):
    missed = [o["row"]["fact_id"] for o in res["outcome"] if o["scored"] and not o["match"] and not o["not_extracted"]]
    assert missed == []               # B23 (Pymetrozine, p. 66) since the step 8 rebuild put it back in the BPH row
    b23 = next(o for o in res["outcome"] if o["row"]["fact_id"] == "B23")
    assert res["atoms"][b23["match"]["ai"]]["fact"] == "e63c#35"
    unscored = {o["row"]["fact_id"] for o in res["outcome"] if not o["scored"]}
    assert unscored == {"A1", "A22", "A23", "A25", "A26", "A27", "A28", "B38b", "B39", "B40", "B41"}


def test_bph_scope_keeps_out_the_wbph_row(res):
    in_b = {a["fact"] for a in res["atoms"] if a["section"] == "B" and a["in_scope"]}
    assert "e63c#35" in in_b and "e63c#67" in in_b                # the BPH row and the BPH resurgence list
    assert "e63c#36" not in in_b and "e63c#69" not in in_b        # WBPH row and WBPH resurgence list


def test_adjudications_count_and_nothing_else_is_decided(res):
    m = metrics(res)["sections"]
    assert m["all"]["found"] == 90
    # 2026-10-21: all 127 disagreements adjudicated; 10 biofertilizer rows unclear, 6 judged for the gold set
    assert (m["all"]["recall_agree"]["lower"]["k"], m["all"]["recall_agree"]["upper"]["k"]) == (74, 84)
    assert m["all"]["precision_found"]["k"] == 109 and m["all"]["precision_found"]["n"] == 110
    assert (m["all"]["precision_agree_lower"]["k"], m["all"]["precision_agree_upper"]["k"]) == (92, 102)
    if ADJUDICATIONS.exists():                   # 2026-10-21: the BPH resurgence list is in the book (p. 69)
        assert m["B"]["extras_confirmed"] == 16
        verdicts = sorted(e["verdict"] for e in res["judged_extras"].values())
        assert verdicts == ["extraction"] * 16 + ["gold"]       # + 8e1d#1/m2, a paraphrased maturity sign (E8)
    calib = calibration(res)
    assert calib["proposal"]["threshold"] is None and calib["proposal"]["message"] == "no threshold yet"
