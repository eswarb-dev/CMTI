# STEP 09 - QualityAgent

## Purpose

`QualityAgent` (`backend/app/agents/quality.py`) answers exactly one
question:

> "What quality inspection evidence exists for the specified machine,
> product, batch and/or time window?"

It exposes deterministic facts — inspection results, measured values,
nominal values, LSL/USL, pass/fail status, defect types, inspection
methods, and aggregate statistics. It performs **no diagnosis**: no
root causes, no SPC, no thresholds, no LLM, no RAG, no fusion.
Sufficiency and interpretation belong to later Reasoner stages.

## Input requirements

The agent is quality-centric. It uses only structured fields:

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
`"At least one structured quality scope (batch_id, machine_id, or
product_id) is required..."` and `retrieval_status="missing_scope"`.

## Scope selection policy

Uses the most specific exact repository capability available:

| Scope provided | General inspection method | Failure method | Summary |
| --- | --- | --- | --- |
| batch_id only | `list_by_batch(batch_id, limit)` | `list_failures(batch_id=batch_id)` | `summarize_results(batch_id=batch_id)` |
| machine_id only | `list_by_machine(machine_id, time_start, time_end, limit)` | `list_failures(machine_id=machine_id)` | `summarize_results(machine_id=machine_id)` |
| product_id only | `list_by_product(product_id, time_start, time_end, limit)` | `list_failures(product_id=product_id)` | `summarize_results(product_id=product_id)` |
| Combined scopes | No single general method covers all → only failures via `list_failures` and summaries via `summarize_results` | Same | Same |

**Critical limitation**: `list_by_batch` does not support time_range, and
no general (non-failure) repository method supports combined machine_id +
product_id filtering. For combined scopes, the agent exposes failure
evidence and aggregate summaries (both support all filters) but does not
retrieve general inspection records, ensuring no filter is silently
ignored.

## Dependencies

Constructor-injected `QualityRepository` (actual STEP 05 class) plus
existing `Settings`. No DI framework.

```python
QualityAgent(
    quality_repository: QualityRepository,
    *,
    settings=None,
    inspection_limit=None,
    failure_limit=None,
)
```

`build_quality_agent(settings, database_path)` wires the canonical
operational database without a DI framework.

## Configuration

| Setting | Default | Meaning |
| --- | --- | --- |
| `quality_agent_inspection_limit` | `12` | general inspection rows per scope |
| `quality_agent_failure_limit` | `8` | failed inspection rows per scope |

All via existing `Settings`; invalid values raise `ValueError` at
construction.

## Inspection Evidence mapping

One `Evidence` per row:

| Field | Value |
| --- | --- |
| `evidence_id` | `EVIDENCE-QUALITY-<inspection_id>` (deterministic) |
| `source_type` | `QUALITY` |
| `provenance` | `source_kind=DEMO_FACTORY`, `source_dataset` from the row, `source_id=record_id=<inspection_id>`, document/chunk/page fields null |
| `machine_id` / `product_id` / `batch_id` | row values (preserved, not replaced by query values) |
| `title` | `"Quality <inspection_id> — <product_id> — <parameter> — <result>"` |
| `content` | factual fields only: inspection ID, batch/machine/product IDs, timestamp, parameter, nominal/LSL/USL/measured values, result, defect type, inspection method |
| `observed_at` | `timestamp` from the inspection row |
| `retrieval_score` / `decision_score` | null (structured evidence is not vector retrieval) |
| `metadata` | `record_type=quality_inspection`, parameter, result, defect_type, inspection_method, is_synthetic |

## Summary Evidence mapping

One aggregate `Evidence` per run, from `QualityRepository.summarize_results()`
with all provided scope filters:

- `evidence_id`: `EVIDENCE-QUALITY-SUMMARY-<sha12(machine|product|batch|time|schema)>`
- `source_id`: `QUALITY-SUMMARY-<sha12>` (deterministic)
- `record_id`: null; `source_type`: `QUALITY`
- `content`: inspection/pass/fail counts, failure rate, per-parameter stats
- `metadata`: `aggregation=quality_summary`, scope fields, time bounds, inspection_count, parameters present
- Per-parameter statistics preserved (never averaged across parameters)

## Failure Record retrieval

If `list_failures` supports the selected exact scope, it is used to expose
bounded failed-inspection evidence. The repository already validates
`result = 'PASS'` vs `result = 'FAIL'` via LSL/USL constraints.

## Duplicate inspection handling

If the same inspection appears in both general retrieval and failure
retrieval, it is emitted only once, deduplicated by `inspection_id`. This
is identity deduplication, not semantic reranking.

## Evidence ordering

Deterministic documented grouping:

1. Quality summary
2. Failed inspection records
3. Remaining general inspection records (deduplicated)

Within record groups: repository ordering preserved. No relevance ranking.

## Scores

Structured quality evidence is not vector retrieval. For all STEP 09
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

No LLM/SDK imports, no `app.rag`/`DocumentRetriever`/`DocumentAgent`/`MaintenanceAgent`, no
maintenance/production/external repositories. `QualityRepository` remains
the sole structured-data dependency. No `sqlite3`/`aiosqlite`/SQL
strings (both statically tested), no SPC/Cp/Cpk, no production reject
metrics, no maintenance correlation, no external dataset mixing.

## Tests

`backend/tests/agents/test_quality_agent.py` (49 tests): unit behaviors with
fake repositories, static dependency + SQL boundary tests, frozen-contract
identity, and 3 read-only integration cases against the canonical DB
(SHAFT-A product scope, CNC-05 machine scope with time window, BATCH scope,
failed inspections) asserting factual presence/provenance only.

## Known limitations

- `list_by_batch` does not support time_range.
- No general (non-failure) repository method supports combined
  machine_id + product_id filtering; combined scopes expose only failure
  evidence and summaries.
- Repository-level (non-`DatabaseError`) driver failures propagate instead
  of degrading.
- `user_context` is not used for structured identity resolution.
