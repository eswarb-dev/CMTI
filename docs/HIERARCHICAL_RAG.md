# STEP 06 - Hierarchical Document RAG

This document describes the ManufacturaIQ **hierarchical retrieval pipeline over
technical documents**: hierarchy reconstruction, section-aware chunking,
embeddings, the local Qdrant index, query-time filtering/scoring, the STEP 04
`DocumentRetriever` implementation, validation and tests.

STEP 06 adds **no agents, no LLM calls, no Jev/LangGraph, no FastAPI routes and
no frontend**. It only builds and serves a deterministic local index that
returns frozen STEP 04 `Evidence`.

---

## 1. Interpreter and commands

Every STEP 06 command runs on the project interpreter only:

```
D:\CMTI\.venv\Scripts\python.exe      # Python 3.12.10 (no system/global interpreter)
```

| Purpose | Command (run from `D:\CMTI\backend` unless noted) |
| --- | --- |
| Build/rebuild index | `D:\CMTI\.venv\Scripts\python.exe -m app.rag.ingestion --force` |
| Incremental/idempotent run | `D:\CMTI\.venv\Scripts\python.exe -m app.rag.ingestion` |
| Chunks only (no embedding) | `... -m app.rag.ingestion --chunks-only` |
| Validation | `... -m app.rag.validation` |
| Query CLI | `... -m app.rag.retrieval "spindle lubrication" --top-k 5` |
| Tests | `... -m pytest tests/rag -q` |

`pip` installs were also performed with `D:\CMTI\.venv\Scripts\python.exe -m pip`.

## 2. Inputs and data integrity

Source of truth is the **STEP 03 staged corpus**; PDFs are never re-parsed.

| Input | Path | Content |
| --- | --- | --- |
| Corpus manifest | `datasets/manifests/documents.json` | 4 documents (sha256, type, page counts) |
| Staged pages | `datasets/staged/documents/pages/document_pages.parquet` | 2173 rows |
| Document metadata | `datasets/staged/documents/metadata/document_metadata.parquet` | 4 rows |
| Candidate headings | `datasets/staged/documents/metadata/candidate_headings.parquet` | 7240 rows (noisy, not trusted) |
| Page table (STEP 03) | quality GOOD 2152 / SPARSE 16 / EMPTY 3 / POSSIBLE_SCAN 2 | 3 EMPTY pages excluded, no OCR run |

STEP 06 only **creates**:

- `datasets/normalized/documents/document_chunks.parquet`
- `D:\CMTI\vector_store\` (index + `manifest.json`)
- `datasets/reports/RAG_BUILD_REPORT.md`
- backend code/tests under `backend/app/rag/`, `backend/tests/rag/`
- `docs/HIERARCHICAL_RAG.md`

It never modifies `datasets/raw`, `datasets/staged`, `datasets/normalized/demo_factory`,
`datasets/normalized/external`, the SQLite database, or STEP 04 contracts/protocols.

## 3. Module map

| Module | Responsibility |
| --- | --- |
| `app/rag/models.py` | `DocumentNode`, `PageRecord`, `SectionNode`, `ChunkRecord`, `map_document_source_type` |
| `app/rag/hierarchy.py` | deterministic heading detection + section tree |
| `app/rag/chunking.py` | token counting, grouping, window splitting, merging, chunk ids |
| `app/rag/embeddings.py` | `BAAI/bge-small-en-v1.5` encoder (CPU, normalized, query prefix) |
| `app/rag/vector_store.py` | local Qdrant wrapper, deterministic point ids, single-client guard |
| `app/rag/filters.py` | `user_context` -> Qdrant payload filter, `validate_top_k` |
| `app/rag/scoring.py` | hierarchy-aware re-ranking + deterministic lexical blend, dedupe, section caps, backfill |
| `app/rag/retrieval.py` | `DocumentRetrieverImpl`, `Evidence` mapping, neighbour lookup, CLI |
| `app/rag/ingestion.py` | end-to-end build, fingerprint/idempotency, atomic swap, report |
| `app/rag/validation.py` | 21 structural/quality/retrieval checks + document and content metrics |

Central configuration lives in `app/core/config.py` (`Settings`):
`rag_chunk_target_tokens=448`, `rag_chunk_overlap_tokens=80`,
`rag_chunk_max_tokens=500`, `rag_chunk_min_tokens=120`, `rag_max_top_k=50`,
`rag_candidate_multiplier=4`, `rag_max_per_section=3`, `rag_header_lines=3`,
`rag_lexical_weight=0.1` (+ `rag_lexical_content/heading/phrase_weight`
`0.5/0.3/0.2`), `rag_collection_name=manufacturaiq_documents`,
`vector_store_path=<project_root>/vector_store`.

## 4. Hierarchy reconstruction

All rules are deterministic and operate on staged page text only.

1. **Edge page markers** - the first/last `rag_header_lines=3` physical lines of
   a page are blanked when they are bare digits (`12`, `page 7`) or small roman
   numerals (value <= 50), so headers/footers never enter chunk text.
2. **Contents pages** - a page with >= 5 dot-leader lines or >= 5 numbered
   entries carrying a trailing page reference is treated as a TOC page:
   no headings are detected there.
3. **Heading patterns**
   - `Chapter N[: Title]` -> level 1 (title may come from the next line);
   - single-line `N.N Title` -> level = number of dots + 1;
   - split `N.N` on one line and its Title Case caption on the next line
     (consumed as one heading, method `split_number_heading`);
   - exact uppercase structural keyword allowlist (`SAFETY`, `MAINTENANCE`,
     `TROUBLESHOOTING`, ...) -> level 1;
   - strict unnumbered Title Case titles -> level 1, only when preceded by a
     blank line and followed by another line on the same page.
4. **Wrapped-line guards** - connector last words (`... and`), long trailing
   sentences (lowercase continuation of >= 6 words), dot leaders, and trailing
   page references (`3.1 Safety Regulations   42`, `... xiv`) reject a heading.
5. **Running-header dedupe** - a heading with the same `(level, text)` seen
   earlier in the document is a running header: its lines are removed from the
   body (1198 suppressed lines in the Siemens manual alone).
6. **Stale-parent suppression** - when a numbered child (level >= 2) is pushed
   under a plain unnumbered parent, that parent is popped so the child starts a
   new branch instead of inheriting a wrong ancestor.
7. **Verbatim text** - heading text is only whitespace-normalised; no level is
   ever invented, so `chapter / section / subsection` fields always exist or are
   legitimately absent (prelude chunks).

Resulting sections: Siemens 844, Haas lathe 692, Haas mill 689, OSHA 15.

## 5. Section-aware chunking

- Small sections are grouped forward until `target_tokens=448`, never crossing
  a level <= 1 or `chapter_heading` boundary, so chunks keep a meaningful
  hierarchy path.
- Oversized groups are split at <= `max_tokens=500` (inside the 512-token bge
  budget) with paragraph/sentence snapping and `overlap_tokens=80` tail overlap.
- Chunks below `min_tokens=120` are absorbed into the previous chunk of the same
  document when the merged size stays within `max_tokens`.
- Token counting uses the local HuggingFace tokenizer
  (`hf_tokenizer:BAAI/bge-small-en-v1.5`) with a deterministic heuristic
  fallback if the tokenizer cannot be loaded.

**Chunk id scheme** (deterministic, no UUID4):

```
CHUNK-<document_id without "DOC-">-P<page_start>-<page_end>-<stable_ordinal>-<sha256[:10].upper()>
stable_ordinal = section_ordinal * 1000 + range_ordinal
content_hash   = sha256(chunk text)
```

**Corpus result (2193 chunks)**

| Metric | Value |
| --- | --- |
| unique chunk ids | 2193 / 2193 |
| token size | min 35 / mean 398.2 / median 481 / max 500 |
| empty chunks | 0 |
| duplicate (document, content_hash) | 0 |
| page range violations | 0 |
| chunks with hierarchy path | 1996 (197 prelude chunks) |

## 6. Embeddings and vector store

| Item | Value |
| --- | --- |
| Model | `BAAI/bge-small-en-v1.5` (local cache, CPU) |
| Dimension / distance | 384 / cosine, L2-normalised vectors |
| Query prefix | `Represent this sentence for searching relevant passages: ` (bge models only) |
| Collection | `manufacturaiq_documents` |
| Store | local Qdrant at `D:\CMTI\vector_store` |
| Point ids | UUID5 over the chunk id (stable across rebuilds) |

**Atomic build and idempotency** - a fresh index is built in
`.vector_store.tmp`, then swapped into place with a `.old` backup. The
`manifest.json` stores a fingerprint over document hashes, staged file hashes,
chunk ids, chunking config, embedding model and `ingestion_version=step06.v1`.
A rerun reuses the index only when fingerprint, chunk count and paths match;
otherwise it rebuilds (`--force` always rebuilds).

**Single-client guard** - local Qdrant silently reports an empty collection if a
second client opens the same path. `VectorStore` therefore refuses a second
open for a path already held in the process (tests share one session retriever).

## 7. Query-time behaviour

| Concern | Behaviour |
| --- | --- |
| `top_k` | `< 1` raises `ValueError`; `> rag_max_top_k=50` is clamped to 50 |
| Candidate pool | `min(max(top_k * 4, 40), 200)` vector hits before re-ranking |
| Filters | only `document_type`, `manufacturer`, `machine_family`, `model`, `document_id`, `language` from `user_context` |
| Identity fields | `machine_id` / `product_id` / `batch_id` are **ignored** - manuals are never bound to machines |
| `document_type` | matched against the raw staged value (`OPERATOR_MANUAL`) **or** the canonical source type (`MANUAL`) |
| Re-ranking | acceptance order by `(1 - rag_lexical_weight) * vector + rag_lexical_weight * lexical` (default `0.1`), drop duplicate `content_hash`, max 3 chunks per section, drop overlapping near-duplicates (same section + page overlap + score delta <= 0.02), then backfill to `top_k`. `retrieval_score` always stays the raw vector score; lexical/combined components live in metadata (`vector_score_raw`, `lexical_score`, `rerank_score`) |
| Source type | `map_document_source_type`: `*_SAFETY`/`SAFETY` -> `SAFETY`, `SOP*` -> `SOP`, `*_MANUAL`/`TECHNICAL_REFERENCE`/... -> `MANUAL`, deterministic fallback `MANUAL` (`EXTERNAL_DATASET` stays reserved for tabular datasets) |

**Evidence contract** - each hit becomes a frozen STEP 04 `Evidence`:
`evidence_id = EVIDENCE-<chunk_id>`, `source_kind=DOCUMENT`,
`source_dataset=manufacturaiq_document_corpus`, `source_id=chunk_id`,
`document_id`, `chunk_id`, `page_start <= page_end`, `chapter/section/subsection`,
`retrieval_score` = vector score (never `decision_score`), title =
`<document title> - <heading>` (<= 300 chars) and metadata that includes the
heading path, hierarchy fields, content hash, embedding/ingestion versions and
`previous/next chunk id + preview` from the chunk artefact.

## 8. Validation and retrieval fixture

`python -m app.rag.validation` runs 21 checks: manifest/staged/chunks/vector
artefacts present, unique ids, no empty or duplicate chunks, valid page ranges,
hierarchy fields present, index/parquet/manifest counts equal, fixture present,
cases evaluated, hit@1/@3/@5 and MRR thresholds, three informational
content-hit checks, and source-type scoping.

The fixture `backend/tests/rag/fixtures/retrieval_cases.json` holds **23 cases**
(thresholds: hit@1 >= 0.7, hit@3 >= 0.85, hit@5 >= 0.9, MRR >= 0.75): the
original 18 document-level cases plus 5 core content cases (`spindle
lubrication`, `lathe chuck safety`, `SINUMERIK tool management`, `lockout
tagout hazardous energy`, `Siemens alarm reset`), with 14 cases carrying
deterministic chunk-level requirements (`expected_keywords`,
`expected_keywords_any`, `expected_heading_keywords`,
`forbidden_heading_keywords`; token-based single terms, substring phrases, no
LLM judge).

Current metrics: **hit@1 0.957, hit@3 1.0, hit@5 1.0, MRR 0.978** (23/23) and
**ContentHit@1 0.714, ContentHit@3 1.0, ContentHit@5 1.0** (14/14 content
cases, informational, no thresholds).

## 9. Tests

`backend/tests/rag/` - 71 tests, all using the project interpreter:

| File | Coverage |
| --- | --- |
| `test_hierarchy.py` (12) | page markers, TOC detection, chapter/numbered/split/keyword/unnumbered rules, wrapped-line guards, running-header dedupe, stale-parent suppression, section fields, verbatim text |
| `test_chunking.py` (9) | config validation, chunk id format, token budgets, grouping boundaries, small-chunk merging, determinism, real-artifact invariants |
| `test_filters.py` (8) | `top_k` bounds, identity-key exclusion, supported/ignored keys, document_type dual match, `MatchAny` multi-value |
| `test_scoring.py` (13) | ordering, content dedupe, section caps, overlap suppression, backfill, empty input, lexical term extraction, lexical components, weight-0 passthrough, blend promotion with vector score preserved, determinism |
| `test_ingestion.py` (6) | point ids, fingerprint sensitivity, manifest consistency, reuse gate, parquet round-trip, statistics |
| `test_vector_store.py` (3) | single-client guard, persistence, filtered search |
| `test_retrieval.py` (7) | bounded results, `top_k` validation, identity non-binding, document_type scope, determinism, safety-first, fixture thresholds |
| `test_evidence.py` (5) | source-type mapping, provenance completeness, metadata/neighbours, title composition, vector-score policy with blend diagnostics |
| `test_content.py` (7) | content-hit semantics (doc/source/keyword/heading/forbidden), token-vs-substring matching, content metrics aggregation, fixture core-query coverage, info-metric reporting |
| `test_artifact_protection.py` (1) | session guard: chunk-parquet hash and vector-manifest fingerprint unchanged by tests |

## 10. Artefacts

| Artefact | Path |
| --- | --- |
| Chunks | `D:\CMTI\datasets\normalized\documents\document_chunks.parquet` (2193 rows) |
| Index | `D:\CMTI\vector_store\` (+ `manifest.json`) |
| Build report | `D:\CMTI\datasets\reports\RAG_BUILD_REPORT.md` |
| Validation | `python -m app.rag.validation` (21/21 PASS) |
| Fixture | `backend/tests/rag/fixtures/retrieval_cases.json` |

## 11. Operational notes

- Local Qdrant allows **one open client per storage path**; validation and the
  tests share a single retriever instance. A second open raises `RuntimeError`
  instead of silently returning zero results.
- `tests/document_pipeline/` is fully isolated (STEP 06A): extraction and
  validation accept temporary `raw_root`/`staged_root`/manifest/report paths,
  all destructive tests run inside `tmp_path` on minimal synthetic fixtures
  (empty corpus, small `.txt` corpus, tiny generated PDF), missing PyMuPDF
  raises before any write, and a session guard fails the suite if any canonical
  STEP 03 artefact hash changes.
- Re-running `pytest D:\CMTI\tests` re-generates `transformations.json`
  timestamps only; dataset content stays identical.

## 12. STEP 06A hardening pass

1. **Test isolation (STEP 03)** - the document-pipeline regression test
   previously called `extract()` against canonical staged paths and could pass
   while writing an empty corpus when PyMuPDF was missing. `extract()`,
   `validate_corpus()`, `discover_documents()` and `write_report()` now accept
   temporary output roots (CLI defaults unchanged); missing PyMuPDF raises
   before any write; all destructive tests use synthetic `tmp_path` fixtures;
   a session fixture guards the canonical artefact hashes.
2. **Content-level evaluation** - alongside Hit@1/@3/@5 and MRR, validation
   reports ContentHit@1/@3/@5 over content-evaluated fixture cases
   (informational, no thresholds, deterministic keyword/heading rules, no LLM
   judge). Baseline before re-ranking: 0.714 / 0.786 / 0.786.
3. **Lexical re-rank (`scoring.py` only)** - the baseline exposed one genuine
   failure: "SINUMERIK tool management" returned generic Siemens overviews
   while the true tool-management lists sat at vector ranks 8-27. Acceptance
   order now blends `(1 - 0.1) * vector + 0.1 * lexical` with lexical =
   `0.5 * content-term coverage + 0.3 * heading-term coverage + 0.2 * query
   bigram-phrase coverage` (lowercase/Unicode normalisation, minimal
   stopwords, technical vocabulary preserved). `Evidence.retrieval_score`
   remains the raw vector score; diagnostics live in metadata. Result:
   ContentHit@3/@5 = 1.0, doc MRR 0.971 -> 0.978, no other case regressed.
4. **Spindle lubrication verdict** - the corpus contains no dedicated spindle
   lubrication procedure; the closest genuine evidence is the spindle
   warm-up/lubrication-distribution text: **INSUFFICIENT DIRECT DOCUMENT
   EVIDENCE** for a dedicated procedure. Nothing was artificially promoted.
5. **RAG test isolation** - all `tests/rag` writes already targeted `tmp_path`;
   a session guard additionally pins the chunk-parquet hash and the vector
   manifest fingerprint across the suite.
