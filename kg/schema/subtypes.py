"""First-slice Recommendation subtypes (schema v1.2, "Deferred and open decisions").

Each subtype adds only its own fields to the core. Numeric subtype fields are
listed in NUMERIC_FIELDS so the core can require their raw text. Every bound
has a `<field>_inclusive` flag (schema v1.2, default true): false
stores "less than 8 %" or "more than 15 months" exactly.
"""

import re
from typing import Annotated, Literal, Union

from pydantic import Field, TypeAdapter, model_validator

from .core import Recommendation, Text, ThresholdClause, check_bound, check_range
from .ids import ActiveIngredientId, ControlTargetId, PestOrDiseaseId, StorageTargetId, VarietyId
from .vocab import CautionKind, ControlClass, DoseBasis

Pct = Annotated[float, Field(ge=0, le=100)]
Months = Annotated[float, Field(ge=0)]


class VarietyRecommendation(Recommendation):
    subtype: Literal["VarietyRecommendation"]
    recommends: list[VarietyId] = Field(min_length=1)       # RECOMMENDS
    note: str | None = None


class SowingWindow(Recommendation):
    NUMERIC_FIELDS = ("start_month", "start_day", "end_month", "end_day")
    subtype: Literal["SowingWindow"]
    start_month: int = Field(ge=1, le=12)
    start_day: int | None = Field(default=None, ge=1, le=31)
    end_month: int = Field(ge=1, le=12)                     # may be before start_month (Dec-Jan)
    end_day: int | None = Field(default=None, ge=1, le=31)


class NutrientDose(Recommendation):
    subtype: Literal["NutrientDose"]
    dose_basis: DoseBasis

    @model_validator(mode="after")
    def _steps_apply(self):
        if not self.steps or any(not s.applies for s in self.steps):
            raise ValueError("a NutrientDose needs Steps, each with APPLIES quantities")
        return self


class PestThreshold(Recommendation):
    subtype: Literal["PestThreshold"]
    pest_ids: list[PestOrDiseaseId] = Field(min_length=1)   # FOR_PEST
    clauses: list[ThresholdClause] = Field(min_length=1)    # HAS_CLAUSE


class ControlMeasure(Recommendation):
    subtype: Literal["ControlMeasure"]
    control_class: ControlClass
    target_ids: list[ControlTargetId] = Field(min_length=1)  # TARGETS

    @model_validator(mode="after")
    def _has_steps(self):
        if not self.steps:
            raise ValueError("a ControlMeasure needs at least one Step")
        return self


class HarvestRule(Recommendation):
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


class DryingSpec(Recommendation):
    NUMERIC_FIELDS = ("target_moisture_pct_min", "target_moisture_pct_max",
                      "storage_months_min", "storage_months_max")
    subtype: Literal["DryingSpec"]
    target_moisture_pct_min: Pct | None = None
    target_moisture_pct_max: Pct | None = None
    storage_months_min: Months | None = None
    storage_months_max: Months | None = None
    target_moisture_pct_min_inclusive: bool = True
    target_moisture_pct_max_inclusive: bool = True
    storage_months_min_inclusive: bool = True
    storage_months_max_inclusive: bool = True
    storage_term_raw: Text | None = None
    method: str | None = None

    @model_validator(mode="after")
    def _storage_term(self):
        check_range(self, "target_moisture_pct_min", "target_moisture_pct_max")
        check_range(self, "storage_months_min", "storage_months_max")
        months = self.storage_months_min is not None or self.storage_months_max is not None
        if months and self.storage_term_raw and not re.search(r"\d", self.storage_term_raw):
            raise ValueError("storage given only as %r: storage_months must stay null"
                             % self.storage_term_raw)
        return self


class StorageRule(Recommendation):
    NUMERIC_FIELDS = ("storage_months_min", "storage_months_max", "max_moisture_pct")
    subtype: Literal["StorageRule"]
    storage_months_min: Months | None = None
    storage_months_max: Months | None = None
    max_moisture_pct: Pct | None = None
    storage_months_min_inclusive: bool = True
    storage_months_max_inclusive: bool = True
    max_moisture_pct_inclusive: bool = True
    structure: str | None = None
    target_ids: list[StorageTargetId] = []   # TARGETS storage pests (context checked against concepts)

    @model_validator(mode="after")
    def _ranges(self):
        check_range(self, "storage_months_min", "storage_months_max")
        check_bound(self, "max_moisture_pct")
        return self


class Caution(Recommendation):
    subtype: Literal["Caution"]
    kind: CautionKind
    text_en: Text
    concerns: list[ActiveIngredientId] = []  # CONCERNS; optional (a safety caution may name no chemical)


FIRST_SLICE = (VarietyRecommendation, SowingWindow, NutrientDose, PestThreshold,
               ControlMeasure, HarvestRule, DryingSpec, StorageRule, Caution)

Fact = Annotated[Union[FIRST_SLICE], Field(discriminator="subtype")]
FACT = TypeAdapter(Fact)   # FACT.validate_python(data) picks the model from data["subtype"]
