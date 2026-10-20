"""concepts/proposed/: drafted seed rows for review. They validate against the concept models but are
never loaded (kg.load.seed reads only SEED_FILES in concepts/)."""

import csv

from kg.load.seed import CONCEPTS_DIR, read_seed
from kg.schema.concepts import PROPOSED_FILES, ActiveIngredient, Label

PROPOSED = CONCEPTS_DIR / "proposed"


def rows(name):
    with open(PROPOSED / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def proposed_nodes():
    nodes, pending = [], []
    for name, model in PROPOSED_FILES.items():
        for row in rows(name):
            if any("TODO" in (v or "") for v in row.values()):
                pending.append((name, row["id"]))
                continue
            nodes.append(model.model_validate({k: v for k, v in row.items() if v}))
    return nodes, pending


def test_proposed_rows_validate_and_are_all_needs_review():
    nodes, pending = proposed_nodes()
    assert nodes and all(n.review_status.value == "needs_review" for n in nodes)
    assert pending == [("fertilizers.csv", "fertilizer:znso4"), ("fertilizers.csv", "fertilizer:feso4")]


def test_active_ingredients_never_take_reg_status_from_the_book():
    nodes, _ = proposed_nodes()
    ais = [n for n in nodes if isinstance(n, ActiveIngredient)]
    assert len(ais) > 30 and all(a.reg_status.value == "unknown" for a in ais)
    assert all("CIB&RC" in a.source for a in ais)


def test_labels_point_at_proposed_or_seeded_concepts_and_brands_are_marked():
    nodes, pending = proposed_nodes()
    known = {n.id for n in nodes if not isinstance(n, Label)} | {i for _, i in pending}
    known |= {n.id for n in read_seed().nodes if not isinstance(n, Label)}
    labels = [n for n in nodes if isinstance(n, Label)]
    assert all(lb.concept_id in known for lb in labels), [lb.concept_id for lb in labels if lb.concept_id not in known]
    brand = next(lb for lb in labels if lb.text == "Bavistin")
    assert brand.source.startswith("REVIEW: BRAND NAME")


def test_proposed_rows_are_not_loaded():
    seeded = {n.id for n in read_seed().nodes}
    assert "pest:brown_planthopper" not in seeded and "ai:carbendazim" not in seeded
