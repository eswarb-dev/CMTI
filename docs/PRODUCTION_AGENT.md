# STEP 10 - ProductionAgent

## Purpose

`ProductionAgent` (`backend/app/agents/production.py`) answers exactly one
question:

> "What production-order and production-output evidence exists for
> the specified machine, product, batch and/or time window?"

It exposes deterministic facts — production orders, quantities
(planned/actual/accepted/rejected), reject rates, statuses, timestamps,
and aggregate rejection summaries. It performs **no diagnosis**: no
root causes, no KPIs like OEE, no LLM, no RAG, no fusion.
Sufficiency and interpretation belong to later Reasoner stages.

## Input requirements

The agent is production-centric. It uses only structured fields:

- `machine_id` (optional),
- `product_id` (optional),
- `batch_id` (optional),
- `time_start` / `time_end` (optional windows).

At least one of `machine_id`, `product_id`, or `batch_id` must be
provided. `user_context` is ignored for identity resolution. Query text
is **never** parsed for machine/product/batch identity — no regex, no
entity extraction.

## Missing-scope behavior

If all three structured scope identifiers are `None`, the agent performs
zero repository calls and returns `evidence=[]` with the warning
`"At least one structured production scope..."` and
`retrieval_status="missing_scope"`.

## Dependencies

Constructor-injected `ProductionRepository` (actual STEP 05 class) plus
existing `Settings`. No DI framework.

```python
ProductionAgent(
    production_repository: ProductionRepository,
    *,
    settings=None,
    order_limit=None,
)
```

`build_production_agent(settings, database_path)` wires the canonical
operational database without a DI framework.

## Configuration

| Setting | Default | Meaning |
| --- | --- | --- |
| `production_agent_order_limit` | `12` | production orders per scope |

All via existing `Settings`; invalid values raise `ValueError` at
construction.

## Production-order Evidence mapping

One `Evidence` per row:

| Field | Value |
| --- | --- |
| `evidence_id` | `EVIDENCE-PRODUCTION-<production_id>` (deterministic) |
| `source_type` | `PRODUCTION` |
| `provenance` | `source_kind=DEMO_FACTORY`, `source_dataset` from the row, `source_id=record_id=<production_id>`, document/chunk/page fields null |
| `machine_id` / `product_id` / `batch_id` | row values (preserved, not replaced by query values) |
| `title` | `"Production <production_id> — <product_id> — <machine_id> — <status>"` |
| `content` | factual fields: production ID, batch/machine/product IDs, status, planned/actual/accepted/rejected quantities, reject rate, timestamps, cycle time, shift |
| `observed_at` | `actual_start_time` from the production record |
| `retrieval_score` / `decision_score` | null (structured evidence is not vector retrieval) |
| `metadata` | `record_type=production_order`, production_status, is_synthetic, shift, cycle_time_sec |

## Rejection Summary Evidence mapping

One aggregate `Evidence` per run, from `ProductionRepository.summarize_rejections()`
with the provided machine_id/product_id/time filters:

- `evidence_id`: `EVIDENCE-PRODUCTION-SUMMARY-<sha12(machine|product|time|schema)>`
- `source_id`: `PRODUCTION-SUMMARY-<sha12>` (deterministic)
- `record_id`: null; `source_type`: `PRODUCTION`
- `content`: order count, total actual/accepted/rejected quantities, reject rate
- `metadata`: `aggregation=production_summary`, scope fields, time bounds, order_count, quantities

**Note**: `summarize_rejections` does NOT support `batch_id`. Batch-only
scopes produce order evidence via `get_by_batch_id` but no summary.

## Repository capability matrix

| Scope | General retrieval | Rejection summary |
| --- | --- | --- |
| machine_id only | `list_by_machine(machine_id, time_start, time_end, limit)` | `summarize_rejections(machine_id=machine_id, start_time, end_time)` |
| product_id only | `list_by_product(product_id, time_start, time_end, limit)` | `summarize_rejections(product_id=product_id, start_time, end_time)` |
| machine_id + product_id | `list_by_machine_and_product(machine_id, product_id, time_start, time_end, limit)` | `summarize_rejections(machine_id, product_id, time_start, time_end)` |
| batch_id only | `get_by_batch_id(batch_id)` (single record) | Not supported |
| batch_id + machine_id/product_id | `get_by_batch_id(batch_id)` + verify match | Not supported |

**Key limitation**: `summarize_rejections` does not support `batch_id`.
Batch-only scopes produce order evidence but no aggregate summary.
Combined batch_id + other scopes use `get_by_batch_id` with filter
verification, and no summary is produced.

## Scope selection

Uses the most specific exact repository capability available:
- machine_id + product_id → `list_by_machine_and_product`
- machine_id only → `list_by_machine`
- product_id only → `list_by_product`
- batch_id only → `get_by_batch_id`
- batch_id + other → `get_by_batch_id` with filter verification

All supplied filters are respected. No filter is silently ignored.

## Evidence ordering

Deterministic documented grouping:
1. Production/rejection summary (if available)
2. Individual production orders

Within record groups: repository ordering preserved. No relevance ranking.

## Scores

Structured production evidence is not vector retrieval. For all STEP 10
evidence: `retrieval_score = null`, `decision_score = null`. No confidence
values are invented.

## AgentResult statuses

- `ok` — all sources completed, evidence present
- `empty` — completed, nothing found
- `partial` — some source failed, others completed
- `missing_scope` — no structured scope provided
- `failed` — nothing completed

## Failure isolation

Each source has an independent boundary catching `DatabaseError` (covers
`RepositoryError`), `ConnectionError`, `TimeoutError`. A failed source
contributes an error entry plus a partial-result warning while successful
sources are preserved. Unexpected defects propagate.

## Boundaries

No LLM/SDK imports, no `app.rag`/`DocumentRetriever`/`DocumentAgent`/`QualityAgent`/`MaintenanceAgent`, no
maintenance/production/external repositories other than `ProductionRepository`, no `sqlite3`/`aiosqlite`/SQL
strings (both statically tested), no OEE/KPI calculations, no quality
correlation, no maintenance correlation, no root-cause inference.

## Tests

`backend/tests/agents/test_production_agent.py` (50 tests): unit behaviors
with fake repositories, static dependency + SQL boundary tests, frozen-contract
identity, and 4 read-only integration cases against the canonical DB
(CNC-05 machine scope, SHAFT-A product scope, BATCH scope, rejection
summary) asserting factual presence/provenance only.

## Known limitations

- `summarize_rejections` does not support `batch_id`.
- `get_by_batch_id` returns a single record, not a paginated list.
- Combined batch_id + other scopes cannot be represented exactly;
  `get_by_batch_id` is used with filter verification.
- Repository-level (non-`DatabaseError`) driver failures propagate
  instead of degrading.
- `user_context` is not used for structured identity resolution.
