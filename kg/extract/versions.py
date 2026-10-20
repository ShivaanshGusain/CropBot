"""What each prompt version's answer looks like. The raw model is shared; a version adds its
envelope and the fields it requires or forbids, so answers stored under v1 still check as v1."""

from typing import NamedTuple

from .model import NESTED, SUBTYPES, NotExtracted


class Version(NamedTuple):
    name: str
    envelope: str               # "list": a JSON list of facts; "object": {"facts", "not_extracted"}
    forbidden: frozenset        # fields the answer must not contain
    step_requires: frozenset    # fields every step must have
    coverage: bool              # every text line and table row must be quoted somewhere


VERSIONS = {
    "v1": Version("v1", "list", frozenset({"extraction_flags"}), frozenset({"instruction_en"}), False),
    "v2": Version("v2", "object", frozenset({"instruction_en"}), frozenset(), True),
}
LATEST = "v2"


def field_names(version: str) -> set[str]:
    """Every field name the version's answer may use (the prompt's field reference lists them)."""
    v = VERSIONS[version]
    names = set()
    for m in SUBTYPES + NESTED:
        names |= set(m.model_fields)
    names -= v.forbidden
    if v.envelope == "object":
        names |= {"facts", "not_extracted"} | set(NotExtracted.model_fields)
    return names


def version_problems(item, version: str) -> list[str]:
    """Rules of the version that the shared model does not enforce."""
    v, out = VERSIONS[version], []
    if not isinstance(item, dict):
        return out
    for name in v.forbidden & set(item):
        out.append("%s: not part of prompt %s" % (name, version))
    for i, step in enumerate(item.get("steps") or []):
        if not isinstance(step, dict):
            continue
        for name in v.forbidden & set(step):
            out.append("steps.%d.%s: not part of prompt %s" % (i, name, version))
        for name in v.step_requires - set(step):
            out.append("steps.%d.%s: required by prompt %s" % (i, name, version))
    return out
