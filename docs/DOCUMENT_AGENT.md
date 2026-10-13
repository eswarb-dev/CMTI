# STEP 07 - DocumentAgent

## Purpose

`DocumentAgent` (`backend/app/agents/document.py`) answers exactly one question:

> "What document evidence is relevant?"

It wraps the STEP 06 `DocumentRetriever` and returns frozen STEP 04
`AgentResult` objects. It performs **no engineering reasoning**: no diagnosis,
no root causes, no summarisation, no LLM calls, no database access, no
cross-agent coordination, no evidence fusion. Sufficiency judgments
("sufficient/insufficient evidence") belong to future Evidence Fusion /
Reasoner stages.

## Input

A frozen `QueryRequest` (`query_id`, `query`, optional `machine_id` /
`product_id` / `batch_id`, `user_context`). The request is forwarded
**unchanged** to the retriever — the agent adds no filters and performs no
machine-to-manual mapping.

## Dependency

The agent depends only on the frozen `DocumentRetriever` protocol:

```python
DocumentAgent(retriever: DocumentRetriever, *, top_k: int | None = None,
              settings: Settings | None = None)
```

It never instantiates Qdrant, embedding models, repositories, other agents,
or providers. `build_document_agent(settings)` is a thin construction helper
that wires the canonical `DocumentRetrieverImpl`; no DI framework, no FastAPI
wiring.

## Execution flow

```
QueryRequest
    ↓
DocumentAgent
    ↓
DocumentRetriever
    ↓
Hierarchical RAG / Qdrant
    ↓
Evidence[]
    ↓
AgentResult
```

1. Start a monotonic timer (`time.perf_counter`).
2. `await retriever.retrieve(query, top_k=self._top_k)` with the original query.
3. Package the returned `Evidence` list unchanged (same objects, same order)
   into `AgentResult(agent_name=AgentName.DOCUMENT, query_id=query.query_id,
   ...)`.

`top_k` defaults to `document_agent_top_k = 8` (existing `Settings` system, no
second config loader) and must stay within the retriever's maximum; the
retriever owns clamping. Non-integer or `< 1` values raise `ValueError` at
construction.

## AgentResult output

| Field | Value |
| --- | --- |
| `agent_name` | `AgentName.DOCUMENT` |
| `query_id` | exactly the request's `query_id` |
| `evidence` | retriever output, unchanged and unranked |
| `warnings` | `"No document evidence retrieved."` when empty; `"Retriever returned N of K requested evidence items."` when short |
| `errors` | only on expected retrieval failures (below) |
| `latency_ms` | non-negative float, always populated |
| `metadata` | `retrieved_count`, `requested_top_k`, `retriever` (class name), `retrieval_status` (`ok` / `empty` / `failed`) |

No thresholds are applied to `retrieval_score`; no `decision_score` is ever set.

## Error behavior

Expected retrieval-layer failures (`RetrievalError`,
`ProviderUnavailableError`, `ConnectionError`, `TimeoutError`) produce a
successful-shape `AgentResult` with `evidence=[]`, one concise error
(`"Document retrieval failed: …"`, no stack traces or internals) and
`retrieval_status="failed"`. Unexpected programming defects propagate
uncaptured so they stay visible in development and tests.

## No-evidence behavior

A successful retrieval returning `[]` yields `evidence=[]` with the
`"No document evidence retrieved."` warning — never fabricated evidence and
never an error for the absence of matches.

## Configuration

| Setting | Default | Meaning |
| --- | --- | --- |
| `document_agent_top_k` | `8` | evidence budget per run; retriever clamps to `rag_max_top_k` |

## Boundaries

- No `app.repositories`, `app.db`, `app.reasoning`, `app.decision`,
  `app.orchestration`, LLM/Provider SDK, or LangGraph imports (statically
  tested).
- `machine_id` / `product_id` / `batch_id` are passed through but never
  converted into document filters.
- Frozen contracts and the STEP 06 RAG subsystem are untouched.

## Tests

`backend/tests/agents/test_document_agent.py` (34 tests): protocol shape,
agent name, query-id preservation, request/top-k/user-context/identity
pass-through, evidence and score preservation, `decision_score` absence,
empty/failure/unexpected-error paths, latency, metadata, duplication,
static dependency boundary, frozen-contract identity, and 4 read-only
integration queries against the canonical index (shared-nothing per test to
respect the single-client Qdrant guard).

## Known limitations

- Returns the best retrieved evidence even when the corpus has no dedicated
  procedure (e.g. spindle lubrication); sufficiency is a later stage's job.
- Default budget of 8 is a heuristic, not a relevance guarantee.
- Retrieval infrastructure failures outside the expected set propagate
  instead of degrading gracefully.
