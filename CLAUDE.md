# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project rules

- docs/schema_v1.2.md is the source of truth
  - Schema changes go in a new versioned file in this repo (`docs/schema_v1.3.md`, ...) and are committed.
  - The Claude Doc is a superseded draft and is never exported again. `docs/schema_v1.1.md` is kept for history.
- use uv add for dependencies
- always MERGE on id; nothing is auto-corrected
- every number keeps its raw text; the LLM never converts units
- every fact needs a SourceSpan and an IN_REGION edge
- secrets come only from .env
- never create concepts automatically
  - The one sanctioned exception: Variety records pivoted from a book's variety tables (`kg/tables`). They are always needs_review, and facts linked to an unapproved Variety are needs_review too.
- new PDFs are never committed (books are recorded by URL and sha256 in the source registry instead)

## What this repo is

CropBot is a farm-advice bot. This branch builds its Neo4j knowledge graph: every agronomic fact becomes a `Recommendation` node with applicability edges, ordered Steps, runtime Conditions and a `SourceSpan` quote (see `docs/schema_v1.2.md`). The stages are defined in the schema's "Build pipeline" section: register → convert → segment → tables → extract → normalise → validate → verify (Jev) → load. Product context (post-harvest focus, pilot plans) is in `CropBot_Research_Brief.md`.

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
uv run python -m kg.tables source:tnau_agriculture_2020    # rice + wheat tables -> data/tables/<id>/, data/review/tables.csv
uv run python -m kg.extract report source:tnau_agriculture_2020   # extraction checks (see "Extraction")
uv run python -m kg.normalize source:tnau_agriculture_2020        # step 10 -> data/normalized/<id>/, data/review/proposed_concepts.csv
uv run python -m kg.validate source:tnau_agriculture_2020         # step 11 -> data/validated/<id>/, data/review/validation.csv
uv run python -m kg.verify source:tnau_agriculture_2020 --dry-run # step 12: claims and request sizes, sends nothing
uv run python -m kg.verify source:tnau_agriculture_2020           # step 12: asks Jev what is not answered yet

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

## Schema models (`kg/schema`)

- **Subtypes:** all 16 are modelled. The 9 first-slice subtypes and the other 7 from the v1.2 table (SeedRate, Spacing, SeedTreatment, IrrigationRule, DoseFormula, WeatherRule, QualitySpec) are in `ALL_SUBTYPES`/`FACT`.
- **Concept models:** Pest, Disease, Weed, ActiveIngredient (`reg_status` defaults to unknown and comes only from the CIB&RC list) and OrganicInput are modelled.
  - Their rows are drafted in `concepts/proposed/` (`PROPOSED_FILES`) and are not loaded until approved.
  - Fertilizer keeps `n_pct`, `p2o5_pct` and `k2o_pct` as properties. The schema's `other{}` (Zn, Fe, S, …) is stored as `(:Fertilizer)-[:CONTAINS {pct, raw}]->(:Nutrient)` edges. In the seed CSV it's the `contains` column, a JSON list of `{nutrient_id, pct, raw}`. Rows with TODO percentages are pending and get no edges.
- **Neo4j properties are never maps**, only primitives or flat arrays.
  - Anything map-shaped becomes edges, or flat properties when that's decided: `raw{}` → `raw_<field>`, `coefficients{}` → `coef_<name>`, Variety `cells{}` → opaque `cells_json` (all built in step 13).
  - A concept's `edges()` gives (relationship, target label, target id, relationship properties) for the loader.
  - The loader refuses a node whose properties aren't primitives.
  - The loader MERGEs every node and edge and reports what each run created; a second run creates nothing.
- **`per_cent_nursery`:** value is the amount per one cent of nursery, and `area_cents` is the nursery area the source stated. "40 kg DAP per 20 cents" is value 2, area_cents 20.

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
- **`concepts/proposed/`** is for drafted rows awaiting review. They validate against the models (`PROPOSED_FILES`) but are not loaded and not used for linking until they're approved and moved into `concepts/`.
- **Step 10 rows** (approved 2026-10-20) are now in `concepts/`, all needs_review: 18 pests, 53 active ingredients, 7 organic inputs and their labels.
  - Active ingredients keep `reg_status: unknown`, which comes only from the CIB&RC list.
  - `name_en` uses the standard spelling, and the book's spelling is a label (chlorpyriphos, Tricyclozole, bromodialone, ethopenprox). The brand label Bavistin → carbendazim and "clayey soils" → `soil:clay` are approved.
  - Dicofol has no `use_class`, since there is no acaricide value.
  - Labels approved later the same day: "Hispa/ spiny beetle" → hispa, "Earhead bug" → earhead bug, "saline soil condition" → `soil:saline`. "saline / sodic soils" is one label text on both `soil:saline` and `soil:sodic`; for soils, systems and seasons such a shared label links to all its concepts (`link_many`). Single-valued links still treat it as ambiguous.
  - Kept held by decision: "Zinc deficient soils", "direct sowing", "ADT 46", "synthetic pyrethroids".
  - Earhead bug's `scientific_name` is the book's wording, "Leptocorisa acuta and L. oratorius", so its table cell links.
  - ZnSO4/FeSO4 and their labels are TODO, pending their nutrient percentages from an official source.
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
  - 11 proposed region section scopes, in integrated farming systems, agrometeorology and sorghum.
  - 1 approved purpose section scope: "RICE - VARIETAL SEED PRODUCTION" (PDF pp. 73-75), `purposes = ["purpose:seed"]`. It quotes the heading on the rendered p. 73, so its units carry `purpose:seed` with origin `section`.
- **A `section_scope` has `regions`, `purposes` (`purpose:<id>`) or both.** A purposes-only scope leaves the unit's regions alone. Units carry `purposes` with origin `section`, and the model never sets a section-level purpose.

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
- Segmentation uses every chapter for boundaries; extraction uses approved chapters only. RICE and WHEAT are approved (checked against the rendered contents table and chapter pages); the rest are proposed.

**The tree is rebuilt from heading numbers,** never from Docling heading levels.
- `1.8.3.1` nests under `1.8.3`. "1.8.3.1.Seed rate" is split into number and title.
- Each scheme (`1.`, `I.`, `A)`, `ii)`/`i.`, `a)`/`a.`) nests in the order it first appears in its context, e.g. "II. NURSERY PRACTICES" > "1. NURSERY PREPARATION".
- A child that arrives before its parent creates a placeholder, which the late parent fills.
- Body text like "4.11.Disease management: …" is promoted to a heading when its parent number exists.

**Unnumbered headings are inline sub-headings** of the numbered section above. Each item records its `subheading`. ALL-CAPS headings are the exception:
- right after another heading it shares a word with, a caps heading is that heading's subtitle ("1. TRANSPLANTED PUDDLED LOWLAND RICE" → "TRANSPLANTED RICE");
- otherwise it starts a major section at chapter level;
- numbering continues across a major section ("3." goes next to "2." even with "RAINFED RICE" in between).

**Registry fixes**, applied only when `status = "approved"`. Each is checked against the rendered PDF page before approval. Its text must be found **exactly once** on its `pdf_page`; otherwise segmentation stops with every problem listed and writes nothing.
- `[[heading_fix]]` `kind = "split"` (default): the heading `match` becomes `heading`, plus an inline sub-heading or a sub-section. A numbered sub-section ("I. SEASON AND VARIETIES") is placed by the numbering rules.
- `[[heading_fix]]` `kind = "restore"`: an item whose number Docling dropped (often a list item) becomes the heading as printed, e.g. "Harvesting" → "1.5. Harvesting". The heading must be a number followed by `match`.
- `[[reading_order_fix]]`: the items `first`..`last` on `pdf_page` move to just after `after`.
- `[[acknowledged_gap]]` (no status; added after checking the page): a numbering gap the book really prints, e.g. wheat has no "1." before "2. Morphological Description of COW(W) 1". It matches only the same chapter, section heading and missing numbers. The report lists it under acknowledged gaps, not open ones, and lists any entry that matches no gap as stale.

**Units**
- One unit per leaf section, plus an "intro" unit for a section with its own text before its first child.
- Fields:
  - `id = unit:<slug>:<hash of section_path and kind>`;
  - `source_id`, `chapter`, `section_path`;
  - `items` in order (ref, label, kind, text, `pdf_page`, `printed_page`, `subheading`);
  - `table_refs`, `picture_refs`, `pdf_pages`;
  - `regions` with origin `source`, or `section` from an approved section scope;
  - `purposes` (origin `section`) from an approved section scope, empty otherwise;
  - approved `default_scope` rules;
  - `approx_tokens` = characters ÷ 4, tables included. Units over 20,000 are flagged, which leaves headroom under the 64k request limit.
- No table stitching or pivoting here; that's step 8.

**Scope check:** every `section_scope` and every `default_scope` section, proposed or approved, must match exactly one section node (heading text equal, start page in range). Its rules apply to every unit under that section. A mismatch writes the outputs, prints FAILED and exits 1.

**Output:** `data/units/<source_id>/units.jsonl` and `report.json` (gitignored). The report lists:
- the largest units and units without text;
- headings that didn't parse;
- open numbering gaps, acknowledged and stale acknowledged gaps, placeholders, late parents, duplicate numbers, promotions;
- heading-like list items;
- every caps decision;
- items before a chapter heading, and chapters whose heading wasn't found;
- the scope checks.

## Tables (`kg/tables`)

No LLM. Rice and wheat chapters only for now (`--chapters`). Input: the full conversion plus `units.jsonl`.

**Merged cells:** rows are built from Docling's unique `table_cells`, so a cell spanning columns appears once with its `col_span`. Genuine repeats ("Straw | Straw | Straw") are separate cells and stay. The original cells are kept per part.

**Stitching**, within a unit. B continues A when:
- B is on the next page;
- only tables lie between them;
- the widths match (equal grid widths, or equal merged widths when one part splits the label column).

Then:
- a first cell "Particulars" always starts a new table;
- a repeated header is dropped;
- otherwise B's first row is data, even if Docling flagged it a header;
- a "Particulars" row *inside* a table splits it, because Docling sometimes puts the end of one variety table and the start of the next in one table.
- a row split by the page break leaves B's first row with no first-column cell, or an empty one. It is merged into A's last row cell by cell in the same column, and only when every cell has a same-column cell to continue.
  - The merged cell keeps the piece in `continued_from`; the merge is logged and written to review as "row continued across page break".
  - Extraction renders such a row as `[#/tables/A row R + #/tables/B row S]`, and a quote in it records the pages of all its pieces.
  - Rice/wheat: 10 merges, among them hispa (`#/tables/56` r4 + `#/tables/57` r0) and WBPH (`#/tables/57` r4 + `#/tables/58` r0). Nine Variety traits are completed by them, e.g. "Seed source: Seed centre, TNAU," becomes "… TNAU, Coimbatore-3".

**Page check, per part, with docling-parse** (the same text layer Docling read):
- rows must equal the bands between horizontal rulings;
- each row must show the full grid width or the merged cell count;
- a merged cell must not have a vertical ruling inside it;
- each cell's text must equal the page words inside its box. Same words in a different order (superscripts, stacked lines) is counted, not flagged.

A part without rulings is "not verifiable". Every mismatch goes to `data/review/tables.csv`; nothing is corrected.

**Variety pivot:** a table headed "Particulars" gives one Variety per column. Values are aligned to the last N columns of each part.
- Mapped rows fill typed fields, with numbers keeping their `raw` text.
- Known descriptive rows become traits "Label: value".
- "Grain size (mm)" prefixes Length, Breadth and Thickness.
- Unmapped, empty, straddling or spanning cells go to review, and a spanning value is never copied to several varieties.
- IDs are `variety:<slug of the name as written>`. Possible duplicates are reported, never merged; merging and aliases are a human review decision.
- `kind = hybrid` only when the name says so.
- `duration_group` comes from the section heading. Varieties whose duration is nearer another group's reference are reported; the reference values come from the book's "Stages | Short (105) | Medium (135) | Long (150)" table.
- `crop_id` comes from the chapter entry, and only once the chapter is approved.

**COW(W)1 block (PDF p. 134):**
- The printed page has it inside "I. SEASON AND VARIETY", after the "3. WHEAT" heading. Docling read it before the heading.
- An approved `[[reading_order_fix]]` restores the order. Its table is pivoted (COW (W) 1, COW (W) 2), and each is flagged "Docling reading order: …" for review.
- Its text lines are listed in the report as context for step 9.

**Damaged by conversion (rice, pp. 23–26):**
- "Imp. White Ponni ADT (R) 46" is one name cell holding two varieties;
- `#/tables/23` merges two varieties' values into one cell across a ruling;
- CO 52's morphology rows straddle columns.

All of these are in review. Re-entering them by hand, or reconverting, is a review decision.

## Extraction (`kg/extract`)

No model is called from this repo. `prepare` writes the filled prompt, a runner answers it, and `ingest` checks and stores the answer:

```bash
uv run python -m kg.extract find    source:tnau_agriculture_2020 "Wet nursery"          # unit ids
uv run python -m kg.extract prepare source:tnau_agriculture_2020 --unit <unit_id> --model <name> [--prompt v2]
uv run python -m kg.extract ingest  source:tnau_agriculture_2020 --unit <unit_id> --model <name> --response <file>
uv run python -m kg.extract report  source:tnau_agriculture_2020 [--prompt v2]
uv run python -m kg.extract compare source:tnau_agriculture_2020 --unit <unit_id> --from v1 --to v2
```

`--prompt` defaults to the latest version (v2).

- **Raw model** (`kg/extract/model.py`), separate from `kg/schema`:
  - all 16 subtypes with the v1.2 fields;
  - names, units and bases as printed ("DAP", "kg", "per 20 cents"), never IDs or canonical units, and numbers parsed with their printed text. Step 10 normalises and links.
  - Extra fields: `basis_inferred`, `basis_rule`, `quantity_ref`, `alt_*`, `condition_raw`, `unmapped`, `excluded_regions` {name, raw}, and one `quote` per fact.
  - A step's `operation` may be empty when no type fits.
  - A quantity's `basis` may be empty when none is printed and the section gives none.
  - Crop and the book's regions come from code, never the model.
- **Prompts** `kg/extract/prompts/v1.md` and `v2.md`, model-agnostic. `kg/extract/versions.py` says what each version's answer looks like, so stored v1 answers still check as v1.
  - Code fills `{{subtypes}}`, `{{vocabularies}}` (from `kg/schema/vocab.py`), `{{default_scope}}` (approved rules with their quotes) and `{{unit}}`.
  - Units are rendered as `[p.N] text`, `[p.N] ## Sub-heading`, and stitched tables as `[#/tables/N row R] cell | cell`. A row merged across a page break is `[#/tables/A row R + #/tables/B row S]`.
  - A test fails if a prompt's field reference and its version's fields disagree.
  - Never edit a prompt that has been used: make a new version.
- **v1:** a JSON list of facts; every step has `instruction_en`.
- **v2:**
  - **Envelope:** `{"facts": [...], "not_extracted": [{quote, reason}]}`, and every text line and table row must be quoted by a fact or listed (the coverage check).
  - **Flags:** `extraction_flags` from a fixed list: line_order_pairing, spans_table_rows, split_from_shared_line, shared_amount, target_from_heading, anchor_from_context.
  - **Table quotes:** a quote may be a passage within one cell.
  - **Purpose:** `purposes` only when the quote states what the produce is for. Seed before sowing is planting material, not a purpose, and a section's purpose comes from the registry.
  - **Numbers and units:** unit "count" for organisms, eggs or items with no printed unit; Indian digit grouping ("1,00,000" = 100000, `kg/extract/numbers.py`) with `raw` as printed.
  - **instruction_en:** no longer written by the model; code writes it later.
- **Output** `data/extracted/<source>/<prompt version>/<hash>.json`, plus `prompts/` and `responses/` there (all gitignored). Unit IDs contain ':', so files are named by the hash.
  - Each file records the prompt version and sha256, `extraction_model`, the unit text sha256, the time, the raw answer, every fact and its check results.
  - Cache key: unit text + prompt version + prompt hash + model.
  - `ingest` refuses to replace an answer with the same key unless given `--force`.
  - Runs under different versions sit side by side. A new run of the same unit and version moves the earlier answer to `<version>/history/<hash>.<cache key[:12]>.json`, recorded as `previous_run`; nothing is overwritten. `prepare` does the same for an earlier prompt with a different key (`history/<hash>.<key[:12]>.md`; the key sits in `prompts/<hash>.key`).
  - `compare --from/--to` takes a version (its latest run) or a run file. It matches facts by subtype and quote (then by one quote containing the other) and ignores `instruction_en`. Runs are labelled `<version>@<cache key[:8]>`.
- **Hand-runs:** the JSON answer is written directly from the rendered prompt; no template generates any field.
- **Checks here only:**
  - the answer parses into the raw model under its version, fact by fact;
  - each fact and not-extracted quote is found in the unit text after both are normalised (NFKC, soft hyphens, dashes, whitespace);
  - (v2) no text line or table row is left uncovered. Sentences outside every quote are listed as a warning only.
  - Code, not the model, finds the quote's page.
  - Failures are saved and reported, never fixed, and `ingest`/`report` exit 1.
  - Everything else is step 11.
- **Step 11 (validate, not built yet) must also:**
  - send every fact with `extraction_flags` to needs_review;
  - flag a quote found in more than one place in its unit. "Narrow bund maintenance (45 x 30 cms)" appears in both the rat row and the IPM module, so the location can't be told apart.
  - check a fact's `table_ref`/`table_row` against where its quote was found;
  - check numbers in quotes with `kg.extract.numbers` (Indian grouping included), plus vocabularies, alternatives and the banned list.

## Normalisation and linking (`kg/normalize`)

No model. Input: the latest v2 run of every unit (a run that failed step 9 stops it). Each raw fact either validates against `kg.schema.FACT` and goes to `data/normalized/<id>/facts.jsonl`, or is held in `held.jsonl` with every blocking reason. Nothing is forced or dropped.

- **Scope:**
  - **Crop:** the chapter's crop_id, only if the chapter is approved.
  - **Regions:** the unit's, with their origin. Text regions are linked; "other than X" is expanded by code into the state's other zones (`text_exclusion`).
  - **Purposes:** from the quote (origin text), merged with the section's (origin section). The origins are kept beside the fact (`purpose_origins`), because v1.2's FOR_PURPOSE has none.
- **Units and bases:** `kg/normalize/units.py`, code only. Every conversion is logged with its rule.
  - acre = 0.404686 ha, cent = 1/100 acre, quintal = 100 kg.
  - Nursery cents give `per_cent_nursery`: value per cent, `area_cents` as stated.
  - A bare "/kg" in a seed treatment, and "for one hectare", are read from context and send the fact to review.
  - `basis_rule` must be one of the unit's approved default-scope rules.
- **`quantity_ref`:** copied from the one earlier fact of the unit that gives the same target an amount, with `inherited: true`; zero or several such facts hold it. A fact inheriting from a held fact is held too (chains included) until its source validates.
- **Linking** (`kg/normalize/link.py`): exact canonical label, then an alias label, then a normalised match on name, slug and labels.
  - Last, for concepts with a `scientific_name`: a table cell that is exactly a known name (`name_en` or a label) followed by that scientific name, both normalised ("Stem borer Scirpophaga incertulas"). Anything else in the cell goes to review.
  - Nutrient symbols match exactly; "P" and "K" follow the NPK convention (p2o5, k2o) and go to review.
  - Generic targets ("Pest", "weeds", "rodent") don't link.
  - No embeddings yet (BGE-M3 isn't set up).
  - Unlinked names are listed in `data/review/proposed_concepts.csv`; no concept is ever created.
- **Held:** a fact is held for:
  - an unlinked required name or applicability (variety, season, system, soil, purpose, stage), since dropping the edge would widen the fact's scope;
  - a step with no operation;
  - a unit or basis with no canonical form;
  - a threshold sampling unit outside `Basis`;
  - a `fact_key` collision within the unit.

  An unlinked *step* or *clause* stage keeps its words in `timing_raw`/`raw`, and the fact goes to review.
- **`fact_key`:** a hash of the source, section path, subtype, linked applicability, identity, step slots (order, alt group, option, operation, target IDs) and the quote's first passage ref. Values are excluded.
  - Identity covers pests, targets, kind, concerns, control class, dose basis, DryingSpec `storage_term_raw`, and every condition of the fact (variable, op, raw).
  - There is no sentence position; facts that still collide stay held. `id` is `rec:` plus a hash of the key and the values.
- **Status:** needs_review for any of:
  - an extraction flag;
  - basis_inferred, or a basis read from context;
  - an inherited amount;
  - an exclusion;
  - a needs_review concept or label;
  - the NPK convention;
  - an unlinked stage.

  Otherwise `extracted`; never approved.
- **Code-written fields:** `instruction_en` is written by code. `SourceSpan.extraction_method` is `table_parse` for table facts, `ocr` on OCR pages, else `native_text`; `bbox` is not filled yet.

## Validation (`kg/validate`)

No model. Input: the facts step 10 validated (`data/normalized/<id>/facts.jsonl`) and the step 9 runs they came from. Each check returns pass, fail or skip with a reason.
- **Rules:** a failure only adds a review reason. `extracted` becomes `needs_review`; nothing is fixed and nothing becomes approved (step 12, Jev, decides `auto_verified`).
- **The checks:**
  1. **quote_location:** the quote is found exactly once in its unit, and `table_ref`/`table_row` is where it was found. Either piece of a merged row counts.
  2. **raw_numbers:** on the step 9 fact (printed values, before conversion), every raw text is in the quote and every number is printed in its raw text. Indian grouping and number words up to twelve count; interpretations such as "a week" = 7 fail.
  3. **value_ranges** (approved 2026-10-20):

     | Field | Range |
     |---|---|
     | Harvest moisture | 10–30 % |
     | Threshing moisture | 10–25 % |
     | Drying target, storage max moisture | 5–20 % |
     | Storage months | 0–60 |
     | Offsets | ±180 days, ±72 hours |
     | depth_cm | 0–20 |
     | Nutrients `per_ha` | ≤ 500 kg |
     | Fertilizers `per_ha` | ≤ 1000 kg |
     | Organic inputs `per_ha` | ≤ 25 t |
     | `per_kg_seed` | ≤ 20 g or ml |
     | `per_cent_nursery` | ≤ 50 kg (organic inputs ≤ 100 kg) |
     | Active ingredient per ha | ≤ 3 kg a.i. (dose × formulation %, ml read as g) |

     A dose with no formulation % is skipped with that reason.
  4. **alternatives:** fertilizer-only alternatives agree within 15 % on N, P2O5 and K2O, using **approved** Fertilizer percentages only. Without them it skips with a review reason.
  5. **ingredients:** every applied active ingredient must be `registered`; unknown, restricted, banned and not seeded all fail (fail closed). A Caution's `concerns` aren't checked.
  6. **review_kept:** a fact with flags, an inferred or context basis, an inherited amount, an exclusion or any step 10 review reason must be `needs_review`.
  7. **range_narrowed:** a value stored as one bound (or equal bounds) that is an end of a range printed in its raw text fails with "printed range stored as a single bound (pending v1.3 min_moisture_pct)". It covers every raw field, quantity, step offset and condition, and the value is never changed. TNAU: rice seed storage "12 - 13 %" and "8 - 9 %" (C2#22, #23), stored as `max_moisture_pct` only.
- **Review notes:** `[[review_note]]` in the registry is printed text on a PDF page plus a note, with a status.
  - Step 11 attaches an approved note to every fact whose quote contains that text on that page, as a review reason; the value never changes.
  - An approved note that matches no fact is reported as stale.
  - TNAU: the Fipronil note (p. 64) is approved. The two Imidacloprid notes (pp. 66, 67) are approved: "inconsistent units for the same product in the source: g/ha on pp. 287–288, kg/ha on pp. 66, 67 and once on p. 288".
  - A quote in a row merged across pages records every piece's page (step 9), so the WBPH row (pp. 66–67) matches both Imidacloprid notes. Identical note text is listed once per fact.
- **Known source typos** (checked on the rendered pages 2026-10-20): "Fipronil 80%WG 50- 62.5 kg" (PDF p. 64) and "Imidacloprid 70% WG 30-35 kg" (pp. 66, 67) are printed in kg. The same Fipronil product is printed as "50-62.5 g" on p. 65. Extraction and normalisation keep the book's kg, check 3 fails them, and they go to review as suspected typos.

## Verification with Jev (`kg/verify`)

Input: the step 11 facts (`data/validated/<id>/facts.jsonl`). The URL and model are read from `docs/jev_example.md`; the key comes from `BEATAPI_API_KEY` in `.env` and is never printed or stored.
- **Claims** (`kg/verify/claims.py`) are built by code from the stored fields; no model writes them.
  - One yes/no claim per step and value, per threshold clause, per moisture, months or depth field, and per ingredient a Caution concerns.
  - Amounts are restated in the book's terms: `per_cent_nursery` becomes value × `area_cents` "per 20 cents of nursery".
  - Wording follows the book:
    - names are as printed, read from the step 9 fact ("super phosphate", "chlorpyriphos", "N"), never `name_en`. Applicability lead-ins (purpose, soil, variety) still use concept names.
    - a condition with raw text is rendered by that text ("in the absence of predatory spider").
    - "at most", "below", "at least" and "more than" appear only when the field's printed raw has a bound word, and the inclusive flag picks which. "12%" is "to 12%".
    - a step's `condition_raw` covering several products, or a fallback option, stays with the whole step: "the alternative to DAP, if not readily available, is urea 16 kg and super phosphate 120 kg per 20 cents of nursery".
  - Timing comes from anchor and offsets, else the stored `timing_raw`. Applicability is a lead-in ("for medium duration varieties grown for seed").
  - Untimed steps fall back to "the advice includes <operation>: <method>".
  - A fact with no claim (the two cautions with no `concerns`, and the saline Spacing with no values) is marked "human review required: no code-built claim" and can never be auto_verified.
  - The key is `c_` + hash(fact_key + claim).
- **Controls:** 5 deliberately wrong claims, one number changed (×2, or +10 points for a percentage) on the first numeric claim of facts taken round-robin over units. Keys are `x_…`; they're excluded from scores and reported separately. Step 15 raises them to about 10 % of claims.
- **Requests:** one per unit, with the unit text exactly as step 9 rendered it as the state and all pending claims as `noul` questions (P(yes)).
  - A request is split only past an estimated 60k tokens (characters ÷ 4 × 1.2).
  - `--dry-run` writes `claims.jsonl` and sizes and sends nothing.
- **Queue and cache** (`data/verified/<id>/`, gitignored):
  - Answers are appended to `answers.jsonl` as they arrive, keyed sha256(unit text + claim + model). A re-run sends only unanswered claims.
  - 429, 5xx and timeouts back off (2, 4, 8, 16, 32 s, or `Retry-After` if longer), then stop with the queue kept.
  - The free tier (`jev-1.14-free`) answers 429 with `retry-after: 60` to a request sent soon after the previous one (first real run, 2026-10-20). Plan for about 1 request per minute.
  - Every try, 429s included, is logged in `requests.jsonl` and printed: HTTP status, latency, rate-limit headers, the names (never the values) of all response headers, and, once known, stored, usage, missing and extra keys.
  - Raw responses are stored only if they're valid JSON with no key or key-like string.
- **Per fact:** `verifier`, `verifier_score` (the lowest P(yes) of its non-control claims), and its claims with P(yes) and the response file.
- **Threshold:** `auto_verified_threshold` in `config/verify.toml` has **no default**. Without it nothing becomes auto_verified; calibration is step 15. With it, only an `extracted` fact with claims can become auto_verified; needs_review stays needs_review.

## Scope rules for extraction and normalisation

- **The p. 63 per-ha rule applies only to its section.** Elsewhere, a dose with no stated basis gets `basis_inferred: true` and goes to review.
- **Exclusions ("other than Cauvery Delta", p. 34)** are recorded by the extractor as `excluded_regions` with their raw text.
  - Code, never the LLM, expands them into `IN_REGION` edges to the state's remaining zones, with `origin: text_exclusion`.
  - Such facts are needs_review.
- **Sub-zones with no concept** (old delta, new delta, "Western region") are not mapped. Scope the fact at the state level, put the phrase in `unmapped`, and set it to needs_review.

## Schema v1.2

The eleven changes that were pending here (two page numbers, raw text for every number, condition-only units, strict bounds, hour offsets, editions, prefixed lowercase IDs, the worked-example fix, `default_scope` as a list, exclusions, table cells in provenance) are now in `docs/schema_v1.2.md` (see its "Changes from v1.1").

Decisions on gaps that don't change the doc:
- `sowing_date`, `variety` and `purpose` are in the condition-variable registry only for their `on_unknown` policy. Applicability to a variety or purpose is always an edge.
- `soil_pH` is the only soil value variable; add others when a source needs them.
- Every NutrientDose step has `APPLIES` quantities, and a ControlMeasure has at least one Step.
- `CONFLICTS_WITH` is recorded on both facts. Conflict detection must never create duplicate links: one link per pair of facts, however often detection runs.

Pending for schema v1.3. These were found in the step 9 hand-run; until v1.3 is written, extraction keeps the phrases in `unmapped`:
- StorageRule needs `min_moisture_pct` (+ `_inclusive`), so "12 - 13 %" keeps its lower bound (it has only `max_moisture_pct` now).
- Repeat schedules ("thrice (at weekly interval from 37 DAT)", "twice, 15 and 30 days after transplanting") have no fields.
- A Caution cannot name the pest it is about (the resurgence lists, p. 69: "BPH, Nilaparvata lugens : acephate, …").
- `Spacing.seedlings_per_hill` needs a range (min/max), for "Shallow planting at 3 - 4 seedlings / hill" (p. 74).

Found in step 10; until v1.3, normalisation holds the affected facts with the reason:
- OperationType has no values for release (parasitoids), trapping, baiting, dusting or bund work, and Step `operation` is required.
- APPLIES has no target type for inputs that aren't nutrients, fertilizers, organic inputs or active ingredients: seed, biocontrol agents (Trichogramma), traps, salts, chemicals (HNO3, KCl, NaCl).
- No concentration or ratio quantities: "%" with no basis, "0.1 N", "80 µM", "1 part … with 49 parts".
- ThresholdClause sampling units outside `Basis`: "/25 net sweeps", "/100 earheads", "in 12 passes".
- `FOR_PURPOSE` needs `{origin}` (text or section); normalisation keeps the origin beside the fact for now.
- ActiveIngredient `use_class` needs an `acaricide` value (Dicofol, PDF p. 67); until then `use_class` is empty.
- Soil-test conditions as applicability: "Zinc deficient soils" (PDF p. 74) is a soil condition, not a soil type. The fact stays held.
- ActiveIngredient groups: "synthetic pyrethroids" (PDF pp. 63, 68) names a class of ingredients, not one. The cautions concerning it stay held.
- GrowthStage seeds for rice, needed for stage timing: "flowering", "tillering stage", "boot leaf stage", "vegetative phase", "from milky stage to grain maturity". Today these stay only in `timing_raw`/`raw`, and the fact needs review.
- Properties are never maps: Neo4j rejects them, which the 2026-10-20 seed load showed.
  - `Fertilizer.other{}` is now `CONTAINS {pct, raw}` edges to Nutrient.
  - Decided 2026-10-20, to build in step 13 when the fact and Variety loaders exist:
    - `raw{}` on subtypes and Variety → flat properties `raw_<field>`;
    - DoseFormula `coefficients{}` → flat properties `coef_<name>`;
    - Variety `cells{}` → one JSON string property `cells_json`, opaque provenance that is never queried in Cypher.
  - The loader's primitive-property check stays, and each mapping gets a test.

Candidate for prompt v3: a flag `scope_from_heading` for applicability taken from a sub-heading rather than the quote. For example, the soil "saline soil condition" comes from the p. 74 sub-heading "Recommendation for planting under saline soil condition", and "Zinc deficient soils" comes the same way. v2 has no flag for this.

## Known issues for segmentation and tables (steps 6–7)

These were found in the committed TNAU conversion while building the schema tests.

- **Fixed: rice seed sub-headings missing on pp. 74–75.**
  - The old conversion's filter had deleted them.
  - The new conversion keeps "Harvesting", "Threshing", "Drying", "Pre-storage seed treatment" and "Storage", and segmentation records them as each item's `subheading`.
  - The schema test examples still use the chapter heading as `section_path`.
- **Fixed: the grain-drying sentence on p. 39.**
  - The printed page (printed 27) has "1.3. Insect management:", "1.4. Disease management:" and "1.5. Harvesting". Docling turned them into list items without numbers.
  - Approved restore fixes bring the headings back, so "Dry the grains to 12% moisture level for storage." sits in "… > 1. TRANSPLANTED PUDDLED LOWLAND RICE > 1.5. Harvesting".
- **Fixed: the same pattern on pp. 46, 49 and 51** (3.9 and 3.10, 4.10, 5.12). Approved restore fixes; rice has no open numbering gaps.
- **Fixed: wheat "I. SEASON AND VARIETY" sat under "CLIMATE REQUIREMENT".**
  - PDF p. 134 prints "CROP IMPROVEMENT" (centred), then "CLIMATE REQUIREMENT" (left) with its table and paragraph, then "I. SEASON AND VARIETY" (centred). Rice p. 13 has the climate block first.
  - An approved `[[reading_order_fix]]` moves "CROP IMPROVEMENT" after the climate paragraph, giving "WHEAT > CROP IMPROVEMENT > I. SEASON AND VARIETY". The caps-heading rule is not changed for one book.
- **Fixed: rice seed fertilizer lines on p. 74.**
  - The page prints "Medium duration : NPK @ 150:50:60 kg / ha" and "Long duration : NPK @ 150:50:80 kg / ha", one bullet per line. Docling read both labels before both values.
  - An approved `[[reading_order_fix]]` moves ": NPK @ 150:50:60 kg / ha" after "Medium duration", so the unit now has the printed order.
- **Fixed: `table_ref`.** The new conversion gives every table a `#/tables/N` ref. The ETL table is two parts (p. 63 and p. 64), to be stitched in step 8.
