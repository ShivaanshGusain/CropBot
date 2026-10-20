"""Concept nodes seeded from concepts/ (schema "Concept nodes" and "Regions, seasons and scope").

Only the concepts the first seed needs are modelled. Every concept has
`name_en` (schema Conventions: "name_en on every concept"), a review_status,
and an optional `source` saying where a hand-entered value came from.
References to other concepts become edges (EDGES); the loader checks that
their targets exist.
"""

from typing import ClassVar, Literal

from pydantic import Field, model_validator

from .core import Model, SourceSpan, Text, check_range
from .ids import (CountryId, CropId, DistrictId, FertilizerId, LabelId, LocalSeasonId, NutrientId,
                  OperationId, PurposeId, SeasonId, SoilId, StateId, SystemId, VarietyId, ZoneId,
                  label_id)
from .vocab import (CropGroup, DurationGroup, LabelKind, OperationType as OperationVocab,
                    Purpose as PurposeVocab, ReviewStatus, Season as SeasonVocab, VarietyKind,
                    ZoneScheme)


class Concept(Model):
    LABEL: ClassVar[str]
    # field -> (relationship type, target node label); the field becomes an edge, not a property
    EDGES: ClassVar[dict[str, tuple[str, str]]] = {}
    # field -> target node label; the field stays a property but must point at an existing node
    REFS: ClassVar[dict[str, str]] = {}
    # closed vocabulary the id slug must belong to, if any
    VOCAB: ClassVar[type | None] = None

    id: str
    name_en: Text
    review_status: ReviewStatus
    source: str | None = None

    @model_validator(mode="after")
    def _slug_in_vocab(self):
        if self.VOCAB is not None:
            slug = self.id.split(":", 1)[1]
            if slug not in {m.value for m in self.VOCAB}:
                raise ValueError("%s is not in the schema's %s list" % (self.id, self.LABEL))
        return self

    def references(self) -> list[tuple[str, str, str]]:
        """(field, target id, target label) for every edge or reference field that is set."""
        targets = {f: label for f, (_, label) in self.EDGES.items()} | self.REFS
        return [(f, getattr(self, f), label) for f, label in targets.items()
                if getattr(self, f) is not None]

    def props(self) -> dict:
        return self.model_dump(mode="json", exclude={"id", *self.EDGES})


# --- regions ---------------------------------------------------------------------

class Country(Concept):
    LABEL = "Country"
    id: CountryId
    level: Literal[1] = 1


class State(Concept):
    LABEL = "State"
    EDGES = {"country_id": ("IN_COUNTRY", "Country")}
    id: StateId
    level: Literal[2] = 2
    country_id: CountryId


class AgroClimaticZone(Concept):
    LABEL = "AgroClimaticZone"
    REFS = {"state_id": "State"}
    id: ZoneId
    level: Literal[3] = 3
    scheme: ZoneScheme
    state_id: StateId | None = None     # a property, not an edge (schema)

    @model_validator(mode="after")
    def _state_scheme(self):
        if self.scheme is ZoneScheme.STATE_BOOK and self.state_id is None:
            raise ValueError("a state_book zone needs state_id")
        return self


class District(Concept):
    LABEL = "District"
    EDGES = {"state_id": ("IN_STATE", "State"), "zone_id": ("IN_ZONE", "AgroClimaticZone")}
    id: DistrictId
    level: Literal[4] = 4
    state_id: StateId
    zone_id: ZoneId | None = None       # IN_ZONE {scheme} edge; scheme is copied from the zone


# --- seasons, systems, soils, purposes, operations ----------------------------------

class Season(Concept):
    LABEL = "Season"
    VOCAB = SeasonVocab
    id: SeasonId


class LocalSeason(Concept):
    LABEL = "LocalSeason"
    EDGES = {"maps_to": ("MAPS_TO", "Season")}
    REFS = {"state_id": "State"}
    id: LocalSeasonId
    state_id: StateId                   # required: a Samba window never reaches another state
    start_month: int | None = Field(default=None, ge=1, le=12)
    end_month: int | None = Field(default=None, ge=1, le=12)
    maps_to: SeasonId | None = None


class Purpose(Concept):
    LABEL = "Purpose"
    VOCAB = PurposeVocab
    id: PurposeId


class ProductionSystem(Concept):
    LABEL = "ProductionSystem"
    id: SystemId


class SoilType(Concept):
    LABEL = "SoilType"
    id: SoilId


class OperationType(Concept):
    LABEL = "OperationType"
    VOCAB = OperationVocab
    id: OperationId


# --- inputs and crops ------------------------------------------------------------------

class Nutrient(Concept):
    LABEL = "Nutrient"
    id: NutrientId
    symbol: Text                        # as the schema writes it: N, P2O5, K2O, ...


class Fertilizer(Concept):
    LABEL = "Fertilizer"
    id: FertilizerId
    n_pct: float = Field(ge=0, le=100)
    p2o5_pct: float = Field(ge=0, le=100)
    k2o_pct: float = Field(ge=0, le=100)
    source: Text                        # required: where the percentages come from


class Crop(Concept):
    LABEL = "Crop"
    id: CropId
    scientific_name: str | None = None
    crop_group: CropGroup


class Variety(Concept):
    """A variety pivoted from a book's variety table (step 8).

    The one sanctioned exception to "never create concepts automatically": the
    pivot (kg/tables) always produces needs_review records, a reviewer may later
    approve them, and facts linked to an unapproved Variety are needs_review too.
    Every number keeps its raw text (schema v1.2), and every value keeps the
    table cell it came from.
    """
    LABEL = "Variety"
    EDGES = {"crop_id": ("VARIETY_OF", "Crop")}
    NUMERIC_FIELDS: ClassVar[tuple[str, ...]] = ("release_year", "duration_days_min",
                                                 "duration_days_max", "avg_yield_kg_ha")
    id: VarietyId
    name: Text                          # as written in the table header
    crop_id: CropId | None = None       # set only when the chapter is approved
    kind: VarietyKind | None = None     # "hybrid" only when the name says so
    release_year: int | None = None
    parentage: str | None = None
    duration_days_min: float | None = Field(default=None, ge=0)
    duration_days_max: float | None = Field(default=None, ge=0)
    duration_group: DurationGroup | None = None
    avg_yield_kg_ha: float | None = Field(default=None, ge=0)
    grain_type: str | None = None
    traits: list[str] = []
    raw: dict[str, Text] = {}           # schema v1.2
    cells: dict[str, dict] = {}         # field or trait label -> table cell provenance
    evidence: list[SourceSpan] = Field(min_length=1)

    @model_validator(mode="after")
    def _variety_rules(self):
        for name in self.NUMERIC_FIELDS:
            if getattr(self, name) is not None and name not in self.raw:
                raise ValueError("%s needs its raw source text in raw[%r]" % (name, name))
        check_range(self, "duration_days_min", "duration_days_max")
        return self


# --- labels ----------------------------------------------------------------------------

class Label(Model):
    """A word farmers or books use for a concept. Scientific names are Crop properties, not labels."""
    LABEL: ClassVar[str] = "Label"
    EDGES: ClassVar[dict[str, tuple[str, str]]] = {"concept_id": ("LABEL_OF", "Concept")}

    id: LabelId | None = None           # computed from concept_id, kind, lang and text
    concept_id: str
    text: Text
    lang: Text
    script: Text
    kind: LabelKind
    review_status: ReviewStatus
    source: str | None = None

    @model_validator(mode="after")
    def _id(self):
        expected = label_id(self.concept_id, self.kind.value, self.lang, self.text)
        if self.id is not None and self.id != expected:
            raise ValueError("label id %s does not match its fields (expected %s)"
                             % (self.id, expected))
        self.id = expected
        return self

    def references(self) -> list[tuple[str, str, str]]:
        return [("concept_id", self.concept_id, "Concept")]

    def props(self) -> dict:
        return self.model_dump(mode="json", exclude={"id", "concept_id"})


SEED_FILES: dict[str, type] = {
    "countries.csv": Country,
    "states.csv": State,
    "zones.csv": AgroClimaticZone,
    "districts.csv": District,
    "seasons.csv": Season,
    "local_seasons.csv": LocalSeason,
    "purposes.csv": Purpose,
    "production_systems.csv": ProductionSystem,
    "soil_types.csv": SoilType,
    "operation_types.csv": OperationType,
    "nutrients.csv": Nutrient,
    "fertilizers.csv": Fertilizer,
    "crops.csv": Crop,
    "labels.csv": Label,
}

# seed files that must hold exactly the schema's closed list
CLOSED_LISTS = {Season: SeasonVocab, Purpose: PurposeVocab, OperationType: OperationVocab}
