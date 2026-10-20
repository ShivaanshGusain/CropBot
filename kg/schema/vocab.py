"""Fixed vocabularies from docs/schema_v1.1.md.

Every closed list in the schema lives here. Lists the schema leaves open
(production systems, soil types, nutrients: they end in "...") are concepts,
not vocabularies, and are seeded from concepts/.
"""

from enum import IntEnum, StrEnum
from typing import NamedTuple


# --- numbers -----------------------------------------------------------------

class Unit(StrEnum):
    """Canonical units (Conventions table)."""
    KG = "kg"
    G = "g"
    T = "t"
    L = "l"
    ML = "ml"
    CM = "cm"
    M = "m"
    DAYS = "days"
    MONTHS = "months"
    PCT = "pct"
    COUNT = "count"


class ConditionOnlyUnit(StrEnum):
    """Pending schema v1.2: units used only by condition variables."""
    MM = "mm"
    DEGC = "degC"


class Basis(StrEnum):
    """What a quantity is per (Conventions table). Also used for ThresholdClause.sampling_unit."""
    PER_HA = "per_ha"
    PER_KG_SEED = "per_kg_seed"
    PER_L_WATER = "per_l_water"
    PER_M2 = "per_m2"
    PER_HILL = "per_hill"
    PER_TILLER = "per_tiller"
    PER_CENT_NURSERY = "per_cent_nursery"   # value is for `area_cents` of nursery, as stated
    PER_PLANT = "per_plant"
    ABSOLUTE = "absolute"


# --- recommendation core -------------------------------------------------------

class Status(StrEnum):
    EXTRACTED = "extracted"
    AUTO_VERIFIED = "auto_verified"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class Subtype(StrEnum):
    """All 16 subtypes; only the first slice has models in subtypes.py."""
    VARIETY_RECOMMENDATION = "VarietyRecommendation"
    SOWING_WINDOW = "SowingWindow"
    SEED_RATE = "SeedRate"
    SPACING = "Spacing"
    SEED_TREATMENT = "SeedTreatment"
    NUTRIENT_DOSE = "NutrientDose"
    DOSE_FORMULA = "DoseFormula"
    IRRIGATION_RULE = "IrrigationRule"
    PEST_THRESHOLD = "PestThreshold"
    CONTROL_MEASURE = "ControlMeasure"
    WEATHER_RULE = "WeatherRule"
    HARVEST_RULE = "HarvestRule"
    DRYING_SPEC = "DryingSpec"
    STORAGE_RULE = "StorageRule"
    QUALITY_SPEC = "QualitySpec"
    CAUTION = "Caution"


class DurationGroup(StrEnum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


class RegionOrigin(StrEnum):
    """Where an IN_REGION edge's scope came from."""
    TEXT = "text"
    SECTION = "section"
    SOURCE = "source"


class Anchor(StrEnum):
    """Step timing anchors."""
    SOWING = "sowing"
    TRANSPLANTING = "transplanting"
    PI = "PI"
    FLOWERING = "flowering"
    HARVEST = "harvest"
    LAST_PUDDLING = "last_puddling"
    PULLING_OUT = "pulling_out"
    CALENDAR = "calendar"
    STORAGE_START = "storage_start"


class OperationType(StrEnum):
    SOWING = "sowing"
    TRANSPLANTING = "transplanting"
    IRRIGATION = "irrigation"
    FERTILIZER_APPLICATION = "fertilizer_application"
    SPRAYING = "spraying"
    SEED_TREATMENT = "seed_treatment"
    WEEDING = "weeding"
    HARVEST = "harvest"
    THRESHING = "threshing"
    DRYING = "drying"
    STORAGE = "storage"


class ConditionOp(StrEnum):
    LT = "<"
    LE = "<="
    GT = ">"
    GE = ">="
    EQ = "=="
    NE = "!="
    IN = "in"
    BETWEEN = "between"


# --- subtype fields ------------------------------------------------------------

class DoseBasis(StrEnum):
    BLANKET = "blanket"
    SOIL_TEST = "soil_test"
    LCC = "lcc"


class ControlClass(StrEnum):
    CULTURAL = "cultural"
    MECHANICAL = "mechanical"
    BIOLOGICAL = "biological"
    CHEMICAL = "chemical"
    PHYSICAL = "physical"


class WeatherAdvice(StrEnum):
    AVOID = "avoid"
    DELAY = "delay"
    DO = "do"
    PROTECT = "protect"


class CautionKind(StrEnum):
    PROHIBITION = "prohibition"
    SAFETY = "safety"
    INCOMPATIBILITY = "incompatibility"
    BANNED = "banned"
    WAITING_PERIOD = "waiting_period"


# --- provenance ----------------------------------------------------------------

class ExtractionMethod(StrEnum):
    NATIVE_TEXT = "native_text"
    OCR = "ocr"
    TABLE_PARSE = "table_parse"


class AuthorityTier(IntEnum):
    """1 = state agricultural university package of practices; 2 = ICAR national guidance; 3 = other."""
    STATE_POP = 1
    ICAR = 2
    OTHER = 3


# --- concepts (closed lists only; used by concepts/ seeds) ------------------------

class Season(StrEnum):
    KHARIF = "kharif"
    RABI = "rabi"
    ZAID = "zaid"
    SUMMER = "summer"
    PERENNIAL = "perennial"


class Purpose(StrEnum):
    GRAIN = "grain"
    SEED = "seed"
    FODDER = "fodder"
    GREEN_MANURE = "green_manure"


class CropGroup(StrEnum):
    CEREAL = "cereal"
    MILLET = "millet"
    PULSE = "pulse"
    OILSEED = "oilseed"
    FIBRE = "fibre"
    SUGAR = "sugar"
    FORAGE = "forage"
    VEGETABLE = "vegetable"
    FRUIT = "fruit"


class VarietyKind(StrEnum):
    VARIETY = "variety"
    HYBRID = "hybrid"


class PestType(StrEnum):
    INSECT = "insect"
    MITE = "mite"
    NEMATODE = "nematode"
    RODENT = "rodent"
    BIRD = "bird"
    MOLLUSC = "mollusc"


class PestContext(StrEnum):
    FIELD = "field"
    STORAGE = "storage"
    BOTH = "both"


class PathogenType(StrEnum):
    FUNGUS = "fungus"
    BACTERIUM = "bacterium"
    VIRUS = "virus"
    PHYTOPLASMA = "phytoplasma"
    NEMATODE = "nematode"


class WeedType(StrEnum):
    GRASS = "grass"
    SEDGE = "sedge"
    BROADLEAF = "broadleaf"


class DisorderKind(StrEnum):
    DEFICIENCY = "deficiency"
    TOXICITY = "toxicity"
    PHYSIOLOGICAL = "physiological"


class UseClass(StrEnum):
    INSECTICIDE = "insecticide"
    FUNGICIDE = "fungicide"
    HERBICIDE = "herbicide"
    NEMATICIDE = "nematicide"
    RODENTICIDE = "rodenticide"
    PGR = "PGR"


class RegStatus(StrEnum):
    REGISTERED = "registered"
    RESTRICTED = "restricted"
    BANNED = "banned"
    UNKNOWN = "unknown"


class OrganicInputKind(StrEnum):
    FYM = "fym"
    COMPOST = "compost"
    GREEN_MANURE = "green_manure"
    BIOFERTILIZER = "biofertilizer"
    PRESS_MUD = "press_mud"
    OTHER = "other"


class ZoneScheme(StrEnum):
    STATE_BOOK = "state_book"
    ICAR_ACZ = "icar_acz"


class RegionLevel(IntEnum):
    COUNTRY = 1
    STATE = 2
    ZONE = 3
    DISTRICT = 4


class LabelKind(StrEnum):
    CANONICAL = "canonical"
    ALIAS = "alias"
    VERNACULAR = "vernacular"
    TRANSLITERATION = "transliteration"
    ABBREVIATION = "abbreviation"


# --- condition variables ---------------------------------------------------------

class OnUnknown(StrEnum):
    """What happens when a condition variable is missing from the farm context."""
    ASK_THEN_BRANCH = "ask_then_branch"   # ask; if the farmer does not know, branch
    CONSERVATIVE = "conservative"         # Cautions and "avoid" WeatherRules fire
    ASK = "ask"


class ValueType(StrEnum):
    NUMBER = "number"
    RATING = "rating"     # Rating values
    DATE = "date"         # ISO date
    VARIETY = "variety"   # a variety: id
    PURPOSE = "purpose"   # a Purpose value


class Rating(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ConditionVariable(NamedTuple):
    value_type: ValueType
    unit: Unit | ConditionOnlyUnit | None
    on_unknown: OnUnknown


_N, _R = ValueType.NUMBER, ValueType.RATING
_ATB, _CONS, _ASK = OnUnknown.ASK_THEN_BRANCH, OnUnknown.CONSERVATIVE, OnUnknown.ASK

# Every condition variable named in schema v1.1: the examples under "Conditions",
# the farm-context example, and the on_unknown table in "Missing data".
CONDITION_VARIABLES: dict[str, ConditionVariable] = {
    "forecast_rain_mm_24h": ConditionVariable(_N, ConditionOnlyUnit.MM, _CONS),
    "forecast_rain_days_3d": ConditionVariable(_N, Unit.DAYS, _CONS),
    "tmax_c": ConditionVariable(_N, ConditionOnlyUnit.DEGC, _CONS),
    "sowing_date": ConditionVariable(ValueType.DATE, None, _ATB),
    "das": ConditionVariable(_N, Unit.DAYS, _ATB),
    "variety": ConditionVariable(ValueType.VARIETY, None, _ATB),
    "purpose": ConditionVariable(ValueType.PURPOSE, None, _ATB),
    "storage_months": ConditionVariable(_N, Unit.MONTHS, _ATB),
    "soil_N_rating": ConditionVariable(_R, None, _ATB),
    "soil_P_rating": ConditionVariable(_R, None, _ATB),
    "soil_K_rating": ConditionVariable(_R, None, _ATB),
    "soil_pH": ConditionVariable(_N, None, _ATB),
    "grain_moisture_pct": ConditionVariable(_N, Unit.PCT, _ATB),
    "pest_count": ConditionVariable(_N, Unit.COUNT, _ASK),
    "spider_count_per_hill": ConditionVariable(_N, Unit.COUNT, _ASK),
}
