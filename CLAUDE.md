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
| repo root (`pyproject.toml`) | 3.13 | Knowledge-graph pipeline: docling pinned to 2.140.0 (same as `extraction/` and the committed `converted/`), easyocr, neo4j, pydantic, python-dotenv, requests; pytest as a dev dependency |
| `extraction/` (`extraction/pyproject.toml`) | 3.12 | PDF → Markdown extraction. On Linux it pulls CUDA 13 torch for the team's GX10 (ARM64, GB10); it also adds easyocr, rapidfuzz, pypdf |

```bash
uv sync                                   # root environment
uv run python -m pytest                   # all tests (offline; none need Neo4j)
uv run python -m pytest tests/schema/test_rejections.py::test_rejected   # one test

uv run python -m kg.load.seed --check     # validate concepts/ without a database
uv run python -m kg.load.seed --counts    # node/relationship counts, no writes
uv run python -m kg.load.seed             # id constraints + MERGE concepts/ into Neo4j
uv run python -m kg.registry              # validate registry/ and check each PDF's sha256
uv run python -m kg.load.sources          # MERGE Source nodes and SUPERSEDES edges
uv run python -m kg.convert source:tnau_agriculture_2020                # full Docling conversion (cached)
uv run python -m kg.convert source:tnau_agriculture_2020 --pages 13-76  # trial run on a page range
uv run python -m pytest -m slow           # the real 2-page conversion test (skipped by default)
uv run python -m kg.segment source:tnau_agriculture_2020   # section units -> data/units/<id>/ (exit 1 on scope failures)

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
- `kg/convert` does that conversion (see "Conversion" below). The full book is meant to run on the GX10.

**Heading structure is not in the heading levels.**
- 96–99% of Docling headings come out at level 1, depending on the book. The section hierarchy ("1.8.3.1.Seed rate") is only in the heading text.
- Numbering spacing is inconsistent, and some headings run into body text ("1.1.1. Wet nursery Nursery area").
- Unnumbered sub-headings ("Nutrient management") belong to the previous numbered heading.

**Page numbers are PDF page numbers, not printed page numbers.** The TNAU rice chapter starts at PDF p. 13, but the book's contents table says p. 1.

**`out/` (per-crop Markdown from the old `extract.py`) is not a pipeline input.**
- Its crop segmentation and page markers are known to be wrong.
  - In `tnau_agriculture`, the rice chapter is interleaved with false `carnation`, `banana` and `fieldpea` segments (`out/segmentation_report.md`).
  - Page markers follow headings only.
  - The files append "Other mentions" from unrelated chapters.
- Use it only as a cross-check or for reading. Extraction units come from `kg/segment`.

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
  convert/           Docling → DoclingDocument JSON in data/docling/<source_id>/ (gitignored)
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
  - The rice and wheat crop rows are approved; their labels are still needs_review.
  - Fertilizer percentages with `review_status: needs_review` must not be used by the alternatives check until approved. All four seeded fertilizers are needs_review.

## Source registry (`registry/`)

- **One TOML per book,** named after its ID (`registry/tnau_agriculture_2020.toml` ↔ `source:tnau_agriculture_2020`). The model is `kg/registry/model.py`.
- **`extraction/sources.toml` stays as it is.**
  - Carried over: title, publisher, url, language, rights_note, doc_type, note, OCR settings, page_range and crop (the last four in `[extraction]`).
  - `year` became `edition_year` + `edition_label`.
  - `region`, `include` and `season` were not carried.
- **`file` is the local path** and must match `sha256`.
  - The TNAU guide points to `data/raw/AGRICULTURE.pdf`.
  - The identical copies in `BooksData/` and `sources/pdfs/` serve the two extraction scripts.
  - A missing file fails validation; the error gives the URL to download from.
- **Validation fails on:**
  - a missing field;
  - an unknown or malformed region ID, or one outside the book's state;
  - a sha256 mismatch;
  - an unregistered `supersedes`;
  - a file name that doesn't match the ID;
  - `edition_year` not being the start year of `edition_label`.
- **What reaches the graph:** Source nodes and `SUPERSEDES` edges. Extraction settings and scopes stay in the registry.
- **`default_scope` rules and `section_scope` overrides** carry `status` (`proposed` | `approved` | `rejected`); only approved ones are used.
  - Sections are keyed by heading text plus PDF page range, because heading levels are unreliable.
  - Once segmentation exists, a section that matches zero units or more than one must fail loudly. Until then, `kg.registry.heading_matches` checks each section against the committed conversion.
- **TNAU:**
  - 2 approved default-scope rules, both section-scoped: per ha unless stated, p. 63; nursery area 800 m² per ha, p. 62.
  - 11 proposed section scopes, in integrated farming systems, agrometeorology and sorghum.

## Conversion (`kg/convert`)

- **Setup:** Docling 2.140.0 with EasyOCR and accurate TableFormer, ported from `extraction/extract.py` (`extraction/` itself is untouched).
- **Settings come from the registry entry's `[extraction]` table,** never from `sources.toml`.
  - `ocr = "auto"` uses `OcrMode.DEFAULT`: OCR runs only on layout regions without PDF text cells.
  - `ocr = "force"` uses `OcrMode.FULL_PAGE`.
- **Output in `data/docling/<source_id>/` (gitignored):**
  - `document.json`: the lossless DoclingDocument, with pictures as PNGs in `images/`;
  - `document.md`: a readable copy, one block per page, with `<!-- PDF p. N | printed p. M -->` markers and running headers removed;
  - `meta.json`: versions, settings, sha256, cache key, timing and OCR pages;
  - `report.json`.
- **Cache:** a run is skipped if `meta.json` has the same cache key (sha256 + Docling package versions + settings). `meta.json` is written last, so an interrupted run never counts as cached. `--force` re-runs anyway.
- **Trial runs** (`--pages a-b`) write to `trial_p<a>-<b>/` and never replace the full conversion.
- **The running-header filter** applies to the Markdown copy and segmentation only; the JSON is never filtered.
- **Tables are referenced as `table_ref = "#/tables/N"`** (the Docling `self_ref`).
- **Page numbers:**
  - `pdf_page` is always set.
  - `printed_page` comes from the registry's `printed_pages` runs (printed = PDF page − offset) and is null outside them.
  - The TNAU PDF has no embedded page labels; its runs were found from the printed number at the top of every page.

## Segmentation (`kg/segment`)

No LLM. Input: the full `document.json`, with running-header headings dropped.

**Chapters**
- They come from the registry's `chapters` list (63 entries drafted from the contents table, PDF pp. 3–5).
- A chapter starts on its PDF page. Its own heading there ("1. RICE (Oryza sativa L.)") is its title, never a section number.
- Segmentation uses every chapter for boundaries; extraction uses approved chapters only.

**The tree is rebuilt from heading numbers,** never from Docling heading levels.
- `1.8.3.1` nests under `1.8.3`. "1.8.3.1.Seed rate" is split into number and title.
- Each scheme (`1.`, `I.`, `A)`, `ii)`/`i.`, `a)`/`a.`) nests in the order it first appears in its context, e.g. "II. NURSERY PRACTICES" > "1. NURSERY PREPARATION".
- A child that arrives before its parent creates a placeholder, which the late parent fills.
- Body text like "4.11.Disease management: …" is promoted to a heading when its parent number exists.

**Unnumbered headings are inline sub-headings** of the numbered section above. Each item records its `subheading`. ALL-CAPS headings are the exception:
- right after another heading it shares a word with, a caps heading is that heading's subtitle ("1. TRANSPLANTED PUDDLED LOWLAND RICE" → "TRANSPLANTED RICE");
- otherwise it starts a major section at chapter level;
- numbering continues across a major section ("3." goes next to "2." even with "RAINFED RICE" in between).

**Heading fixes:** only `status = "approved"` `[[heading_fix]]` entries are applied (`match` + `pdf_page` → heading + inline sub-heading or sub-section).

**Units**
- One unit per leaf section, plus an "intro" unit for a section with its own text before its first child.
- Fields:
  - `id = unit:<slug>:<hash of section_path and kind>`;
  - `source_id`, `chapter`, `section_path`;
  - `items` in order (ref, label, kind, text, `pdf_page`, `printed_page`, `subheading`);
  - `table_refs`, `picture_refs`, `pdf_pages`;
  - `regions` with origin `source`, or `section` from an approved section scope;
  - approved `default_scope` rules;
  - `approx_tokens` = characters ÷ 4, tables included. Units over 20,000 are flagged, which leaves headroom under the 64k request limit.
- No table stitching or pivoting here; that's step 8.

**Scope check:** every `section_scope` and every `default_scope` section, proposed or approved, must match exactly one section node (heading text equal, start page in range). Its rules apply to every unit under that section. A mismatch writes the outputs, prints FAILED and exits 1.

**Output:** `data/units/<source_id>/units.jsonl` and `report.json` (gitignored). The report lists:
- the largest units and units without text;
- headings that didn't parse;
- numbering gaps, placeholders, late parents, duplicate numbers, promotions;
- heading-like list items;
- every caps decision;
- items before a chapter heading, and chapters whose heading wasn't found;
- the scope checks.

## Scope rules for extraction and normalisation

- **The p. 63 per-ha rule applies only to its section.** Elsewhere, a dose with no stated basis gets `basis_inferred: true` and goes to review.
- **Exclusions ("other than Cauvery Delta", p. 34)** are recorded by the extractor as `excluded_regions` with their raw text.
  - Code, never the LLM, expands them into `IN_REGION` edges to the state's remaining zones, with `origin: text_exclusion`.
  - Such facts are needs_review.
- **Sub-zones with no concept** (old delta, new delta, "Western region") are not mapped. Scope the fact at the state level, put the phrase in `unmapped`, and set it to needs_review.

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
9. **`default_scope` is a list of rules,** each optionally section-scoped. The Source node stores the approved rules as text; the registry holds each rule's quote, page and section.
10. **Exclusions.**
    - A Recommendation can carry `excluded_regions` (`{id, raw}`).
    - `RegionOrigin` gains `text_exclusion` for the edges code expands from them.
    - A fact with an exclusion must be needs_review, and an excluded region can't also be in its regions.

Decisions on gaps that don't change the doc:
- `sowing_date`, `variety` and `purpose` are in the condition-variable registry only for their `on_unknown` policy. Applicability to a variety or purpose is always an edge.
- `soil_pH` is the only soil value variable; add others when a source needs them.
- Every NutrientDose step has `APPLIES` quantities, and a ControlMeasure has at least one Step.
- `CONFLICTS_WITH` is recorded on both facts. Conflict detection must never create duplicate links: one link per pair of facts, however often detection runs.

## Known issues for segmentation and tables (steps 6–7)

These were found in the committed TNAU conversion while building the schema tests.

- **Fixed: rice seed sub-headings missing on pp. 74–75.**
  - The old conversion's filter had deleted them.
  - The new conversion keeps "Harvesting", "Threshing", "Drying", "Pre-storage seed treatment" and "Storage", and segmentation records them as each item's `subheading`.
  - The schema test examples still use the chapter heading as `section_path`.
- **Reported, not fixed: the grain-drying sentence on p. 39.**
  - "Dry the grains to 12% moisture level for storage." follows the list items "Insect management: See Crop Protection Chapter", "Disease management: …" and "Harvesting". These look like the lost sections 1.3–1.5.
  - Segmentation reports both the gap (1.3–1.5 missing under "1. TRANSPLANTED PUDDLED LOWLAND RICE") and the heading-like list items. Until a `heading_fix` from the printed book (printed p. 27) is approved, the sentence sits in the "1.2.5. Water management" unit.
- **Fixed: `table_ref`.** The new conversion gives every table a `#/tables/N` ref. The ETL table is two parts (p. 63 and p. 64), to be stitched in step 8.
