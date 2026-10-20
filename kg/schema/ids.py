"""ID formats: `<type>:<slug>`, lowercase (schema Conventions).

The schema names some prefixes (crop, variety, pest, ai, state, district,
country, zone, season_local, purpose); the others below are this module's
choice, kept in one place so they can change with the schema.
"""

import re
from typing import Annotated

from pydantic import AfterValidator

SLUG = r"[a-z0-9][a-z0-9_]*"

PREFIX = {
    "recommendation": "rec",
    "source": "source",
    "span": "span",
    "crop": "crop",
    "variety": "variety",
    "stage": "stage",
    "pest": "pest",
    "disease": "disease",
    "weed": "weed",
    "disorder": "disorder",
    "ai": "ai",
    "fertilizer": "fertilizer",
    "organic_input": "organic_input",
    "nutrient": "nutrient",
    "season": "season",
    "local_season": "season_local",
    "system": "system",
    "soil": "soil",
    "purpose": "purpose",
}

# State and district IDs are official LGD codes; zones are a state-scheme prefix + slug.
REGION_RE = re.compile(r"^(country:in|state:\d+|district:\d+|zone:%s)$" % SLUG)


def _matcher(*kinds: str):
    prefixes = "|".join(PREFIX[k] for k in kinds)
    rx = re.compile(r"^(%s):%s$" % (prefixes, SLUG))

    def check(value: str) -> str:
        if not rx.match(value):
            raise ValueError("%r is not a %s id" % (value, " or ".join(kinds)))
        return value
    return check


def _region(value: str) -> str:
    if not REGION_RE.match(value):
        raise ValueError("%r is not a region id (country:in, state:<lgd>, "
                         "district:<lgd>, zone:<slug>)" % value)
    return value


RecId = Annotated[str, AfterValidator(_matcher("recommendation"))]
SourceId = Annotated[str, AfterValidator(_matcher("source"))]
SpanId = Annotated[str, AfterValidator(_matcher("span"))]
CropId = Annotated[str, AfterValidator(_matcher("crop"))]
VarietyId = Annotated[str, AfterValidator(_matcher("variety"))]
StageId = Annotated[str, AfterValidator(_matcher("stage"))]
SeasonRef = Annotated[str, AfterValidator(_matcher("season", "local_season"))]
SystemId = Annotated[str, AfterValidator(_matcher("system"))]
SoilId = Annotated[str, AfterValidator(_matcher("soil"))]
PurposeId = Annotated[str, AfterValidator(_matcher("purpose"))]
ActiveIngredientId = Annotated[str, AfterValidator(_matcher("ai"))]
PestOrDiseaseId = Annotated[str, AfterValidator(_matcher("pest", "disease"))]
ControlTargetId = Annotated[str, AfterValidator(_matcher("pest", "disease", "weed", "disorder"))]
StorageTargetId = Annotated[str, AfterValidator(_matcher("pest"))]
AppliesTargetId = Annotated[str, AfterValidator(
    _matcher("nutrient", "fertilizer", "organic_input", "ai"))]
def _state(value: str) -> str:
    if not re.match(r"^state:\d+$", value):
        raise ValueError("%r is not a state id (state:<lgd>)" % value)
    return value


RegionId = Annotated[str, AfterValidator(_region)]
StateId = Annotated[str, AfterValidator(_state)]
