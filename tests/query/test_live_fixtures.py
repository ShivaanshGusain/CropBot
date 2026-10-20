"""The step 14 templates on the loaded TNAU facts, one farm-context fixture per question.

  uv run python -m pytest tests/query/test_live_fixtures.py --neo4j-test-db cropbot-test

Skipped without --neo4j-test-db; the fixture empties that database and loads concepts/ and the TNAU facts.
Each fixture (tests/query/fixtures/*.json) gives the context and the expected answer.
"""

import json
from pathlib import Path

import pytest

from kg.load import facts as lf
from kg.query import FarmContext, answer
from kg.registry import read_registry
from kg.validate import VALIDATED_DIR
from tests.conftest import reset_and_seed

FIXTURES = sorted((Path(__file__).parent / "fixtures").glob("*.json"))


def summarise(out: dict) -> dict:
    """The parts of an answer the fixtures compare."""
    facts = [f for s in out["slots"] for f in s["facts"]]
    return {"scope": out["scope"], "asks": sorted(a["variable"] for a in out["asks"]),
            "visible": sorted(f["id"] for f in facts), "hidden": sorted({h["fact"] for h in out["hidden"]}),
            "message": out["message"],
            "labels": {f["id"]: f["labels"] for f in facts},
            "clauses": {f["id"]: [c["value"] for c in f["clauses"]] for f in facts if f["clauses"]},
            "conflicts": {f["id"]: sorted(c["id"] for c in f["conflicts"]) for f in facts if f["conflicts"]}}


def check(expect: dict, got: dict) -> list[str]:
    """Differences between a fixture's expectation and the summary (hidden: listed ones must be hidden)."""
    problems = []
    for key, want in expect.items():
        have = got[key]
        if key in ("asks", "visible"):
            ok = sorted(want) == have
        elif key == "hidden":
            ok = set(want) <= set(have)
        elif key in ("labels", "clauses", "conflicts"):
            ok = all(have.get(k) == v for k, v in want.items())
        else:
            ok = want == have
        if not ok:
            problems.append("%s: expected %r, got %r" % (key, want, have))
    return problems


@pytest.fixture(scope="module")
def loaded(neo4j_test_db):
    if not (VALIDATED_DIR / "tnau_agriculture_2020" / "facts.jsonl").exists():
        pytest.skip("needs data/validated and data/verified for the TNAU guide")
    driver, name = neo4j_test_db
    concepts = reset_and_seed(driver, name)                  # the test database only
    entry = read_registry()[0]
    lf.load(driver, entry, lf.build(entry, lf.read_inputs(entry), concepts), name)
    return driver, name


@pytest.mark.parametrize("path", FIXTURES, ids=[p.stem for p in FIXTURES])
def test_fixture(loaded, path):
    driver, name = loaded
    fx = json.loads(path.read_text(encoding="utf-8"))
    out = answer(driver, fx["template"], FarmContext.model_validate(fx["context"]), name)
    assert check(fx["expect"], summarise(out)) == []
    for f in (f for s in out["slots"] for f in s["facts"]):        # every served fact carries its citation
        c = f["citation"]
        assert c["quote"] and c["pdf_page"] and c["printed_page"] and c["source_title"] and c["status"]
        assert "verifier_score" in c
