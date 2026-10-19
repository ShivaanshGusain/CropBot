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
uv run python -m pytest                   # tests (none exist yet)
uv run python -m pytest tests/test_x.py::test_name   # one test

uv run --project extraction python extraction/extract.py --list   # registry check: included, duplicate, unregistered PDFs
uv run --project extraction python extraction/extract.py --all --source tnau_agriculture
uv run --project extraction python extract.py --all               # original MVP script
```

`requirements.txt` is a leftover; dependencies go in `pyproject.toml` via `uv add`. There is no linter or formatter configured.

`docs/jev_example.md` holds the reference Jev (verifier) request; the key is `BEATAPI_API_KEY` in `.env`. `.env.example` lists the variable names.

## Existing code and how it relates to the schema

**Two versions of `extract.py`.**
- `extract.py` (root) is the original MVP. It handles 4 fixed books, downloads them into `sources/pdfs/`, and produced the committed `converted/` and `out/` folders (docling 2.140.0, run on CUDA).
- `extraction/extract.py` is the improved version. It reads every PDF in `BooksData/` using `extraction/sources.toml`. It keeps bounding boxes and footnotes, avoids false crop matches ("lime", "gram") and detects byte-identical duplicates by sha256.
- Both convert with Docling and flatten the result into an item list: `{k: h|p|li|tbl|img, lvl, t, md, img, cap, pg, ...}`. From that list they split each book by crop into `out/<crop>_<source_id>.md`.

**The committed `converted/*.index.json` files are lossy.**
- They store no bboxes, no OCR confidence and no Docling JSON. Tables are Markdown strings only, and footnotes were dropped. So they cannot supply `SourceSpan.bbox` or `table_ref` (`#/tables/N`).
- The schema's convert stage needs the lossless DoclingDocument JSON. That is a new conversion; the cache goes under `data/docling/` (gitignored).

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
- 51 PDFs (about 590 MB) are already tracked: `BooksData/`, `sources/pdfs/` and `data/raw/`.
- `data/raw/AGRICULTURE.pdf`, `BooksData/AGRICULTURE.pdf` and `sources/pdfs/tnau_agriculture.pdf` are the same file (TNAU Crop Production Guide 2020).

**`Graph_Rag_try.py`** is a discarded prototype. It uses unconstrained `LLMGraphTransformer` on fixed-size chunks with hard-coded Neo4j credentials. It conflicts with the schema, so don't extend it.

**Soil Health Card scrapers** (`state_retrival.py`, `district_retrival.py`, `block_retrival.py`, `village_retrival.py`, `data_scraper.py`, notes in `cheetsheet.txt`):
- They crawl soilhealth4.dac.gov.in.
- The research brief says to stop them because of the portal's terms of service.
- Their region IDs are portal-internal, not the LGD codes the schema uses.
- Live data stays out of the graph anyway (schema design principle 8).
