# CropBot knowledge graph: handover

For teammates who haven't worked on the pipeline. The KG-building phase closed on 2026-10-24. This page says what is in the graph, how to get it on your machine, and how the agent asks it questions. Everything else (every decision, every number, every known problem) is in `CLAUDE.md`; the schema is `docs/schema_v1.6.md`.

## 1. What is in the graph (main database, 2026-10-24)

Snapshot `13c96aefbc1ee99265369282f5f0746446ef6a86795e24d319337855ff5c681d`: 842 nodes, 1,280 relationships (`uv run python -m kg.load.facts --snapshot` prints it; if the hash differs, the graph changed).

Every agronomic fact is a `Recommendation` node with a subtype label, applicability edges (crop, region, system, …), and a `SourceSpan` holding the exact quote, the PDF page and the source.

| Source | Region | Authority tier | Facts in the graph | Held (not loaded) |
|---|---|---|---|---|
| `source:tnau_agriculture_2020`: TNAU Crop Production Guide, Agriculture 2020 (rice chapter, 4 sections) | Tamil Nadu (`state:33`) | 1 (state university) | 113: 12 extracted, 101 needs_review | 11 |
| `source:dfpd_uniform_spec_kms_2026_27`: DFPD uniform specification, paddy, KMS 2026-27 (DFPD letter dated 17.08.2026) | national (`country:in`) | 0 (regulatory) | 18 QualitySpec, all **approved** | 0 |
| `source:gbpuat_kharif_advisory_2020`: GBPUAT Pantnagar, "Advisory for Kharif Season in Uttarakhand", dated 02.05.2020 (rice rows) | Uttarakhand (`state:5`) | 1 | 8, all **approved**: 2 VarietyRecommendation, 6 SowingWindow | 4 (Chetki Dhan, Jethi Rice) |

TNAU by subtype: ControlMeasure 44, NutrientDose 13, Caution 12, SeedTreatment 12, PestThreshold 8, IrrigationRule 6, HarvestRule 5, StorageRule 5, SeedRate 4, DryingSpec 3, Spacing 1.

The GBPUAT advisory is dated 02.05.2020 (the date in its URL's file name and its PDF metadata; the page itself prints no date). Its windows and varieties are for the 2020 kharif season and have not been checked against a newer advisory.

**Status.** Code sets `extracted` or `needs_review` (steps 10–12: needs_review whenever something about the fact needs a person's look; `auto_verified` would also come from code, but no threshold is set, so no fact has it). Only `approved` and `rejected` come from people, through the expert decisions file (`data/review/expert_decisions.csv`). `approved` facts are served as they are; `extracted` and `needs_review` are unreviewed (section 5). No TNAU fact has been reviewed yet.

**The three approved answers** (served with no warning label):
1. **Paddy procurement quality** (`quality_check`): the 18 DFPD limits for paddy, KMS 2026-27 (moisture at most 17 %, foreign matter, damaged grains, the substances paddy must be free from, …), for every state.
2. **Rice varieties for Uttarakhand** (`varieties_for`): 16 varieties for Tarai, Bhabhar & Plain; 8 for the irrigated hills (mid and high hills).
3. **Rice sowing and transplanting windows for Uttarakhand** (`sowing_window`): Tarai nursery 16 May – 7 June and transplanting 25 June – 7 July; irrigated mid hills nursery 1–15 May and transplanting 16–30 June; irrigated high hills nursery 16–30 April and transplanting 1–15 June.

## 2. Getting the graph on your machine

Dump shared at: <link>

The dump is `neo4j.dump` (345,278 bytes, sha256 `edd99b47c31d8c6127f48a137cc238ff2c263f008481c3193ae76f6a4ddaa9c9`), made on 2026-10-24 from the main database.

1. **Install Neo4j Desktop and create a local DBMS of version 2026.09 or newer.** Desktop's local DBMSs are Neo4j Enterprise under the developer licence, the edition this dump needs. The dump was made with and loaded on 2026.09.0 (Neo4j Desktop 2, 2026-10-24); a newer DBMS version is expected to load it but has not been tried. Set the DBMS's password and leave it stopped. Don't use Community edition for now (see "Community edition" below).
2. **Load the dump.** Put the file in a folder of its own, named exactly `neo4j.dump` (the load looks for `<database>.dump`), then, with the DBMS stopped, from the DBMS's installation folder:

   ```bash
   bin/neo4j-admin database load neo4j --from-path=<folder with neo4j.dump> --overwrite-destination=true
   ```

   On Windows it is `bin\neo4j-admin.bat`; on the development machine it needed `JAVA_HOME` set to Neo4j Desktop's bundled Java 21 runtime. If the DBMS is already running (Enterprise only), stop just the database instead: run `STOP DATABASE neo4j WAIT` on the `system` database, load, then `START DATABASE neo4j WAIT`. Then start the DBMS.
3. **Python environment:** install [uv](https://docs.astral.sh/uv/), then in the repo root:

   ```bash
   uv sync
   ```

   The project needs Python 3.13 (`requires-python = ">=3.13"`, pinned to 3.13 in `.python-version`); uv fetches it if it is missing.
4. **`.env`:** copy `.env.example` to `.env` in the repo root and fill in `NEO4J_URI` (your DBMS's Bolt URL, port 7687 by default), `NEO4J_USER` and `NEO4J_PASSWORD` (the password you set in step 1). `BEATAPI_API_KEY` is needed only to build the graph. Never commit `.env`.
5. **Check the connection and the data:**

   ```bash
   uv run python scripts/check_neo4j.py
   ```

   ```bash
   uv run python -m kg.load.facts --snapshot
   ```

   The first prints the server version; the second must print sha256 `13c96aef…` with 842 nodes and 1,280 relationships.
6. **Ask one question:**

   ```bash
   uv run python -c "from kg.query import ask; out = ask('sowing_window', {'crop': 'crop:rice', 'state': 'state:5', 'zones': ['zone:uk_tarai_bhabhar_plain']}); print([(f['values']['window_for'], f['citation']['quote']) for s in out['slots'] for f in s['facts']])"
   ```

   It prints the Tarai nursery and transplanting windows with their quotes.

**Community edition.** The dump's store format is `block-block-1.1` (introduced in Neo4j 5.14.0; read with `neo4j-admin database info neo4j` on 2026-10-24). Whether Neo4j Community loads it is **untested**, so teammates use Neo4j Desktop (step 1). For a Community deployment later, test the load first (recorded in the CLAUDE.md backlog); there are two routes, neither tested here:
- **migrate the store format:** on Enterprise, convert the database with `neo4j-admin database migrate` to a store format Community supports, dump it again, and load that dump into Community;
- **rebuild from the repository:** on an empty Community database, run the loaders from the repo: `uv run python -m kg.load.seed` (constraints and concepts), then `uv run python -m kg.load.facts <source>` for each of the three sources (each applies the committed expert decisions). The snapshot hash will not match `13c96aef…`, because it covers every property and `created_at` records the time of the load; check instead the 842 nodes and 1,280 relationships and the fact counts by status (section 1). The loaders read the pipeline outputs in `data/tables/`, `data/normalized/`, `data/validated/` and `data/verified/`, which are gitignored; unzip them from `backups/` (section 3) into `data/` first.

## 3. Starting Neo4j and connecting

- **Server:** a Neo4j Desktop local DBMS, 2026.09 or newer (Enterprise, developer licence; the development machine runs 2026.09.0). Start the DBMS in Neo4j Desktop and wait until it shows **Running**. It listens for Bolt on port 7687.
- **Databases:** `neo4j` (the home database: the real graph) and, on the development machine, `cropbot-test` (live tests only; every live test empties it first).
- **Connection settings** come only from `.env` in the repo root, which is never committed. The names (see `.env.example`):
  - `NEO4J_URI`: the Bolt URL of the local server;
  - `NEO4J_USER`, `NEO4J_PASSWORD`;
  - `BEATAPI_API_KEY`: the Jev verifier, needed only to build the graph, never to query it.
- **Backup** (2026-10-24, gitignored `backups/` on the development machine; none of it is on GitHub, so copy it elsewhere). Every zip's entry count was checked against its folder's file count.

  | File | Bytes | Contents |
  |---|---|---|
  | `neo4j.dump` | 345,278 | the `neo4j` database (sha256 `edd99b47…`); restored into `cropbot-test` and checked: same snapshot hash |
  | `data_raw_2026-10-24.zip` | 7,940,863 | `data/raw/`: the 3 source PDFs |
  | `data_docling_2026-10-24.zip` | 4,900,891 | `data/docling/`: the conversions (110 files) |
  | `data_review_2026-10-24.zip` | 4,721,869 | `data/review/`: review workbooks, hand-check pages, review CSVs and the decisions file (29 files) |
  | `data_extracted_2026-10-24.zip` | 660,266 | `data/extracted/`: the hand-run prompts and answers, with history (74 files) |
  | `data_units_2026-10-24.zip` | 339,616 | `data/units/`: segmentation units (6 files) |
  | `data_tables_2026-10-24.zip` | 133,249 | `data/tables/`: stitched tables and pivoted varieties (9 files) |
  | `data_verified_2026-10-24.zip` | 102,567 | `data/verified/`: Jev claims, answers and request logs (22 files) |
  | `data_normalized_2026-10-24.zip` | 63,380 | `data/normalized/`: step 10 facts and held facts (9 files) |
  | `data_validated_2026-10-24.zip` | 46,317 | `data/validated/`: step 11 facts (6 files) |
  | `data_eval_2026-10-24.zip` | 5,449 | `data/eval/`: the step 15 report (1 file) |
  | `data_loaded_2026-10-24.zip` | 2,325 | `data/loaded/`: step 13 load reports (3 files) |
  | **total** | **19,262,070** | |

  `data/gold/` is committed, so it needs no zip.

## 4. How the agent queries: pick a template, never write raw Cypher

The only entry point is

```python
from kg.query import ask
answer = ask(template, farm_context)      # -> dict (section 5)
```

- `template` is one of the seven names below. Each has fixed Cypher in `kg/query/templates.py`; the agent never writes or edits graph queries. A question no template covers gets no answer from the graph.
- `farm_context` is a dict (or a `kg.query.FarmContext`) describing the farmer. Fill only what the farmer has told you: **a missing field means "unknown"**, and the answer then asks for it instead of guessing. An unknown field name is refused.
- `ask` opens a connection from `.env` and closes it again. To reuse one connection, pass `driver=` (a `neo4j` driver); `database=` reads another database (for example `cropbot-test`).
- `ask` raises `kg.query.AskError` for an unknown template, a bad farm context or missing `.env` settings.
- From the shell, with a JSON context file: `uv run python -m kg.query sowing_window --context ctx.json`.

### The farm context (`kg/query/context.py`)

| Field | Example | Meaning |
|---|---|---|
| `crop` (required) | `"crop:rice"` | crop id (`concepts/crops.csv`) |
| `state` | `"state:5"` | LGD state id: Uttarakhand `state:5`, Tamil Nadu `state:33` |
| `district` | | district id (none seeded with an LGD code yet) |
| `zones` | `["zone:uk_tarai_bhabhar_plain"]` | the farmer's zones in their own state's scheme (`concepts/zones.csv`): `zone:uk_tarai_bhabhar_plain`, `zone:uk_mid_hills` (900–1500 m), `zone:uk_high_hills` (1500 m and above), and the Tamil Nadu zones (`zone:tn_…`) |
| `systems` | `["system:irrigated"]` | production systems (`concepts/production_systems.csv`) |
| `purpose` | `"purpose:grain"` | `purpose:grain` or `purpose:seed` (also fodder, …) |
| `duration_group` | `"medium"` | `short`, `medium` or `long` |
| `variety`, `season`, `local_seasons`, `soil_types`, `stage` | | concept ids |
| `month`, `sowing_date`, `das` | | when (days after sowing) |
| `storage_months` | `10` | how long the produce will be stored |
| `pest` | `"pest:brown_planthopper"` | required by `threshold` |
| `observations` | `{"spider_count_per_hill": 0}` | counts and measurements: `pest_count`, `spider_count_per_hill`, `grain_moisture_pct` |
| `soil` | `{"pH": 6.5, "Zn": "low"}` | soil-test ratings N, P, K, Zn and pH |
| `forecast` | `{"rain_mm_24h": 12}` | `rain_mm_24h`, `rain_days_3d`, `tmax_c` |
| `endemic` | `{"disease:tungro": true}` | whether the area is known for a pest or disease |
| `commodity_form`, `grade`, `quality`, `present` | `"paddy"`, `{"moisture": 18}` | `quality_check` only: what is sold, its grade, measured values, substances found |

### Choosing the farmer's zone

No district has an LGD code yet and there is no district → zone mapping, so the agent cannot derive a zone from where the farmer lives. For an Uttarakhand farmer it asks instead and sets `zones` itself:

- **plains or hills?** Plains (Tarai, Bhabhar and the plains) → `["zone:uk_tarai_bhabhar_plain"]`.
- **for hills, the altitude:** 900–1500 m → `["zone:uk_mid_hills"]`; 1500 m and above → `["zone:uk_high_hills"]`. Also ask whether the field is irrigated (`"systems": ["system:irrigated"]`): the hill varieties and windows are for irrigated hills, and without a system the answer asks for it.

Without a zone, `varieties_for` and `sowing_window` answer "No local guidance available" (checked on the main database with `{"crop": "crop:rice", "state": "state:5"}`): their facts are scoped to zones, and they never fall back to the state or to another state.

### The templates, one example each

Every example below was run on the main database on 2026-10-24; the comment says what came back.

**`drying_target`**: to what moisture to dry (DryingSpec; Q15, Q16). For `purpose:grain` it also adds the procurement moisture limit.
```python
ask("drying_target", {"crop": "crop:rice", "state": "state:33", "purpose": "purpose:grain"})
# 1 fact: dry the grains to 12 % (TNAU p. 39), labelled "not yet verified by an expert"; plus the DFPD limit 17 %
```

**`storage`**: how long and at what moisture to store (StorageRule, with cautions on any protectant).
```python
ask("storage", {"crop": "crop:rice", "state": "state:33", "purpose": "purpose:seed"})
# asks "For how many months will you store it?" and branches: 8-9 months at 12-13 %, 12-15 months at 8-9 %,
# more than 15 months below 8 % (TNAU p. 75), all labelled unverified
```

**`harvest_readiness`**: when to harvest and thresh (HarvestRule; Q12, Q14).
```python
ask("harvest_readiness", {"crop": "crop:rice", "state": "state:33", "purpose": "purpose:seed",
                          "duration_group": "medium"})
# 2 facts: harvest when 90 % of the panicles are golden yellow at 20 % moisture; thresh at 16-17 % (TNAU p. 74)
```

**`threshold`**: when a pest is bad enough to act (PestThreshold; Q8). Needs `pest`.
```python
ask("threshold", {"crop": "crop:rice", "state": "state:33", "pest": "pest:brown_planthopper",
                  "observations": {"spider_count_per_hill": 0}})
# 1 fact (TNAU p. 64) with its clauses, labelled unverified
```

**`quality_check`**: will the procurement centre accept the paddy (QualitySpec; Q19). National, so it answers in any state.
```python
ask("quality_check", {"crop": "crop:rice", "state": "state:5", "commodity_form": "paddy", "quality": {"moisture": 18}})
# 18 approved DFPD limits (p. 6), each with a pass/fail/unknown check; verdict "fail" on moisture (limit 17 %)
```

**`varieties_for`**: which variety to sow (VarietyRecommendation; Q1).
```python
ask("varieties_for", {"crop": "crop:rice", "state": "state:5", "zones": ["zone:uk_tarai_bhabhar_plain"]})
# 1 approved fact (GBPUAT p. 1); values["recommends"]: 16 varieties as {"id", "name"}
```

**`sowing_window`**: when to sow the nursery, sow or transplant (SowingWindow; Q2). One answer slot per operation.
```python
ask("sowing_window", {"crop": "crop:rice", "state": "state:5", "zones": ["zone:uk_mid_hills"],
                      "systems": ["system:irrigated"]})
# 2 approved facts (GBPUAT p. 1): nursery 1-15 May, transplanting 16-30 June; never the high-hills windows
```

Varieties and sowing windows never cross state lines: a farmer outside Uttarakhand gets "No local guidance available", never another state's varieties.

### Uttarakhand farmers get Tamil Nadu advice for drying, storage, harvest and thresholds

The graph has no Uttarakhand source for these four. For `state:5`, `drying_target`, `storage`, `harvest_readiness` and `threshold` therefore fall back to the Tamil Nadu (TNAU) facts: the answer's `scope` is `fallback`, and every served fact carries the label **"From a Tamil Nadu source"** besides "not yet verified by an expert". The agent must show that label with the advice. Run on the main database on 2026-10-24, for a Tarai farmer drying grain:

```python
ask("drying_target", {"crop": "crop:rice", "state": "state:5", "zones": ["zone:uk_tarai_bhabhar_plain"],
                      "purpose": "purpose:grain"})
# scope "fallback", asks [], 1 slot:
#   DryingSpec, status extracted, values {"target_moisture_pct_max": 12.0},
#   labels ["not yet verified by an expert", "From a Tamil Nadu source"],
#   citation source:tnau_agriculture_2020, PDF p. 39 (printed p. 27)
# procurement_moisture: the DFPD paddy moisture limit 17.0 (national, approved, no label)
```

The same context with the other three templates (storage `purpose:seed`; harvest_readiness `purpose:seed`, `duration_group: "medium"`; threshold `pest:brown_planthopper` with no spiders) also returned `scope: "fallback"`, every served fact labelled "From a Tamil Nadu source": storage 3 facts (and it asks the storage months), harvest_readiness 2, threshold 1.

## 5. What an answer contains

`ask` returns a dict:

| Key | What it is |
|---|---|
| `template` | the template name |
| `scope` | `local` (the farmer's own regions), `fallback` (another state's source; only drying, storage, harvest and threshold facts) or `none` |
| `asks` | questions to put to the farmer: `{"variable", "question", "policy"}`, e.g. `{"variable": "storage_months", "question": "For how many months will you store it?"}` |
| `slots` | the answer, one slot per distinct piece of advice: `{"branch", "facts", "disagreement"}`. `branch` says which answer to an open question the slot is for (`{"storage_months": ["8 to 9 months"]}`); `disagreement` is true when equally ranked sources give different values |
| `hidden` | facts and steps that matched but are not served, each with its `quote` and `reason` ("dose not yet verified by an expert", "outranked in its answer slot", "withheld: … unknown", …) |
| `notes` | remarks the agent may pass on (e.g. a storage term the source gives without months) |
| `message` | set when nothing is served: "No local guidance available" (no fact for this place), "No verified guidance available" (facts exist but none may be served) |
| `verdict` | `quality_check` only: `result` (pass / fail / unknown), `failed`, `not_checked`, `passed`, `grade_rules` |
| `procurement_moisture` | `drying_target` for grain only: the procurement moisture limit fact |

Each served fact in `slots[].facts` has `id`, `subtype`, `summary_en`, `labels`, `values` (the stored values, with `raw_*` holding the printed words), `steps` (each with `instruction_en`, `timing_raw`, `if` conditions still open), `hidden_steps`, `clauses` (thresholds), `conflicts`, `cautions`, `check` (quality_check) and a `citation`:

```python
{"quote": "...exact text from the source...", "pdf_page": 1, "printed_page": None, "source_title": "...",
 "source_id": "source:gbpuat_kharif_advisory_2020", "status": "approved", "verifier_score": 0.98,
 "missing_in_latest_run": False, "extraction_method": "table_parse", "transcription": None}
```

**How to show it to a farmer**
- If `asks` is not empty, ask those questions first (or show every slot with its `branch`, "if you store for 8 to 9 months: …").
- Show each served fact's advice with its citation: the source title and page, and the quote when the farmer wants to check. `printed_page` is the page number printed in the book (None when the page prints none); `pdf_page` is the PDF's page.
- Show every label next to the advice: **"not yet verified by an expert"** (an unreviewed fact), "checked automatically against the source", or "From a Tamil Nadu source" (a fallback answer for another state).
- Never show what is in `hidden` as advice; it is there for logging and review. Doses (fertilizer and pesticide amounts) from unreviewed facts are always hidden, and so is any step applying a pesticide whose registration has not been checked.
- With `disagreement: true`, show both values and their sources; don't pick one.
- If `message` is set and `slots` is empty, say so; don't fill the gap from general knowledge.

## 6. Language

The graph is in English: every quote, value, label and question is English, as printed in the sources. The agent may translate the advice into the farmer's language, but:
- quotes are shown unchanged, in the source's own words, never translated or reworded (a translation may be added beside a quote, marked as a translation);
- labels keep their meaning exactly: "not yet verified by an expert" must still say that no expert has checked it, and "From a Tamil Nadu source" that the advice comes from another state; a translation may not soften, drop or merge them;
- numbers, units and dates are carried over as they are (no unit conversion, no rounding).

## 7. Adding a new source, in short

The full rules are in `CLAUDE.md` (one section per stage); the order is fixed and each stage's output is checked by a person before the next.

1. **Register** the PDF: `registry/<source>.toml` (url, sha256 of the file, state, region scope, authority tier, edition, chapters). New PDFs go in `data/raw/` and are never committed. `uv run python -m kg.registry` checks it.
2. **Concepts first:** any state, zone, variety, pest or ingredient the source names that `concepts/` lacks is drafted in `concepts/proposed/` with its page quote, approved by a person, then moved into `concepts/`. Concepts are never created automatically.
3. **Convert** (`kg.convert`), **segment** (`kg.segment`), **tables** (`kg.tables`): check the converted text against the rendered pages; a scanned page whose OCR can't be trusted gets a hand transcription (`transcriptions/`).
4. **Extract** (`kg.extract prepare`, then a hand-run or a runner answers the prompt, then `kg.extract ingest`): the latest prompt is v6.
5. **Normalise, validate, verify** (`kg.normalize`, `kg.validate`, `kg.verify`): facts that can't be linked or read are held with their reasons; the verifier (Jev) scores code-built claims.
6. **Load** (`kg.load.facts`): run it twice; the second run must create nothing and leave the snapshot hash unchanged.
7. **Review:** a person checks every fact (`kg.review sheet`, or a hand-check page) and approvals are imported through the decisions file (`kg.review import`), then reloaded twice.
8. **Fixtures:** one farm context per question in `tests/query/fixtures/`, run live on `cropbot-test`.

## 8. Known limits and backlog

See `CLAUDE.md` for the details; in short:
- **Coverage is small:** one TNAU rice chapter (four sections), the DFPD paddy schedule, and the GBPUAT rice rows (2020). No wheat facts, no other crop, no Hindi source yet. Uttarakhand farmers get Tamil Nadu advice, labelled, for drying, storage, harvest and thresholds (section 4).
- **Almost all TNAU facts are unreviewed** (`needs_review` or `extracted`): their doses are hidden and descriptive facts carry the unverified label. The agronomist's review workbook (`data/review/expert_review_tnau.xlsx`) is waiting.
- **No pesticide is served:** every active ingredient's registration status is `unknown` until the CIB&RC list is loaded, and pesticide steps fail closed.
- **No auto-verification threshold** yet (the gold set is too small to calibrate one), so nothing becomes `auto_verified`.
- **Districts have no LGD codes** and there is no district → zone mapping: the agent asks plains or hills and the altitude (section 4).
- **Community edition is untested** for the dump: use Neo4j Desktop; test a Community load before any Community deployment (section 2).
- **Held facts:** Chetki Dhan and Jethi Rice (GBPUAT; no concepts for spring rice, upland or the direct-seeding type), and 11 TNAU facts (CLAUDE.md lists each reason).
- **Backlog:** the Jev claim lead-in should read "for irrigated rice", not "for the crop under irrigated"; prompt v6 shows the model no crop, so only a hand-run can tell other crops' rows in a multi-crop table; the open schema notes (v1.4-v1.6) and the proposed items in `CLAUDE.md`.
