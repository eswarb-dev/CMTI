# STEP 08 - MaintenanceAgent

## Purpose

`MaintenanceAgent` (`backend/app/agents/maintenance.py`) answers exactly one
question:

> "What maintenance, alarm and machine-condition evidence exists for this
> machine and requested time period?"

It exposes deterministic facts — maintenance history, inspection findings,
performed actions, alarm events, repeated-alarm counts, telemetry
min/max/mean/first/last aggregates. It performs **no diagnosis**: no root
causes, no thresholds, no health scores, no LLM, no RAG, no fusion.
Sufficiency and interpretation belong to later Reasoner stages.

## Input requirements

The agent is machine-centric. It uses only structured fields:

- `machine_id` (required structurally),
- `time_start` / `time_end` (optional windows).

`product_id` / `batch_id` are ignored for retrieval. Query text is **never**
parsed for machine identity — no regex, no entity extraction.

## machine_id policy

If `machine_id` is `None`, the agent performs zero repository calls and
returns `evidence=[]` with the warning `"machine_id is required for
maintenance evidence; no repository queries were performed."` and
`retrieval_status="missing_machine_id"`. This is not an error; a future
API/orchestration layer may populate the field.

## Dependencies

Constructor-injected, protocol-shaped repositories (actual STEP 05 classes):

```python
MaintenanceAgent(
    maintenance_repository: MaintenanceRepository,
    alarm_repository: AlarmRepository,
    telemetry_repository: TelemetryRepository,
    *, settings=None, maintenance_limit=None, alarm_limit=None,
    telemetry_lookback_hours=None, alarm_summary_limit=None,
)
```

`build_maintenance_agent(settings, database_path)` wires the canonical
operational database without a DI framework. No raw SQL lives in the agent;
only repository methods are called.

## Maintenance Evidence mapping

One `Evidence` per row, repository order preserved:

| Field | Value |
| --- | --- |
| `evidence_id` | `EVIDENCE-MAINTENANCE-<maintenance_id>` (deterministic) |
| `source_type` | `MAINTENANCE` |
| `provenance` | `source_kind=DEMO_FACTORY`, `source_dataset` from the row, `source_id=record_id=<maintenance_id>`, document/chunk/page fields null |
| `machine_id` | row value; `product_id`/`batch_id` null (absent in source) |
| `title` | `Maintenance <id> — <machine> — <type>` |
| `content` | present factual fields only (type, symptom, component, failure code, findings, action, status, downtimes, timestamps) |
| `observed_at` | `started_at`, else `created_at`, never invented |
| `retrieval_score` / `decision_score` | null (structured evidence is not vector retrieval) |
| `metadata` | `record_type`, `is_synthetic`, `maintenance_type`, `status` |

## Alarm Evidence mapping

One `Evidence` per row: `EVIDENCE-ALARM-<alarm_id>`, `source_type=ALARM`,
`source_id=record_id=<alarm_id>`, `observed_at` = alarm timestamp, content
with code/severity/category/description/timestamp/acknowledgement/related
batch — never translated into a diagnosis.

## Alarm recurrence Evidence

For each distinct alarm code in the bounded retrieved set (first-seen order),
the agent calls `AlarmRepository.count_occurrences(...)` over the query
window — never the truncated list length. A summary item is emitted only
when `count > 1`, capped at `maintenance_agent_alarm_summary_limit` items:

- `evidence_id`: `EVIDENCE-ALARM-SUMMARY-<machine>-<code>-<sha12>`
- `source_id`: `ALARM-SUMMARY-<machine>-<code>-<sha12>` (stable SHA-256 suffix, never `hash()`)
- `record_id`: null; `source_type`: `ALARM`
- content: `"Alarm <code> occurred <N> times for <machine> between <start> and <end>."` (or `" across all recorded history."` when unbounded)
- metadata: `record_type=alarm_summary`, `aggregation=count`, code, count, window

## Telemetry-summary Evidence

At most one item per run, from `TelemetryRepository.summarize(...)` over the
resolved window — never hundreds of raw rows:

- `evidence_id`: `EVIDENCE-TELEMETRY-SUMMARY-<machine>-<sha12(machine|start|end|telemetry_summary_v1)>`
- `source_type`: `TELEMETRY`, `record_id`: null, `observed_at`: window end
- content: per available metric (`rpm`, `vibration_mm_s`, `temperature_c`, `current_a`, `load_pct`, `spindle_power_kw`) with `count/min/max/mean/first/last`
- metadata: `aggregation=summary`, window bounds, metric names, `sample_count`
- No words like normal/abnormal/high/overheating appear anywhere: no approved industrial thresholds exist in this project.

## Time-window resolution

Maintenance/alarms: query window when either bound exists
(`list_by_machine_and_time_range`), else `recent_for_machine` with the
configured limit. Telemetry (`summarize` requires a bounded window):

| Query bounds | Resolved window |
| --- | --- |
| start + end | exactly `(start, end)` |
| start only | `(start, latest)` iff `latest >= start`, else no telemetry + warning |
| end only | `(end − lookback, end)` |
| neither | `(latest − lookback, latest)`; no latest sample → warning, other evidence kept |

## Configuration

| Setting | Default | Meaning |
| --- | --- | --- |
| `maintenance_agent_maintenance_limit` | `8` | maintenance rows per run |
| `maintenance_agent_alarm_limit` | `10` | alarm rows per run |
| `maintenance_agent_telemetry_lookback_hours` | `168` | 7-day prototype retrieval window (NOT an industrial threshold) |
| `maintenance_agent_alarm_summary_limit` | `5` | max recurrence summaries per run |

All via existing `Settings`; invalid values raise `ValueError` at construction.

## AgentResult behavior

Evidence order is fixed and documented: maintenance records, alarm
recurrence summaries, alarm records, telemetry summary; repository order
within groups; no relevance ranking. `agent_name=MAINTENANCE`,
`query_id` echoed. `retrieval_status`: `ok` (all sources completed, evidence
present), `empty` (completed, nothing found), `partial` (some source failed,
others completed), `missing_machine_id`, `failed` (nothing completed).
Warnings cover missing machine, empty sources, shortfalls, and partial
availability — never numeric thresholds.

## Failure isolation

Each source has an independent boundary catching `DatabaseError` (covers
`RepositoryError`), `ConnectionError`, `TimeoutError`. A failed source
contributes an error entry plus a partial-result warning while successful
sources are preserved; unexpected defects propagate. Telemetry absence never
fails the whole run.

## Boundaries

No LLM/SDK imports, no `app.rag`/`DocumentRetriever`/`DocumentAgent`, no
quality/production/external repositories, no `sqlite3`/`aiosqlite`/SQL
strings (both statically tested), no fusion, no cross-domain relationships.

## Tests

`backend/tests/agents/test_maintenance_agent.py` (49 tests): the 38 required
unit behaviors with fake repositories, static dependency + SQL boundary
tests, frozen-contract identity, and 3 read-only integration cases against
the canonical DB (CNC-05 full window, CNC-03 full window, ALM-VIB-01
recurrence) asserting factual presence/provenance only — never simulated
causes, never `demo_cases.json`.

## Known limitations

- Requires an explicit `machine_id`; cannot resolve identity from text.
- Telemetry resolves to one summary per run; raw samples are not exposed.
- Recurrence counting issues one `COUNT(*)` per distinct code (bounded by the summary limit).
- Repository-level (non-`DatabaseError`) driver failures propagate instead of degrading.
