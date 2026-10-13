# STEP 16 — FastAPI API Layer

## Purpose

STEP 16 exposes the existing ManufacturaIQ workflow over HTTP. FastAPI is only
an adapter:

```text
HTTP request -> API schema -> QueryRequest -> orchestrator.run() -> API response
```

The API layer does not reimplement routing, agent execution, evidence fusion,
reasoning, review, repository access, RAG retrieval, or provider behavior.

## Installed Runtime

- FastAPI: `0.141.1`
- Uvicorn: `0.54.0`
- Application version: `0.1.0`

## App Factory

Application construction is handled by:

```python
create_app(orchestrator=None, settings=None, orchestrator_factory=build_manufacturaiq_orchestrator)
```

Importing `app.main` does not construct production orchestrator dependencies.
The default module-level `app` is a FastAPI object whose production workflow is
constructed only when lifespan startup runs.

## Lifespan Ownership

If no orchestrator is injected, lifespan startup constructs one app-owned
orchestrator using the STEP 15 builder. That instance is stored on `app.state`
and reused for all requests.

If an orchestrator is injected into `create_app()`, the API treats it as
externally owned and does not close it during shutdown.

For app-owned orchestrators, shutdown calls `aclose()` or `close()` only if the
object exposes one of those methods. Shutdown failures are logged and not
exposed through public response bodies.

## Qdrant And Provider Lifecycle

The API never creates Qdrant, Jev, Gemini, DB, RAG, or agent dependencies per
request. Production construction happens once in lifespan through the STEP 15
orchestrator builder.

Provider API keys are not required for `/health` or `/ready`. Missing Jev or
Gemini keys are handled by the underlying frozen components during workflow
execution.

## Endpoints

### `GET /health`

Process liveness only.

Response:

```json
{
  "status": "ok",
  "service": "manufacturaiq"
}
```

This endpoint does not touch the orchestrator, database, Qdrant, agents, Jev,
Gemini, or RAG validation.

### `GET /ready`

Lightweight wiring readiness.

Response:

```json
{
  "status": "ready",
  "service": "manufacturaiq",
  "orchestrator": "available"
}
```

Readiness checks that startup supplied an orchestrator. It does not call
external providers, run DB validation, or run RAG validation.

### `POST /api/query`

Runs one request through `orchestrator.run(query)`.

Request:

```json
{
  "query": "Investigate the recent production rejects for CNC-05.",
  "machine_id": "CNC-05"
}
```

The query text is not parsed for `machine_id`. Clients must supply structured
scope fields explicitly.

Supported request fields:

- `query`
- `machine_id`
- `product_id`
- `batch_id`
- `time_start`
- `time_end`
- `document_context`

`document_context` allows only:

- `document_type`
- `manufacturer`
- `machine_family`
- `model`
- `document_id`
- `language`

Unknown fields are rejected. Arbitrary public `user_context` is not accepted.

### `POST /api/documents`

Multipart upload with a single `file` field (PDF only). Synchronous
ingestion: 201 new READY document, 200 duplicate (`duplicate: true`),
413 oversize, 415 non-PDF, 422 malformed/encrypted/no-text, 503 when
uploads are disabled.

### `GET /api/documents`

Dynamic user documents in registry order (`{documents, count}`); safe
fields only.

### `GET /api/documents/{document_id}`

One dynamic record (`USR-*` only); unknown or static IDs → 404.

### `DELETE /api/documents/{document_id}`

Removes dynamic vectors, original file, and registry row
(`{document_id, deleted: true}`); unknown IDs → 404.

## Query ID Policy

The frozen `QueryRequest` requires a `query_id`, so the API generates a UUID
for every accepted request. Clients do not supply internal query IDs in STEP 16.

## Response Schema

The API response contains:

- `query_id`
- derived `status`
- `routing`
- optional `evidence`
- optional `reasoning`
- optional `review`

The response serializes frozen application data only. It does not expose vector
embeddings, Qdrant paths, filesystem paths, provider request bodies, API keys,
or database connection information.

## Status Semantics

`status` is derived from frozen workflow fields:

- `needs_clarification`: `RoutingDecision.needs_clarification == true`
- `pass`: `ReviewDecision.action == PASS`
- `human_review`: `ReviewDecision.action == HUMAN_REVIEW`

This is not a second business-state authority.

## Response Examples

PASS:

```json
{
  "query_id": "uuid",
  "status": "pass",
  "routing": {"needs_clarification": false},
  "evidence": {"evidence": [], "warnings": [], "conflicts": []},
  "reasoning": {"raw_answer": "placeholder"},
  "review": {"action": "PASS"}
}
```

HUMAN_REVIEW:

```json
{
  "query_id": "uuid",
  "status": "human_review",
  "routing": {"needs_clarification": false},
  "evidence": {"evidence": [], "warnings": [], "conflicts": []},
  "reasoning": {"raw_answer": "placeholder"},
  "review": {"action": "HUMAN_REVIEW"}
}
```

Needs clarification:

```json
{
  "query_id": "uuid",
  "status": "needs_clarification",
  "routing": {
    "needs_clarification": true,
    "clarification_reason": "Please provide a machine id."
  },
  "evidence": null,
  "reasoning": null,
  "review": null
}
```

## Validation And Errors

FastAPI/Pydantic validation errors use normal HTTP `422` responses.

Semantic clarification from the routing engine is not an HTTP validation error;
it returns HTTP `200` with `status = "needs_clarification"`.

`PASS` and `HUMAN_REVIEW` both return HTTP `200`.

Unexpected internal failures return HTTP `500` with a generic public error. The
public response does not include tracebacks, filesystem paths, SQL, provider
payloads, or secrets.

## CORS

CORS is configured from `Settings.cors_allowed_origins`. The default is:

```python
["http://localhost:5173"]
```

Credentials are disabled in STEP 16. No wildcard credentialed CORS policy is
used.

## OpenAPI

FastAPI generates OpenAPI automatically. The schema includes:

- `/health`
- `/ready`
- `/api/query`

No separate hand-maintained OpenAPI JSON file exists.

## Out Of Scope

STEP 16 does not implement:

- client auth, JWT, OAuth, API keys, sessions, RBAC
- streaming, SSE, WebSockets, token streaming
- background jobs
- file upload
- database or repository CRUD endpoints
- SQL browser endpoints
- RAG rebuild/admin endpoints
- frontend React files

## Testing

API tests use fake orchestrators and run without `TYPESAFE_API_KEY`,
`GEMINI_API_KEY`, network access, Qdrant startup, DB validation, or RAG
validation.

