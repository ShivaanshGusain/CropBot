"""Claims for Jev, built by code from a fact's stored fields; no model writes or rewrites them.

One yes/no claim per step and value ("Does the passage state that DAP is applied at 40 kg per 20 cents
of nursery before the last puddling?"), per threshold clause, per moisture / months / depth field and
per ingredient a Caution concerns. A fact none of these apply to gets no claim and needs human review.
"""

import copy
import hashlib

BASIS = {"per_ha": "per hectare", "per_kg_seed": "per kg of seed", "per_l_water": "per litre of water",
         "per_m2": "per square metre", "per_hill": "per hill", "per_tiller": "per tiller", "per_plant": "per plant",
         "absolute": ""}
UNIT = {"kg": "kg", "g": "g", "t": "tonnes", "l": "litres", "ml": "ml", "pct": "%", "count": "", "cm": "cm",
        "m": "m", "days": "days", "months": "months"}
ANCHOR = {"sowing": "sowing", "transplanting": "transplanting", "PI": "panicle initiation", "flowering": "flowering",
          "harvest": "harvest", "last_puddling": "the last puddling", "pulling_out": "pulling out the seedlings",
          "storage_start": "the start of storage"}
OPS = {"<": "fewer than", "<=": "at most", ">": "more than", ">=": "at least", "==": "exactly", "!=": "other than"}
NO_CLAIM = "human review required: no code-built claim"


def num(v: float) -> str:
    return ("%.4f" % v).rstrip("0").rstrip(".")


def span(lo, hi) -> str:
    return num(lo) if lo == hi or hi is None else "%s to %s" % (num(lo), num(hi))


def amount(a: dict) -> str:
    """The quantity in the source's own terms: per_cent_nursery is rebuilt as value x area_cents."""
    lo = a.get("value") if a.get("value") is not None else a.get("min")
    hi = a.get("value") if a.get("value") is not None else a.get("max")
    if a["basis"] == "per_cent_nursery":
        area = a["area_cents"]
        lo, hi = lo * area, hi * area
        per = "per cent of nursery" if area == 1 else "per %s cents of nursery" % num(area)
    else:
        per = BASIS[a["basis"]]
    unit = UNIT[a["unit"]]
    if unit == "tonnes" and lo == hi == 1:
        unit = "tonne"
    text = span(lo, hi) + ("%s" % unit if unit == "%" else (" " + unit if unit else ""))
    return (text + " " + per).strip()


def timing(s: dict) -> str:
    if s.get("offset_min") is not None or s.get("offset_max") is not None:
        lo, hi = s.get("offset_min"), s.get("offset_max")
        lo = lo if lo is not None else hi
        unit = s.get("offset_unit") or "days"
        anchor = ANCHOR.get(s.get("anchor"), s.get("anchor"))
        if (hi is None or hi == lo) and lo == 0:
            return " at %s" % anchor
        if hi is None:
            return " from %s %s after %s onwards" % (num(abs(lo)), unit, anchor)
        side = "before" if lo < 0 else "after"
        a, b = sorted((abs(lo), abs(hi)))
        return " %s %s %s" % (span(a, b), unit, side + " " + anchor)
    if s.get("timing_raw"):
        return " " + s["timing_raw"]
    return ""


def lead(fact: dict, names: dict) -> str:
    """", for short duration varieties grown for seed on clay soils, " or ""."""
    subject = "%s duration varieties" % fact["duration_group"] if fact.get("duration_group") else None
    mods = []
    if fact.get("variety_ids"):
        subject = "the variety " + " or ".join(names.get(i, i) for i in fact["variety_ids"])
    if fact.get("purpose_ids"):
        mods.append("grown for " + " or ".join(names.get(i, i).lower() for i in fact["purpose_ids"]))
    if fact.get("soil_ids"):
        mods.append("on " + " or ".join(names.get(i, i).lower() for i in fact["soil_ids"]) + " soils")
    if fact.get("system_ids"):
        mods.append("under " + " or ".join(names.get(i, i).lower() for i in fact["system_ids"]))
    if not subject and not mods:
        return ""
    return ", for %s, " % " ".join([subject or "the crop"] + mods)


def condition(c: dict) -> str:
    what = "the " + c["variable"].replace("_", " ")
    if c["op"] == "between":
        return "%s is between %s and %s" % (what, num(c["value"]), num(c["value_max"]))
    value = c["value"] if not isinstance(c["value"], list) else ", ".join(map(str, c["value"]))
    return "%s is %s %s" % (what, OPS.get(c["op"], c["op"]), num(value) if isinstance(value, float) else value)


def _q(text: str) -> str:
    """"that, for x, y" when there is a lead-in, else "that y"."""
    return "Does the passage state that%s?" % (text if text.startswith(",") else " " + text)


def _name(a: dict, names: dict) -> str:
    """Target and formulation: "Acephate 75 % SP", "Azospirillum (Carrier based)"."""
    name, form = names.get(a["target_id"], a["target_id"]), a.get("formulation")
    if not form:
        return name
    return "%s %s" % (name, form) if form[0].isdigit() else "%s (%s)" % (name, form)


def step_claims(fact: dict, names: dict) -> list[str]:
    out = []
    targets = " or ".join(names.get(i, i) for i in fact.get("target_ids") or [])
    against = " against %s" % targets if targets and fact["subtype"] == "ControlMeasure" else ""
    for s in fact["steps"]:
        cond = " (%s)" % s["condition_raw"] if s.get("condition_raw") else ""
        conds = "".join(" when %s" % condition(c) for c in s.get("conditions") or [])
        for a in s["applies"]:
            out.append(_q("%s%s is applied%s at %s%s%s%s" % (lead(fact, names), _name(a, names), against, amount(a),
                                                              timing(s), conds, cond)))
        if not s["applies"] and timing(s) and fact.get("depth_cm") is None:
            op = (s.get("operation") or "").replace("_", " ")
            method = " (%s)" % s["method"] if s.get("method") else ""
            out.append(_q("%s%s%s is done%s%s%s" % (lead(fact, names), op, method, timing(s), conds, cond)))
    return out


def fallback_claims(fact: dict, names: dict) -> list[str]:
    """A fact whose only content is untimed steps: one claim per step from its operation and method."""
    out = []
    for s in fact["steps"]:
        if s.get("method"):
            op = (s.get("operation") or "").replace("_", " ")
            cond = " (%s)" % s["condition_raw"] if s.get("condition_raw") else ""
            out.append(_q("%sthe advice includes %s: %s%s" % (lead(fact, names), op, s["method"], cond)))
    return out


def field_claims(fact: dict, names: dict) -> list[str]:
    st, out, ld = fact["subtype"], [], lead(fact, names)

    def pct(prefix):
        lo, hi = fact.get(prefix + "_min"), fact.get(prefix + "_max")
        if lo is None and hi is None:
            return None
        if lo is None:
            word = "below" if fact.get(prefix + "_max_inclusive") is False else "at most"
            return "%s %s%%" % (word, num(hi))
        return "%s%%" % span(lo, hi)

    if st == "HarvestRule":
        if pct("harvest_moisture_pct"):
            out.append(_q("%sthe crop is harvested at %s moisture" % (ld, pct("harvest_moisture_pct"))))
        if pct("threshing_moisture_pct"):
            out.append(_q("%sthreshing is done at %s moisture" % (ld, pct("threshing_moisture_pct"))))
    elif st == "DryingSpec" and pct("target_moisture_pct"):
        term = " for %s" % fact["storage_term_raw"] if fact.get("storage_term_raw") else ""
        out.append(_q("%sthe produce is dried to %s moisture%s" % (ld, pct("target_moisture_pct"), term)))
    elif st == "StorageRule" and (fact.get("storage_months_min") is not None or fact.get("max_moisture_pct") is not None):
        lo, hi = fact.get("storage_months_min"), fact.get("storage_months_max")
        if lo is not None and hi is None:
            months = "for more than %s months" % num(lo) if fact.get("storage_months_min_inclusive") is False \
                else "for at least %s months" % num(lo)
        elif lo is not None:
            months = "for %s months" % span(lo, hi)
        else:
            months = ""
        m = fact.get("max_moisture_pct")
        moist = "" if m is None else " at a moisture content %s %s%%" % (
            "below" if fact.get("max_moisture_pct_inclusive") is False else "of at most", num(m))
        where = " in %s" % fact["structure"] if fact.get("structure") else ""
        out.append(_q("%sit is stored %s%s%s" % (ld, months, moist, where)))
    elif st == "IrrigationRule" and fact.get("depth_cm") is not None:
        when = timing(fact["steps"][0]) if fact["steps"] else ""
        out.append(_q("%sa water depth of %s cm is kept%s" % (ld, num(fact["depth_cm"]), when)))
    elif st == "PestThreshold":
        pests = " or ".join(names.get(i, i) for i in fact["pest_ids"])
        for c in fact["clauses"]:
            unit = "%" if c["unit"] == "pct" else ""
            per = " " + BASIS.get(c.get("sampling_unit") or "absolute", "") if c.get("sampling_unit") else ""
            conds = "".join(" when %s" % condition(x) for x in c.get("conditions") or [])
            out.append(_q("action against %s is needed at %s%s %s%s%s" % (pests, num(c["value"]), unit, c["observation"],
                                                                           per, conds)))
    elif st == "Caution":
        for i in fact.get("concerns") or []:
            out.append(_q("%sit advises against using %s" % (ld, names.get(i, i))))
    return out


def claims_for(fact: dict, names: dict) -> list[str]:
    """[] means no code-built claim: the fact needs human review and can never be auto_verified."""
    out = field_claims(fact, names) + step_claims(fact, names)
    if not out and fact["subtype"] != "Caution":
        out = fallback_claims(fact, names)
    return out


def claim_key(fact_key: str, claim: str, control: bool = False) -> str:
    return ("x_" if control else "c_") + hashlib.sha1(("%s|%s" % (fact_key, claim)).encode("utf-8")).hexdigest()[:16]


PCT_FIELDS = ("target_moisture_pct", "harvest_moisture_pct", "threshing_moisture_pct")


def _changed(fact: dict) -> dict | None:
    """A copy with the first number changed: x2, or +10 points for a percentage. None if no number."""
    f = copy.deepcopy(fact)
    for s in f["steps"]:
        for a in s["applies"]:
            if any(a.get(k) is not None for k in ("value", "min", "max")):
                for k in ("value", "min", "max"):
                    if a.get(k) is not None:
                        a[k] = a[k] + 10 if a["unit"] == "pct" else a[k] * 2
                return f
    for p in PCT_FIELDS:
        if f.get(p + "_min") is not None or f.get(p + "_max") is not None:
            for k in (p + "_min", p + "_max"):
                if f.get(k) is not None:
                    f[k] += 10
            return f
    for k, step in (("max_moisture_pct", 10), ("depth_cm", None)):
        if f.get(k) is not None:
            f[k] = f[k] + step if step else f[k] * 2
            return f
    if f.get("clauses"):
        f["clauses"][0]["value"] *= 2
        return f
    return None


def control_claim(fact: dict, names: dict) -> str | None:
    """A deliberately wrong claim: the fact's first numeric claim with one number changed."""
    changed = _changed(fact)
    if changed is None:
        return None
    pairs = zip(claims_for(fact, names), claims_for(changed, names))
    return next((b for a, b in pairs if a != b), None)
