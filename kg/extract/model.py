"""Raw extraction model (step 9), separate from the final schema models in kg.schema.

The fields follow schema v1.2, but names, units and bases are kept as printed
("DAP", "kg", "per 20 cents"), never as IDs or canonical units; step 10 normalises
and links them. Numbers are parsed into value / min / max, and each keeps its
printed text. Crop and the book's regions are not asked of the model: code adds
them from the chapter and the unit.
"""

from typing import Annotated, ClassVar, Literal, Union

from pydantic import Field, PositiveInt, StringConstraints, TypeAdapter, model_validator

from kg.schema.core import Model, Text, check_bound, check_groups, check_range
from kg.schema.vocab import (CONDITION_VARIABLES, Anchor, CautionKind, ConditionOp, ControlClass,
                             DoseBasis, DurationGroup, OffsetUnit, OperationType, Subtype,
                             WeatherAdvice)

Pct = Annotated[float, Field(ge=0, le=100)]
NonNeg = Annotated[float, Field(ge=0)]
TableRef = Annotated[str, StringConstraints(pattern=r"^#/tables/\d+$")]


class RawCondition(Model):
    """A runtime check, only for a variable in the fixed registry."""
    variable: str
    op: ConditionOp
    value: float | str | list[float | str]
    value_max: float | str | None = None
    unit: str | None = None                     # as printed
    any_of_group: PositiveInt = 1
    raw: Text

    @model_validator(mode="after")
    def _known(self):
        if self.variable not in CONDITION_VARIABLES:
            raise ValueError("unknown condition variable %r" % self.variable)
        return self


class RawQuantity(Model):
    """Step -[:APPLIES]-> what is applied; the amount as printed."""
    target: Text                                # name as printed: "DAP", "Carbendazim"
    value: NonNeg | None = None
    min: NonNeg | None = None
    max: NonNeg | None = None
    min_inclusive: bool = True
    max_inclusive: bool = True
    unit: str | None = None                     # as printed: "kg", "g", "ml", "tonne"
    basis: str | None = None                    # as printed: "/ha", "per 20 cents", "/kg of seed";
                                                # null when none is printed and the section gives none
    basis_inferred: bool = False                # basis not stated for this quantity: a guess, reviewed
    basis_rule: str | None = None               # the approved default-scope rule that gave the basis
    formulation: str | None = None              # "50 WP", "talc based"
    water_raw: str | None = None                # spray volume as printed: "500 l/ha"
    raw: Text | None = None                     # the whole quantity phrase
    quantity_ref: Literal["previous"] | None = None   # the amount was stated in an earlier bullet

    @model_validator(mode="after")
    def _amount(self):
        has_amount = any(v is not None for v in (self.value, self.min, self.max))
        if self.value is not None and (self.min is not None or self.max is not None):
            raise ValueError("give either value or min/max, not both")
        check_range(self, "min", "max")
        if has_amount:
            if self.raw is None or self.unit is None:
                raise ValueError("an amount needs its raw phrase and its unit as printed")
            if self.quantity_ref is not None:
                raise ValueError("quantity_ref is only for an amount stated earlier, not given here")
        elif self.quantity_ref is None:
            raise ValueError("no amount: set quantity_ref='previous' if it was stated earlier")
        if self.basis_inferred and self.basis_rule:
            raise ValueError("a basis from an approved rule is not inferred")
        if (self.basis_inferred or self.basis_rule) and self.basis is None:
            raise ValueError("basis_inferred / basis_rule need the basis they give")
        if self.water_raw is not None and self.raw is None:
            raise ValueError("water_raw needs the raw quantity phrase")
        return self


class RawStep(Model):
    order: PositiveInt
    alt_group: PositiveInt | None = None
    alt_option: PositiveInt | None = None
    alt_priority: Literal[1, 2] | None = None   # 1 = preferred, 2 = fallback
    condition_raw: Text | None = None           # the words that make the step conditional or a fallback
    operation: OperationType | None = None      # null when no operation type fits (reported)
    method: str | None = None
    anchor: Anchor | None = None
    offset_min: float | None = None             # relative to anchor; negative = before
    offset_max: float | None = None
    offset_min_inclusive: bool = True
    offset_max_inclusive: bool = True
    offset_unit: OffsetUnit = OffsetUnit.DAYS
    stage: str | None = None                    # growth stage as printed
    month_start: int | None = Field(default=None, ge=1, le=12)
    month_end: int | None = Field(default=None, ge=1, le=12)
    timing_raw: Text | None = None
    instruction_en: Text
    applies: list[RawQuantity] = []
    conditions: list[RawCondition] = []

    @model_validator(mode="after")
    def _timing(self):
        timed = [self.offset_min, self.offset_max, self.stage, self.month_start, self.month_end]
        if any(v is not None for v in timed) and self.timing_raw is None:
            raise ValueError("step timing needs timing_raw")
        offsets = self.offset_min is not None or self.offset_max is not None
        if offsets and self.anchor in (None, Anchor.CALENDAR):
            raise ValueError("offsets need a non-calendar anchor")
        if self.offset_unit is not OffsetUnit.DAYS and not offsets:
            raise ValueError("offset_unit %s set without offsets" % self.offset_unit.value)
        check_range(self, "offset_min", "offset_max")
        if (self.anchor is Anchor.CALENDAR) != (self.month_start is not None):
            raise ValueError("a calendar anchor and month_start go together")
        if self.month_end is not None and self.month_start is None:
            raise ValueError("month_end needs month_start")
        if (self.alt_option is not None or self.alt_priority is not None) and self.alt_group is None:
            raise ValueError("alt_option and alt_priority need an alt_group")
        check_groups(self.conditions)
        return self


class RawThresholdClause(Model):
    observation: Text                           # "hoppers", "dead hearts"
    value: NonNeg
    unit: str | None = None                     # as printed: "%", "no."
    sampling_unit: str | None = None            # as printed: "/tiller", "per hill"
    stage: str | None = None                    # as printed
    raw: Text
    conditions: list[RawCondition] = []

    @model_validator(mode="after")
    def _groups(self):
        check_groups(self.conditions)
        return self


class RawExcludedRegion(Model):
    name: Text                                  # as printed: "Cauvery Delta"
    raw: Text                                   # the whole phrase: "other than Cauvery Delta"


class RawFact(Model):
    """Core of every raw fact. A subtype's numeric fields need raw[field]."""
    NUMERIC_FIELDS: ClassVar[tuple[str, ...]] = ()

    subtype: Subtype
    summary_en: Text
    quote: Text                                 # exact, contiguous source text
    table_ref: TableRef | None = None
    table_row: int | None = Field(default=None, ge=0)
    table_col: int | None = Field(default=None, ge=0)
    duration_group: DurationGroup | None = None
    # applicability as printed; crop and the book's regions come from code
    varieties: list[Text] = []
    seasons: list[Text] = []
    systems: list[Text] = []
    soils: list[Text] = []
    purposes: list[Text] = []
    stages: list[Text] = []
    regions: list[Text] = []                    # only regions the text names as this fact's scope
    excluded_regions: list[RawExcludedRegion] = []
    unmapped: list[Text] = []                   # source phrases with no slot
    raw: dict[str, Text] = {}
    steps: list[RawStep] = []
    conditions: list[RawCondition] = []

    @model_validator(mode="after")
    def _core(self):
        for name in self.NUMERIC_FIELDS:
            if getattr(self, name) is not None and name not in self.raw:
                raise ValueError("%s needs its printed text in raw[%r]" % (name, name))
        extra = set(self.raw) - set(self.NUMERIC_FIELDS)
        if extra:
            raise ValueError("raw has entries for non-numeric fields: %s" % sorted(extra))
        if (self.table_row is not None or self.table_col is not None) and self.table_ref is None:
            raise ValueError("table_row/table_col need a table_ref")
        check_groups(self.conditions)
        return self


# --- the 16 subtypes (schema v1.2 "Recommendation subtypes") -----------------------------

class VarietyRecommendation(RawFact):
    subtype: Literal["VarietyRecommendation"]
    recommends: list[Text] = Field(min_length=1)    # variety names as printed
    note: str | None = None


class SowingWindow(RawFact):
    NUMERIC_FIELDS = ("start_month", "start_day", "end_month", "end_day")
    subtype: Literal["SowingWindow"]
    start_month: int = Field(ge=1, le=12)
    start_day: int | None = Field(default=None, ge=1, le=31)
    end_month: int = Field(ge=1, le=12)
    end_day: int | None = Field(default=None, ge=1, le=31)


class SeedRate(RawFact):
    subtype: Literal["SeedRate"]
    method: str | None = None                       # the rate itself is a Step quantity


class Spacing(RawFact):
    NUMERIC_FIELDS = ("row_cm", "plant_cm", "hills_per_m2", "seedlings_per_hill")
    subtype: Literal["Spacing"]
    row_cm: NonNeg | None = None
    plant_cm: NonNeg | None = None
    hills_per_m2: NonNeg | None = None
    seedlings_per_hill: NonNeg | None = None


class SeedTreatment(RawFact):
    subtype: Literal["SeedTreatment"]


class NutrientDose(RawFact):
    subtype: Literal["NutrientDose"]
    dose_basis: DoseBasis

    @model_validator(mode="after")
    def _steps_apply(self):
        if not self.steps or any(not s.applies for s in self.steps):
            raise ValueError("a NutrientDose needs Steps, each with quantities")
        return self


class DoseFormula(RawFact):
    subtype: Literal["DoseFormula"]
    target_nutrient: Text
    coefficients_raw: Text                          # the formula as printed; step 10 parses it
    target_yield_unit: str | None = None
    soil_series: str | None = None
    valid_range: str | None = None


class IrrigationRule(RawFact):
    NUMERIC_FIELDS = ("depth_cm",)
    subtype: Literal["IrrigationRule"]
    depth_cm: NonNeg | None = None
    criterion: str | None = None                    # "hairline cracks"


class PestThreshold(RawFact):
    subtype: Literal["PestThreshold"]
    pests: list[Text] = Field(min_length=1)         # pest or disease names as printed
    clauses: list[RawThresholdClause] = Field(min_length=1)


class ControlMeasure(RawFact):
    subtype: Literal["ControlMeasure"]
    control_class: ControlClass
    targets: list[Text] = Field(min_length=1)       # pest, disease, weed or disorder names as printed

    @model_validator(mode="after")
    def _has_steps(self):
        if not self.steps:
            raise ValueError("a ControlMeasure needs at least one Step")
        return self


class WeatherRule(RawFact):
    subtype: Literal["WeatherRule"]
    operation: OperationType | None = None
    advice: WeatherAdvice


class HarvestRule(RawFact):
    NUMERIC_FIELDS = ("harvest_moisture_pct_min", "harvest_moisture_pct_max",
                      "threshing_moisture_pct_min", "threshing_moisture_pct_max")
    subtype: Literal["HarvestRule"]
    maturity_signs: list[Text] = []
    harvest_moisture_pct_min: Pct | None = None
    harvest_moisture_pct_max: Pct | None = None
    threshing_moisture_pct_min: Pct | None = None
    threshing_moisture_pct_max: Pct | None = None
    harvest_moisture_pct_min_inclusive: bool = True
    harvest_moisture_pct_max_inclusive: bool = True
    threshing_moisture_pct_min_inclusive: bool = True
    threshing_moisture_pct_max_inclusive: bool = True

    @model_validator(mode="after")
    def _ranges(self):
        check_range(self, "harvest_moisture_pct_min", "harvest_moisture_pct_max")
        check_range(self, "threshing_moisture_pct_min", "threshing_moisture_pct_max")
        return self


class DryingSpec(RawFact):
    NUMERIC_FIELDS = ("target_moisture_pct_min", "target_moisture_pct_max",
                      "storage_months_min", "storage_months_max")
    subtype: Literal["DryingSpec"]
    target_moisture_pct_min: Pct | None = None
    target_moisture_pct_max: Pct | None = None
    storage_months_min: NonNeg | None = None
    storage_months_max: NonNeg | None = None
    target_moisture_pct_min_inclusive: bool = True
    target_moisture_pct_max_inclusive: bool = True
    storage_months_min_inclusive: bool = True
    storage_months_max_inclusive: bool = True
    storage_term_raw: Text | None = None            # "short term", "long term"
    method: str | None = None

    @model_validator(mode="after")
    def _ranges(self):
        check_range(self, "target_moisture_pct_min", "target_moisture_pct_max")
        check_range(self, "storage_months_min", "storage_months_max")
        return self


class StorageRule(RawFact):
    NUMERIC_FIELDS = ("storage_months_min", "storage_months_max", "max_moisture_pct")
    subtype: Literal["StorageRule"]
    storage_months_min: NonNeg | None = None
    storage_months_max: NonNeg | None = None
    max_moisture_pct: Pct | None = None
    storage_months_min_inclusive: bool = True
    storage_months_max_inclusive: bool = True
    max_moisture_pct_inclusive: bool = True
    structure: str | None = None
    targets: list[Text] = []                        # storage pests as printed

    @model_validator(mode="after")
    def _ranges(self):
        check_range(self, "storage_months_min", "storage_months_max")
        check_bound(self, "max_moisture_pct")
        return self


class QualitySpec(RawFact):
    NUMERIC_FIELDS = ("limit_value",)
    subtype: Literal["QualitySpec"]
    authority: str | None = None
    valid_for_season: str | None = None
    parameter: Text
    limit_value: NonNeg | None = None
    unit: str | None = None


class Caution(RawFact):
    subtype: Literal["Caution"]
    kind: CautionKind
    text_en: Text
    concerns: list[Text] = []                       # active ingredients as printed


SUBTYPES = (VarietyRecommendation, SowingWindow, SeedRate, Spacing, SeedTreatment, NutrientDose,
            DoseFormula, IrrigationRule, PestThreshold, ControlMeasure, WeatherRule, HarvestRule,
            DryingSpec, StorageRule, QualitySpec, Caution)
assert {m.model_fields["subtype"].annotation.__args__[0] for m in SUBTYPES} == set(Subtype)

Fact = Annotated[Union[SUBTYPES], Field(discriminator="subtype")]
FACT = TypeAdapter(Fact)
NESTED = (RawStep, RawQuantity, RawCondition, RawThresholdClause, RawExcludedRegion)
