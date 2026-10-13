# Dynamic Document Ingestion (STEP 19B1 — backend foundation)

User-supplied PDFs can be validated, stored, registered, parsed, chunked,
embedded, indexed, and retrieved through the existing `DocumentAgent`,
without touching the frozen STEP 03/06 corpus. No public upload endpoint
exists yet (STEP 19B2); no frontend wiring; no chat attachments.

## Architecture

```
Uploaded PDF
  → validation (MIME + %PDF- signature + PyMuPDF parse)
  → SHA-256 (streaming, size-capped)
  → registry (data/documents/registry/documents.db)
  → original file (data/documents/originals/<USR-ID>.pdf, atomic move)
  → page extraction (PyMuPDF, 1-based pages, same as frozen corpus)
  → chunking (frozen build_document_chunks, per-page sections)
  → BGE embeddings (same frozen model instance shared)
  → separate Qdrant collection (manufacturaiq_dynamic_documents)
  → DynamicDocumentRetriever + CompositeDocumentRetriever
  → DocumentAgent → frozen Evidence
```

## Static/dynamic separation

| Aspect | Static (frozen) | Dynamic (new) |
|---|---|---|
| Source | 4 PDFs, 2173 pages, 2193 chunks | user uploads |
| Files | `datasets/`, staged artifacts | `data/documents/` (originals/registry/processing/vectors) |
| Qdrant path | `vector_store` | `data/documents/vectors` |
| Collection | `manufacturaiq_documents` | `manufacturaiq_dynamic_documents` |
| Payload dataset | `manufacturaiq_document_corpus` | `manufacturaiq_dynamic_documents` (+ `corpus: "dynamic"`) |
| Document IDs | `DOC-*` | `USR-*` (no collision) |
| Embedding | BGE-small-en-v1.5, dim 384, COSINE | identical |

Static collection is never deleted/recreated/upserted by dynamic code
(verified: 2193 before and after).

## Registry schema

SQLite `documents` table: `document_id` (PK), `original_filename`,
`stored_filename`, `sha256` (UNIQUE — duplicate authority),
`mime_type`, `file_size_bytes`, `status`, `page_count`, `chunk_count`,
`created_at`, `updated_at`, `error_code`, `error_message` (sanitized ≤500),
`metadata_json`. Parameterized SQL only; idempotent init; no secrets stored.

Statuses: `PENDING → PROCESSING → READY | FAILED`.

## Storage lifecycle

Stream → temp `.part` file (size cap enforced while streaming) → SHA-256 →
PDF validation → atomic `os.replace` to permanent location. Failures delete
the temp file; a READY record always implies complete storage + index.

## Duplicate semantics

SHA-256 is the content authority: re-uploading identical bytes returns the
existing document (`duplicate=True`) without reindexing. Simultaneous
duplicates are serialized by the `UNIQUE(sha256)` constraint (loser returns
the winner). Chunk/point IDs are deterministic (`make_chunk_id` +
UUID5 point IDs), so retry = delete-by-`document_id` + overwrite, never
duplicates.

## PDF validation

Accepts only genuine PDFs: `%PDF-` magic, PyMuPDF parse, ≥1 page.
Rejects: non-PDF, malformed, encrypted/password-protected
(`ENCRYPTED_PDF`, no cracking), zero-text/image-only (`NO_EXTRACTABLE_TEXT`,
no OCR in 19B1).

## Chunking / embeddings

Frozen `build_document_chunks` with one section per page (1-based pages),
`ChunkingConfig` from Settings, HF tokenizer with heuristic fallback.
Chunk IDs `CHUNK-USR-*-P<start>-<end>-<ord>-<digest>`: deterministic across
re-runs. Embeddings reuse the single application-owned BGE instance
(dim 384); ingestion encodes in `document_ingest_batch_size` batches.

## Dynamic Qdrant collection

Created idempotently (`ensure_collection` asserts dimension on mismatch),
COSINE distance, payloads carry `document_id`, `page_start/end`, `chunk_id`,
`title`, `source_type`, `corpus`, plus frozen-compatible fields.
Filterable by `document_id` (future delete/reindex). Single-client rule:
one `VectorStore` per path per process — ingestion service and retriever
must share the store instance when coexisting.

## Composite retrieval

`CompositeDocumentRetriever` queries static + dynamic with identical settings
(top_k, pool, lexical blend), merges on blended score
(`rerank_score ?? vector_score`), stable tie-break
(score ↓, document_id, page, chunk_id), chunk dedup, top_k cut, re-ranked
1..n. No corpus boost. Empty dynamic collection reproduces static results
exactly (tested). `document_context` filters (incl. `document_id`) apply to
both corpora. `DocumentAgent` sees only the `DocumentRetriever` protocol;
the composite is injected at composition time
(`build_document_agent(settings, retriever)`); the orchestrator builder uses
it when `document_upload_enabled`, else static exactly as before.

## Failure recovery

Extraction/embedding/upsert failure → status `FAILED` (never READY),
best-effort deletion of that document's partial vectors, original file kept
per policy, retry re-runs deterministically.

## Security model

- PDF only; extension and Content-Type never trusted.
- Original filenames untrusted: system-controlled `<USR-ID>.pdf` names,
  traversal/absolute/separator names rejected.
- 50 MB default cap (configurable).
- PDF text is DATA: indexed verbatim, never executed, never placed into
  system configuration or prompts (prompt-injection-as-data tested).
- No API keys, headers, or env dumps in metadata/registry/payloads.

## Resource lifecycle

No per-request clients. `close()` cascades service → store + registry and
composite → both retrievers. Test resources use `tmp_path` and are closed by
fixtures; nothing writes to `data/documents` in tests.

## Known limitations (19B1)

PDF only; no OCR; no encrypted PDFs; synchronous service ingestion; no public
upload endpoint; no frontend wiring; no deletion API; no reindex UI; no
temporary chat attachments. Future STEP 19B2 API wiring will need a shared
store/registry owner in the application lifespan (single-client rule).

## STEP 19B2 — public API + frontend integration

### Public API

- `POST /api/documents` (multipart `file`) → 201 new READY, 200 duplicate
  (`duplicate: true`), 413 oversize, 415 non-PDF, 422 malformed/encrypted/
  no-text, 503 disabled, 500 unexpected only. Synchronous ingestion; routes
  are thin and delegate to `DocumentIngestionService` via threadpool.
- `GET /api/documents` → dynamic user documents only (registry order),
  safe fields only (no paths, no SHA-256, no metadata blobs).
- `GET /api/documents/{id}` → one record; unknown or non-`USR-*` IDs → 404
  (static `DOC-*` never manageable).
- `DELETE /api/documents/{id}` → vectors → file → registry row; missing →
  404; `USR-*` only; re-upload after delete works (SHA row removed).

### Resource ownership

FastAPI lifespan owns `DocumentResources` (registry + shared dynamic
`VectorStore` + embedder) and builds the service from it; the orchestrator
is composed with `document_resources` so the composite's dynamic retriever
shares the SAME store object (identity-tested). Externally injected services
are never closed by the app. Upload-disabled startup still works (static RAG
unchanged; document endpoints → 503). `/health`/`/ready` semantics unchanged.

### Deletion lifecycle

Compensating order (not ACID): delete dynamic vectors by `document_id`
filter → delete original (missing treated as clean) → delete registry row
last so failures stay retryable. READY deletion removes vectors, file, and
row; afterwards retrieval returns nothing for that ID. FAILED rows deletable
(zero vectors). Static collection never touched (2193 before/after verified).

### Frontend integration

`UploadModal` performs real `POST /api/documents` (FormData, no manual
Content-Type, no fake progress — binary Uploading/Processing → result);
READY shows "Document added to the knowledge base.", duplicates show
"This document already exists in the knowledge base.", errors map
413/415/encrypted/no-text to friendly messages. `KnowledgeBaseView` renders
the live list (status/pages/chunks/timestamps, safe FAILED errors, delete
with inline confirmation, "No uploaded documents yet." empty state).
`UploadsView` renders the same live registry as ingestion records (no fake
progress/durations/workers). Uploaded PDFs are immediately retrievable via
normal `POST /api/query` through the composite retriever; no reload needed.
Chat flow itself is unchanged (no PDF bytes attached to queries).

### Security boundaries

Endpoints are unauthenticated — suitable only for controlled prototype
deployment. PDF-only enforced server-side; client checks are hints.
Filenames untrusted end-to-end; error payloads contain no tracebacks/paths;
SHA-256 stays server-side.

### E2E verification (19B2 smoke)

Upload (201 READY) → list shows `USR-*` → chat query retrieves dynamic
evidence → delete (200) → list empty → repeat query returns no dynamic
evidence. Static count 2193 throughout; dynamic count >0 during, baseline
after. CORS clean from `http://localhost:5173` (GET/POST/DELETE allowed).

## Known limitations (after 19B2)

PDF only; no OCR; no encrypted PDFs; synchronous upload/ingestion; no
temporary chat attachments; no auth/multi-user isolation yet; no progress
streaming; no manual reindex endpoint; no document editing.

## Configuration

`DOCUMENT_UPLOAD_ENABLED` (default true), `DOCUMENT_STORAGE_PATH` (default
`<project>/data/documents`), `DOCUMENT_MAX_UPLOAD_MB` (50),
`DOCUMENT_DYNAMIC_COLLECTION` (`manufacturaiq_dynamic_documents`),
`DOCUMENT_INGEST_BATCH_SIZE` (32). Hermetic tests use `_env_file=None`.
