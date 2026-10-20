"""Registry validation runs offline: it needs the committed PDF and concepts/, not Neo4j."""

import json
import re
import shutil
from pathlib import Path

import pytest

from kg.registry import REGISTRY_DIR, RegistryError, heading_matches, read_registry

ROOT = Path(__file__).resolve().parents[2]
TNAU = "tnau_agriculture_2020.toml"
INDEX = ROOT / "converted" / "tnau_agriculture.index.json"


@pytest.fixture
def reg(tmp_path):
    """A copy of registry/ that a test can break."""
    shutil.copytree(REGISTRY_DIR, tmp_path / "registry")
    return tmp_path / "registry"


def edit(directory, old, new, name=TNAU):
    path = directory / name
    text = path.read_text(encoding="utf-8")
    assert re.search(old, text, re.M), old
    path.write_text(re.sub(old, new, text, count=1, flags=re.M), encoding="utf-8")


def problems(directory):
    with pytest.raises(RegistryError) as e:
        read_registry(directory)
    return "\n".join(e.value.problems)


def test_committed_registry_validates():
    [entry] = read_registry()
    assert entry.id == "source:tnau_agriculture_2020"
    assert (entry.state_id, entry.region_scope, entry.authority_tier) == ("state:33", ["state:33"], 1)
    assert (entry.edition_year, entry.edition_label) == (2020, "2020")


def test_sha256_mismatch_fails(reg):
    edit(reg, r'^sha256 = "a', 'sha256 = "b')
    assert "sha256 mismatch for data/raw/AGRICULTURE.pdf" in problems(reg)


def test_missing_file_fails(reg):
    edit(reg, r'^file = ".*"', 'file = "data/raw/not_there.pdf"')
    assert "file data/raw/not_there.pdf is missing; download it from https://" in problems(reg)


def test_missing_required_field_fails(reg):
    edit(reg, r"^authority_tier = 1\n", "")
    assert "authority_tier: Field required" in problems(reg)


def test_unknown_region_fails(reg):
    edit(reg, r'regions = \["zone:tn_western"\]', 'regions = ["zone:tn_nowhere"]')
    assert "zone:tn_nowhere is not a loaded region" in problems(reg)


def test_region_outside_the_state_fails(reg):
    edit(reg, r'^region_scope = \["state:33"\]', 'region_scope = ["state:33", "country:in"]')
    assert "country:in is outside the book's state state:33" in problems(reg)


def test_malformed_region_id_fails(reg):
    edit(reg, r'^region_scope = \["state:33"\]', 'region_scope = ["state:tn"]')
    assert "is not a region id" in problems(reg)


def test_unregistered_supersedes_fails(reg):
    edit(reg, r"^doc_type = ", 'supersedes = "source:tnau_agriculture_2016"\ndoc_type = ')
    assert "supersedes source:tnau_agriculture_2016, which is not registered" in problems(reg)


def test_file_name_must_match_id(reg):
    (reg / TNAU).rename(reg / "tnau.toml")
    assert "file name must match the id (tnau_agriculture_2020.toml)" in problems(reg)


def test_edition_year_must_match_label(reg):
    edit(reg, r'^edition_label = "2020"', 'edition_label = "2021-22"')
    assert "start year" in problems(reg)


def test_page_range_must_be_ordered(reg):
    edit(reg, r"pdf_pages = \[63, 69\]", "pdf_pages = [69, 63]")
    assert "is after end" in problems(reg)


def test_only_approved_default_scope_rules_reach_the_source(reg):
    edit(reg, r'^status = "approved"\nsection = \{ heading = "A\) Pest',
         'status = "proposed"\nsection = { heading = "A) Pest')
    [entry] = read_registry(reg)
    assert entry.to_source().default_scope == [
        "dose basis = per_ha unless stated [ii) Main field, PDF pp. 63-69]"]


def test_proposed_section_scopes_are_kept_but_not_used():
    [entry] = read_registry()
    assert len(entry.section_scope) == 11 and entry.approved_section_scopes() == []


@pytest.mark.skipif(not INDEX.exists(), reason="committed TNAU conversion not present")
def test_every_section_matches_exactly_one_heading():
    [entry] = read_registry()
    items = json.loads(INDEX.read_text(encoding="utf-8"))["items"]
    sections = [r.section for r in entry.default_scope if r.section] + entry.section_scope
    counts = {s.heading: heading_matches(s, items) for s in sections}
    assert all(n == 1 for n in counts.values()), counts


# --- printed pages -------------------------------------------------------------------------

@pytest.mark.parametrize("pdf_page, printed", [
    (12, None), (13, "1"), (64, "52"), (146, "134"), (147, "136"), (380, "369"),
    (381, "385"), (459, "463"), (460, None)])
def test_printed_page_mapping(pdf_page, printed):
    [entry] = read_registry()
    assert entry.printed_page(pdf_page) == printed


def test_overlapping_printed_page_runs_fail(reg):
    edit(reg, r"pdf_pages = \[147, 380\]", "pdf_pages = [140, 380]")
    assert "printed_pages runs overlap at PDF page 140" in problems(reg)


def test_gaps_are_recorded_as_notes():
    [entry] = read_registry()
    assert any("135" in n for n in entry.notes) and any("370-384" in n for n in entry.notes)
