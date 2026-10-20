"""Printed units and bases -> canonical ones (schema Conventions), in code only.

Every rule returns its name so each conversion can be logged; a printed form with no rule
returns None and the fact is held, never guessed.
  1 acre = 0.404686 ha; 1 cent = 1/100 acre = 40.4686 m2; 1 quintal = 100 kg.
  per_cent_nursery: value per one cent of nursery; area_cents = the area the source stated.
"""

import re
from typing import NamedTuple

from kg.schema.vocab import Basis, Unit

HA_PER_ACRE = 0.404686
CENTS_PER_HA = 100 / HA_PER_ACRE            # 247.105...
ACRES_PER_HA = 1 / HA_PER_ACRE              # 2.47105...


class UnitRule(NamedTuple):
    unit: Unit
    factor: float
    rule: str


class BasisRule(NamedTuple):
    basis: Basis
    factor: float               # multiply the amount by this
    area_cents: float | None
    rule: str
    inference: bool             # the printed text alone does not fix the basis


UNITS = {
    "kg": (Unit.KG, 1), "kgs": (Unit.KG, 1), "g": (Unit.G, 1), "gm": (Unit.G, 1),
    "t": (Unit.T, 1), "tonne": (Unit.T, 1), "tonnes": (Unit.T, 1), "ton": (Unit.T, 1),
    "l": (Unit.L, 1), "lit": (Unit.L, 1), "litre": (Unit.L, 1), "liter": (Unit.L, 1), "lt": (Unit.L, 1),
    "ml": (Unit.ML, 1), "%": (Unit.PCT, 1), "pct": (Unit.PCT, 1), "per cent": (Unit.PCT, 1),
    "count": (Unit.COUNT, 1), "nos.": (Unit.COUNT, 1), "nos": (Unit.COUNT, 1), "no.": (Unit.COUNT, 1),
    "q": (Unit.KG, 100), "quintal": (Unit.KG, 100), "quintals": (Unit.KG, 100),
    "cm": (Unit.CM, 1), "m": (Unit.M, 1), "days": (Unit.DAYS, 1), "months": (Unit.MONTHS, 1),
}


def canon_unit(printed: str | None) -> UnitRule | None:
    if printed is None:
        return None
    key = printed.strip().lower()
    if key not in UNITS:
        return None
    unit, factor = UNITS[key]
    rule = "%s -> %s" % (printed, unit.value) + (" (x%g)" % factor if factor != 1 else "")
    return UnitRule(unit, factor, rule)


def _clean(text: str) -> str:
    t = text.lower().replace("(", " ").replace(")", " ").replace("@", " ")
    return re.sub(r"\s+", " ", t).strip()


def canon_basis(printed: str | None, nursery: bool = False, seed_treatment: bool = False) -> BasisRule | None:
    """`nursery`: the fact sits in a nursery section; `seed_treatment`: a treatment of seed."""
    if printed is None:
        return None
    t = _clean(printed)
    if t in ("per_ha", "/ha", "/ ha", "per ha", "per hectare", "/hectare", "ha-1", "ha -1"):
        return BasisRule(Basis.PER_HA, 1, None, "%s -> per_ha" % printed, False)
    if t in ("kernel/ha",):
        return BasisRule(Basis.PER_HA, 1, None, "%s -> per_ha (amount of kernel per ha)" % printed, False)
    if t in ("for one hectare", "one hectare of seeds", "for 1 ha"):
        return BasisRule(Basis.PER_HA, 1, None, "%s -> per_ha (the amount for one hectare)" % printed, True)
    if t in ("/acre", "/ acre", "per acre"):
        return BasisRule(Basis.PER_HA, ACRES_PER_HA, None, "%s -> per_ha (x%.5f)" % (printed, ACRES_PER_HA), False)
    m = re.fullmatch(r"(?:to|per|for)?\s*(\d+(?:\.\d+)?)\s*cents?\s*(?:of\s*)?nursery", t)
    if m:
        area = float(m.group(1))
        return BasisRule(Basis.PER_CENT_NURSERY, 1 / area, area,
                         "%s -> per_cent_nursery (/%g, area_cents %g)" % (printed, area, area), False)
    if t in ("/cent", "/ cent", "per cent", "per cent of nursery"):
        if nursery:
            return BasisRule(Basis.PER_CENT_NURSERY, 1, 1, "%s in a nursery section -> per_cent_nursery "
                                                            "(area_cents 1)" % printed, False)
        return BasisRule(Basis.PER_HA, CENTS_PER_HA, None, "%s -> per_ha (x%.3f)" % (printed, CENTS_PER_HA), False)
    m = re.fullmatch(r"per\s*(\d+(?:\.\d+)?)?\s*m\s*2|/\s*m\s*2|per\s*m2", t)
    if m:
        area = float(m.group(1)) if m.lastindex and m.group(1) else 1.0
        return BasisRule(Basis.PER_M2, 1 / area, None, "%s -> per_m2%s" % (printed, " (/%g)" % area if area != 1 else ""),
                         False)
    if re.fullmatch(r"/\s*kg\s*of\s*seeds?|per\s*kg\s*(?:of\s*)?seeds?", t):
        return BasisRule(Basis.PER_KG_SEED, 1, None, "%s -> per_kg_seed" % printed, False)
    if seed_treatment and re.fullmatch(r"/\s*kg", t):
        return BasisRule(Basis.PER_KG_SEED, 1, None, "%s in a seed treatment -> per_kg_seed" % printed, True)
    m = re.fullmatch(r"/\s*l(?:it)?\s*of\s*water(?:.*)?|per\s*l(?:itre)?\s*of\s*water", t)
    if m:
        return BasisRule(Basis.PER_L_WATER, 1, None, "%s -> per_l_water" % printed, False)
    m = re.fullmatch(r"in\s*(\d+(?:\.\d+)?)\s*l(?:it)?\s*of\s*water", t)
    if m:
        vol = float(m.group(1))
        return BasisRule(Basis.PER_L_WATER, 1 / vol, None, "%s -> per_l_water (/%g)" % (printed, vol), False)
    m = re.fullmatch(r"/\s*(tiller|hill|plant)", t)
    if m:
        return BasisRule(Basis("per_" + m.group(1)), 1, None, "%s -> per_%s" % (printed, m.group(1)), False)
    if t in ("per hill", "per tiller", "per plant"):
        return BasisRule(Basis(t.replace(" ", "_")), 1, None, "%s -> %s" % (printed, t.replace(" ", "_")), False)
    return None


def water_l_per_ha(printed: str | None) -> float | None:
    """"500 l/ha" -> 500; anything else (e.g. "1lit of water" for soaking) has no slot."""
    if not printed:
        return None
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:l|lit|litres?)\s*/\s*ha", printed.strip().lower())
    return float(m.group(1)) if m else None
