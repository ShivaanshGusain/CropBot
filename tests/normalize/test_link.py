"""Offline tests for name linking (kg.normalize.link): no embeddings, nothing created."""

from kg.normalize.link import Linker, normalise
from kg.schema.concepts import AgroClimaticZone, Fertilizer, Label, Nutrient, Purpose, SoilType

NODES = [
    Fertilizer(id="fertilizer:dap", name_en="Diammonium phosphate (DAP)", n_pct=18, p2o5_pct=46, k2o_pct=0,
               review_status="needs_review", source="x"),
    Fertilizer(id="fertilizer:ssp", name_en="Single super phosphate (SSP)", n_pct=0, p2o5_pct=16, k2o_pct=0,
               review_status="needs_review", source="x"),
    Nutrient(id="nutrient:n", name_en="Nitrogen", symbol="N", review_status="approved"),
    Nutrient(id="nutrient:p2o5", name_en="Phosphorus as P2O5", symbol="P2O5", review_status="approved"),
    Purpose(id="purpose:seed", name_en="Seed", review_status="approved"),
    SoilType(id="soil:clay", name_en="Clay", review_status="approved"),
    SoilType(id="soil:clay_loam", name_en="Clay", review_status="approved"),          # a deliberate clash
    AgroClimaticZone(id="zone:tn_cauvery_delta", name_en="Cauvery Delta Zone", scheme="state_book",
                     state_id="state:33", review_status="needs_review"),
    Label(concept_id="fertilizer:dap", text="DAP", lang="en", script="Latn", kind="canonical", review_status="approved"),
    Label(concept_id="fertilizer:ssp", text="super phosphate", lang="en", script="Latn", kind="alias",
          review_status="needs_review"),
]
VARIETIES = [{"id": "variety:adt_38", "name": "ADT 38", "review_status": "needs_review"}]
L = Linker(NODES, VARIETIES)


def test_normalise():
    assert normalise("Seeds") == "seed" and normalise("clayey soils") == "clayey soil" and normalise("ADT-38") == "adt 38"


def test_exact_label_then_alias_then_normalised():
    assert L.link("DAP", ("fertilizer",))[:2] == ("fertilizer:dap", "label_exact")
    assert L.link("super phosphate", ("fertilizer",))[:2] == ("fertilizer:ssp", "label_alias")
    assert L.link("seeds", ("purpose",))[:2] == ("purpose:seed", "normalised")
    assert L.link("ADT 38", ("variety",))[:2] == ("variety:adt_38", "normalised")


def test_review_status_is_the_weaker_of_concept_and_label():
    assert L.link("DAP", ("fertilizer",)).review_status == "needs_review"          # approved label, needs_review concept
    assert L.link("seeds", ("purpose",)).review_status == "approved"
    assert L.link("super phosphate", ("fertilizer",)).review_status == "needs_review"


def test_nutrient_symbols_and_the_npk_convention():
    assert L.link("N", ("nutrient",))[:2] == ("nutrient:n", "symbol")
    p = L.link("P", ("nutrient", "fertilizer"))
    assert (p.id, p.method, p.review_status) == ("nutrient:p2o5", "npk_convention", "needs_review")


def test_unlinked_generic_ambiguous_and_wrong_type():
    assert L.link("clayey soils", ("soil",)).reason == "no concept matches"
    assert L.link("Pest", ("pest", "disease")).reason == "generic target, no concept"
    assert L.link("Clay", ("soil",)).reason.startswith("ambiguous")
    assert L.link("DAP", ("pest",)).id is None                                    # right name, wrong concept type
    assert L.link("ADT 46", ("variety",)).id is None
