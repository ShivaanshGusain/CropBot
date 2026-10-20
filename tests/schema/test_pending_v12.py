"""Pending schema v1.2 additions: strict bounds, hour offsets, edition labels."""

import copy

import pytest
from pydantic import ValidationError

from kg.schema import FACT, Applies, Source, Step

from .examples import DRYING_SEED_SHORT, STORAGE_LONG, TNAU_SOURCE

# --- strict bounds ---------------------------------------------------------------------


def test_less_than_and_more_than_are_stored_exactly():
    rule = FACT.validate_python(STORAGE_LONG)   # "more than 15 months ... less than 8 %"
    assert (rule.storage_months_min, rule.storage_months_min_inclusive) == (15, False)
    assert (rule.max_moisture_pct, rule.max_moisture_pct_inclusive) == (8, False)


def test_bounds_are_inclusive_by_default():
    drying = FACT.validate_python(DRYING_SEED_SHORT)
    assert drying.target_moisture_pct_min_inclusive and drying.target_moisture_pct_max_inclusive


def test_exclusive_flag_without_a_bound_is_rejected():
    data = copy.deepcopy(STORAGE_LONG)
    data["storage_months_max_inclusive"] = False   # there is no storage_months_max
    with pytest.raises(ValidationError, match="storage_months_max is empty"):
        FACT.validate_python(data)


def test_equal_bounds_that_exclude_an_end_are_rejected():
    data = copy.deepcopy(DRYING_SEED_SHORT)
    data.update(target_moisture_pct_min=12, target_moisture_pct_max=12,
                target_moisture_pct_max_inclusive=False)
    with pytest.raises(ValidationError, match="empty range"):
        FACT.validate_python(data)


def test_applies_range_can_be_strict():
    a = Applies(target_id="ai:carbendazim", min=1, max=2, max_inclusive=False,
                unit="g", basis="per_kg_seed", raw="1 to under 2 g/kg")
    assert a.max_inclusive is False


# --- hour offsets ---------------------------------------------------------------------------

DRAIN = {"order": 1, "operation": "irrigation", "anchor": "sowing",
         "offset_min": 18, "offset_max": 24, "offset_unit": "hours",
         "timing_raw": "18 to 24 hrs after sowing",
         "instruction_en": "Drain the water 18 to 24 hours after sowing"}


def test_hour_offsets():
    step = Step.model_validate(DRAIN)   # wet nursery, p. 30
    assert (step.offset_min, step.offset_max, step.offset_unit.value) == (18, 24, "hours")


def test_offsets_default_to_days():
    step = Step.model_validate({k: v for k, v in DRAIN.items() if k != "offset_unit"})
    assert step.offset_unit.value == "days"


def test_unknown_offset_unit_is_rejected():
    with pytest.raises(ValidationError, match="Input should be 'days' or 'hours'"):
        Step.model_validate({**DRAIN, "offset_unit": "weeks"})


def test_hours_without_offsets_are_rejected():
    data = {k: v for k, v in DRAIN.items() if k not in ("offset_min", "offset_max")}
    with pytest.raises(ValidationError, match="offset_unit hours set without offsets"):
        Step.model_validate(data)


# --- edition year and label --------------------------------------------------------------


def test_edition_label_keeps_the_written_form():
    src = Source.model_validate({**TNAU_SOURCE, "edition_year": 2021, "edition_label": "2021-22"})
    assert (src.edition_year, src.edition_label) == (2021, "2021-22")


@pytest.mark.parametrize("year", [2022, None])
def test_edition_year_must_be_the_label_start_year(year):
    with pytest.raises(ValidationError, match="start year"):
        Source.model_validate({**TNAU_SOURCE, "edition_year": year, "edition_label": "2021-22"})
