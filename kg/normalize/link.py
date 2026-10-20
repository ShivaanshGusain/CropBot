"""Names as printed -> concept IDs. No embeddings yet (BGE-M3 is not set up), and never a new
concept: unmatched or ambiguous names go to review.

Order: (1) a Label whose text equals the name, (2) the same with an alias/abbreviation label,
(3) a normalised match (casefold, punctuation removed, a trailing plural dropped) against
name_en, the ID slug and every label. Nutrient symbols match exactly ("N"). "P" and "K" follow
the book's N:P2O5:K2O convention, an inference that sends the fact to review.
"""

import json
import re
from collections import defaultdict
from typing import NamedTuple

from kg.load.seed import read_seed
from kg.registry import ROOT
from kg.schema.concepts import Label, Nutrient
from kg.tables import TABLES_DIR

GENERIC = {"pest", "disease", "weed", "rodent", "insect pest", "pest and disease"}
NPK_CONVENTION = {"P": "nutrient:p2o5", "K": "nutrient:k2o"}


class Link(NamedTuple):
    id: str | None
    method: str                 # label_exact | label_alias | normalised | symbol | npk_convention | ...
    review_status: str | None   # of the concept and of the label used, the weaker one
    reason: str | None = None   # why it did not link


def normalise(text: str) -> str:
    words = re.sub(r"[^0-9a-z]+", " ", text.casefold()).split()
    if words:
        w = words[-1]
        if w.endswith("ies") and len(w) > 4:
            words[-1] = w[:-3] + "y"
        elif w.endswith("s") and not w.endswith("ss") and len(w) > 3:
            words[-1] = w[:-1]
    return " ".join(words)


class Linker:
    def __init__(self, nodes, varieties=()):
        self.status = {}                          # concept id -> review_status
        self.exact = defaultdict(set)             # label text -> {(concept id, label status, kind)}
        self.norm = defaultdict(set)              # normalised form -> {(concept id, label status or None)}
        self.symbol = {}
        for n in nodes:
            if isinstance(n, Label):
                self.exact[n.text].add((n.concept_id, n.review_status.value, n.kind.value))
                self.norm[normalise(n.text)].add((n.concept_id, n.review_status.value))
                continue
            self.status[n.id] = n.review_status.value
            self.norm[normalise(n.name_en)].add((n.id, None))
            self.norm[normalise(n.id.split(":", 1)[1].replace("_", " "))].add((n.id, None))
            if isinstance(n, Nutrient):
                self.symbol[n.symbol] = n.id
        for v in varieties:
            self.status[v["id"]] = v["review_status"]
            self.norm[normalise(v["name"])].add((v["id"], None))

    @classmethod
    def for_source(cls, entry):
        path = TABLES_DIR / entry.id.split(":", 1)[1] / "varieties.jsonl"
        varieties = [json.loads(line) for line in open(path, encoding="utf-8")] if path.exists() else []
        return cls(read_seed().nodes, varieties)

    def _status(self, concept_id, label_status=None):
        statuses = {self.status.get(concept_id), label_status} - {None}
        return "needs_review" if "needs_review" in statuses else "approved"

    def link(self, name: str, prefixes: tuple[str, ...]) -> Link:
        """`prefixes`: the ID prefixes this name may link to, e.g. ("pest", "disease")."""
        def ok(cid):
            return cid.split(":", 1)[0] in prefixes

        if normalise(name) in GENERIC:
            return Link(None, "generic", None, "generic target, no concept")
        if "nutrient" in prefixes:
            if name in self.symbol:
                return Link(self.symbol[name], "symbol", self._status(self.symbol[name]))
            if name in NPK_CONVENTION:
                cid = NPK_CONVENTION[name]
                return Link(cid, "npk_convention", "needs_review")
        for method, kinds in (("label_exact", {"canonical"}),
                              ("label_alias", {"alias", "abbreviation", "vernacular", "transliteration"})):
            hits = {(c, s) for c, s, k in self.exact.get(name, ()) if ok(c) and k in kinds}
            ids = {c for c, _ in hits}
            if len(ids) == 1:
                cid = ids.pop()
                weakest = "needs_review" if any(s == "needs_review" for _, s in hits) else "approved"
                return Link(cid, method, self._status(cid, weakest))
            if len(ids) > 1:
                return Link(None, method, None, "ambiguous: %s" % sorted(ids))
        hits = {(c, s) for c, s in self.norm.get(normalise(name), ()) if ok(c)}
        ids = {c for c, _ in hits}
        if len(ids) == 1:
            cid = ids.pop()
            label = "needs_review" if any(s == "needs_review" for _, s in hits) else None
            return Link(cid, "normalised", self._status(cid, label))
        if len(ids) > 1:
            return Link(None, "normalised", None, "ambiguous: %s" % sorted(ids))
        return Link(None, "none", None, "no concept matches")
