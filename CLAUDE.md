# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project rules

- docs/schema_v1.1.md is the source of truth
- use uv add for dependencies
- always MERGE on id; nothing is auto-corrected
- every number keeps its raw text; the LLM never converts units
- every fact needs a SourceSpan and an IN_REGION edge
- secrets come only from .env
- never create concepts automatically
- new PDFs are never committed (books are recorded by URL and sha256 in the source registry instead)

## What this repo is

CropBot is a farm-advice bot. This branch builds its Neo4j knowledge graph: every agronomic fact becomes a `Recommendation` node with applicability edges, ordered Steps, runtime Conditions and a `SourceSpan` quote (see `docs/schema_v1.1.md`). The stages are defined in the schema's "Build pipeline" section: register → convert → segment → tables → extract → normalise → validate → verify (Jev) → load. Product context (post-harvest focus, pilot plans) is in `CropBot_Research_Brief.md`.

## Environments and commands

There are two separate uv projects:

| Project | Python | Purpose |
|---|---|---|
| repo root (`pyproject.toml`) | 3.13 | Knowledge-graph pipeline: docling, neo4j, pydantic, python-dotenv, requests; pytest as a dev dependency |
| `extraction/` (`extraction/pyproject.toml`) | 3.12 | PDF → Markdown extraction. On Linux it pulls CUDA 13 torch for the team's GX10 (ARM64, GB10); it also adds easyocr, rapidfuzz, pypdf |

```bash
uv sync                                   # root environment
uv run python -m pytest                   # all tests (offline; none need Neo4j)
uv run python -m pytest tests/schema/test_rejections.py::test_rejected   # one test

uv run python -m kg.load.seed --check     # validate concepts/ without a database
uv run python -m kg.load.seed --counts    # node/relationship counts, no writes
uv run python -m kg.load.seed             # id constraints + MERGE concepts/ into Neo4j

uv run --project extraction python extraction/extract.py --list   # registry check: included, duplicate, unregistered PDFs
uv run --project extraction python extraction/extract.py --all --source tnau_agriculture
uv run --project extraction python extract.py --all               # original MVP script
```

`requirements.txt` is a leftover; dependencies go in `pyproject.toml` via `uv add`. There is no linter or formatter configured.

`.env.example` lists the variable names. Two scripts check the connections:

```bash
uv run python scripts/check_neo4j.py                                          # prints the Neo4j server version
uv run python scripts/check_jev.py --save docs/jev_response_example.json      # sends docs/jev_example.md, prints the raw reply
```

`--save` writes the reply only if it is HTTP 2xx, valid JSON, and contains neither the key nor anything key-like. Otherwise the script writes nothing and exits with an error.

### Jev notes

- `docs/jev_example.md` holds the reference request, and `docs/jev_response_example.json` holds a real reply to it. The key is `BEATAPI_API_KEY` in `.env`.
- `"type": "noul"` is a yes/no question. Its returned value is the probability of "yes", e.g. `{"safe": {"noul": 0.86, "type": "noul"}}`.
- Every question in one call is evaluated independently against the same `state`, so batching all of a section's claims into one call is valid.

### Neo4j notes

Local development runs Neo4j 2026.09.0 Enterprise. Which edition to deploy is a team decision; the research brief recommends Community. Vector-index quantisation is decided when the indexes are built.

## Existing code and how it relates to the schema

**Two versions of `extract.py`.**
- `extract.py` (root) is the original MVP. It handles 4 fixed books, downloads them into `sources/pdfs/`, and produced the committed `converted/` and `out/` folders (docling 2.140.0, run on CUDA).
- `extraction/extract.py` is the improved version. It reads every PDF in `BooksData/` using `extraction/sources.toml`. It keeps bounding boxes and footnotes, avoids false crop matches ("lime", "gram") and detects byte-identical duplicates by sha256.
- Both convert with Docling and flatten the result into an item list: `{k: h|p|li|tbl|img, lvl, t, md, img, cap, pg, ...}`. From that list they split each book by crop into `out/<crop>_<source_id>.md`.

**The committed `converted/*.index.json` files are lossy.**
- They store no bboxes, no OCR confidence and no Docling JSON. Tables are Markdown strings only, and footnotes were dropped. So they cannot supply `SourceSpan.bbox` or `table_ref` (`#/tables/N`).
- The schema's convert stage needs the lossless DoclingDocument JSON. That means a new conversion.
- The full conversion runs on the GX10. Its cache lives in `data/docling/`, keyed by the PDF's sha256. That folder is gitignored, so anyone can regenerate it from the registry.
- Until then, prototype segmentation on the committed rice text in `converted/tnau_agriculture.index.json`.

**Heading structure is not in the heading levels.**
- 96–99% of Docling headings come out at level 1, depending on the book. The section hierarchy ("1.8.3.1.Seed rate") is only in the heading text.
- Numbering spacing is inconsistent, and some headings run into body text ("1.1.1. Wet nursery Nursery area").
- Unnumbered sub-headings ("Nutrient management") belong to the previous numbered heading.

**Page numbers are PDF page numbers, not printed page numbers.** The TNAU rice chapter starts at PDF p. 13, but the book's contents table says p. 1.

**The crop segmentation in the committed `out/` is unreliable.**
- In the MVP output for `tnau_agriculture`, the rice chapter is interleaved with false `carnation`, `banana` and `fieldpea` segments; see `out/segmentation_report.md`.
- The files also append "Other mentions" from unrelated chapters. Build extraction units from the converted document, not from `out/`.

**`extraction/sources.toml` is the existing source registry.**
- It is keyed by file name and holds title, publisher, url, doc_type, a free-text region, OCR settings, page_range and include.
- It lacks the schema's fields: `state_id`, `region_scope`, `authority_tier`, `default_scope`, section overrides and a recorded `sha256`.
- `CROPS` in `extraction/extract.py` is a hand-written alias list. It can seed reviewed crop concepts and labels, but a script must not turn it into concepts.

**PDFs.**
- 51 PDFs (about 590 MB) are already tracked: `BooksData/`, `sources/pdfs/` and `data/raw/`. Leave them as they are.
- New PDFs in any of those folders are gitignored.
- `data/raw/AGRICULTURE.pdf`, `BooksData/AGRICULTURE.pdf` and `sources/pdfs/tnau_agriculture.pdf` are the same file (TNAU Crop Production Guide 2020).

**`Graph_Rag_try.py`** is a discarded prototype. It uses unconstrained `LLMGraphTransformer` on fixed-size chunks with hard-coded Neo4j credentials. It conflicts with the schema, so don't extend it.

**Soil Health Card scrapers** (`state_retrival.py`, `district_retrival.py`, `block_retrival.py`, `village_retrival.py`, `data_scraper.py`, notes in `cheetsheet.txt`):
- **Do not run or modify them.**
- They crawl soilhealth4.dac.gov.in.
- The research brief says to stop them because of the portal's terms of service.
- Their region IDs are portal-internal, not the LGD codes the schema uses.
- Live data stays out of the graph anyway (schema design principle 8).

## Pipeline layout

New pipeline code goes in the plain `kg/` package and runs as `uv run python -m kg.<stage>`. There is no build-system section and no `src/` layout.

```
registry/            one hand-written TOML file per book: url, sha256, state_id, region_scope, authority_tier, edition_year, default_scope, section scopes
concepts/            hand-curated concept and label files (crops, regions with LGD codes, pests, ingredients); the only way concepts are created
kg/
  registry/          load and validate the registry; check each PDF's sha256 against it
  convert/           Docling → DoclingDocument JSON in data/docling/<sha256>/ (gitignored)
  segment/           heading tree from the numbering text → one unit per section (heading path, text, tables, pages, scope)
  tables/            join tables split across pages, rotate variety tables, check header and row counts against the page
  schema/            Pydantic models mirroring the schema, plus fixed vocabularies (units, basis, condition variables)
  extract/           one LLM call per unit → facts with raw text and quotes
  normalize/         units and basis, ranges, linking names to concepts (exact, alias, embedding → proposals for review)
  validate/          exact quote match, every raw number appears in its quote, vocabularies, banned list, alternative-totals check
  verify/            Jev claims built from stored fields
  load/              constraints, MERGE writers, IN_REGION edges, revision rules
  conflicts/         CONFLICTS_WITH detection
  eval/              gold set, precision/recall per subtype, the 20 competency questions
scripts/             one-off checks (e.g. Neo4j and Jev connectivity)
tests/               mirrors kg/
data/gold/           hand-annotated sections (committed)
```

## IDs and loading

- Every node label has a uniqueness constraint on `id`, including Step, Condition, ThresholdClause, Label and the 16 subtype labels (`kg/load/constraints.py`). Every write is `MERGE` on `id`.
- **Step, Condition and ThresholdClause IDs** are derived from their parent Recommendation's ID. The exact format is decided with the fact loader.
- **Label IDs** are `label:` plus a hash of the concept ID, kind, language and NFC-normalised text (`kg.schema.ids.label_id`). Kind is part of the key, so the same text can be both an alias and a vernacular name.
- Labels are words farmers and books actually use. Scientific names go in `Crop.scientific_name`, never in a Label.
- Every concept has `name_en`, regions included (schema Conventions: "name_en on every concept").

## Concept seeds (`concepts/`)

- **Format:**
  - One CSV per node label, UTF-8 with a header row (`concepts/<label>s.csv`; file → model map in `kg.schema.concepts.SEED_FILES`).
  - An empty cell means null. Every row has `review_status` (`approved` | `needs_review`) and a `source` saying where its values came from.
- **Unknown values:** a row containing `TODO` anywhere is skipped and reported as pending. Never invent an LGD code or a value; write TODO.
  - The pilot state and all districts are TODO for now. District names and zones come from the TNAU rice variety table, but their LGD codes are unknown.
- **Validation before any write** (`kg.load.seed`):
  - ID prefixes;
  - duplicate IDs across all files;
  - references (`state_id`, `zone_id`, `maps_to`, label `concept_id`) must point at loaded nodes;
  - a LocalSeason needs `state_id`;
  - Season, Purpose and OperationType must equal the schema's closed lists.
- **needs_review concepts are loaded,** with `review_status: needs_review`.
- **Review rule for linking and loading (steps 10 and 13):**
  - Linking may use needs_review concepts, but any fact linked to a needs_review concept must itself be needs_review.
  - Both seeded crops are needs_review, so every rice and wheat fact stays needs_review until those two rows are approved.
  - Fertilizer percentages with `review_status: needs_review` must not be used by the alternatives check until approved. All four seeded fertilizers are needs_review.

## Pending schema changes (v1.2, not yet in the doc)

Build to these, but don't edit `docs/schema_v1.1.md`; the schema owner is updating it to v1.2. They are marked `pending schema v1.2` in `kg/schema/`.

1. **Two page numbers.** `SourceSpan` holds both `pdf_page` (the PDF page, used to locate text) and `printed_page` (the page number printed in the book, used in citations). Docling reports PDF pages.
2. **Raw text for every number.**
   - `ThresholdClause` gets a `raw` field.
   - Each subtype gets a `raw` map from field name to source text, required for every non-null numeric field (for example `DryingSpec.raw["target_moisture_pct_max"] = "12 - 13 %"`).
   - `APPLIES.raw` covers the whole quantity phrase, including `water_l_per_ha` and `area_cents`.
3. **Condition-only units.** `mm` (`forecast_rain_mm_24h`) and `degC` (`tmax_c`) are allowed only in Conditions, as `ConditionOnlyUnit`. Dose units stay as listed in the doc.
4. **Strict bounds.** Every bound has a `<field>_inclusive` flag (default true): each min/max pair, `APPLIES.min`/`max`, `Step.offset_min`/`offset_max`, and `StorageRule.max_moisture_pct`. "Less than 8 %" is stored as `max_moisture_pct: 8, max_moisture_pct_inclusive: false`.
5. **Hour offsets.** `Step.offset_unit` is `days` (default) or `hours`, so "18 to 24 hrs after sowing" can be stored.
6. **Editions.** `Source.edition_year` is the integer start year, used for ranking. `edition_label` keeps the edition as written ("2021-22").
7. **IDs are prefixed and lowercase everywhere** (`season:rabi`, `nutrient:p2o5`). v1.2 fixes the doc's farm context (`"season": "rabi"`) and its uppercase Nutrient IDs. The prefixes the doc doesn't name are the ones in `kg/schema/ids.py`.
8. **Worked example 2 is wrong.** The book gives short-term seed storage as 8–9 months, not 0–9. Follow the book.

Decisions on gaps that don't change the doc:
- `sowing_date`, `variety` and `purpose` are in the condition-variable registry only for their `on_unknown` policy. Applicability to a variety or purpose is always an edge.
- `soil_pH` is the only soil value variable; add others when a source needs them.
- Every NutrientDose step has `APPLIES` quantities, and a ControlMeasure has at least one Step.
- `CONFLICTS_WITH` is recorded on both facts. Conflict detection must never create duplicate links: one link per pair of facts, however often detection runs.

## Known issues for segmentation and tables (steps 6–7)

Found in the committed TNAU conversion while building the schema tests:
- **Rice seed sub-headings are missing on pp. 74–75.** The harvest, drying, seed-treatment and storage sub-headings of `RICE - VARIETAL SEED PRODUCTION` are absent, so those bullets sit under "Roguing space". The tests use the chapter heading as `section_path`.
- **The grain-drying sentence is under the wrong heading.** "Dry the grains to 12% moisture level for storage." (p. 39) sits under "Non-Puddled machine Transplanted Rice (NPTR)".
- **No `table_ref`.** Table facts such as the BPH threshold (p. 64) can't get a `#/tables/N` pointer until the full Docling JSON conversion exists.
