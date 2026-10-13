# Structured Record Identity + Provenance Hardening (STEP 19A)

## STEP 18B finding

Offline core `record_identity_recall = 0.445` (MULTI-CASE-001: 0.538).
Expected `QI-*` / `TEL-*` record identities were not surfaced in evidence
provenance, while `PRODORD-*`, `MNT-*`, `ALM-*` were found.

## Diagnostic matrix

| Missing family | Individual evidence preserves ID? | Repository exposes ID? | Verdict |
|---|---|---|---|
| `QI-*` | Yes (`record_id` = `inspection_id`, verified for returned rows, e.g. QI-000569) | Yes (canonical `inspection_id`, deterministic `ORDER BY timestamp DESC, inspection_id DESC LIMIT 8`) | **E** — evaluation expects 13 specific historical rows; frozen design returns summary + 8 most recent failures |
| `TEL-*` | N/A — no individual telemetry evidence exists | Yes (canonical `telemetry_id`, 38,379 rows) | **D** — telemetry evidence is summary-only by design; one summary cannot name individual rows |
| `MNT-*` / `ALM-*` | Yes (`record_id` = `maintenance_id` / `alarm_id`) | Yes | No defect (found in evaluation) |
| `PRODORD-*` | Yes (`record_id` = `production_id`) | Yes | No defect (found in evaluation) |

Root-cause classes A (agent drops ID), B (wrong field), C (repository omits
ID) were **disproven** for all individual-row evidence. Fusion preserves
provenance (it keys deduplication on provenance identity; validity 1.000).

## Canonical identity mapping

| Evidence | Repository field | `EvidenceProvenance.source_id` | `record_id` |
|---|---|---|---|
| Quality inspection row | `QualityRecord.inspection_id` | inspection ID | inspection ID |
| Maintenance row | `MaintenanceRecord.maintenance_id` | maintenance ID | maintenance ID |
| Alarm row | `AlarmRecord.alarm_id` | alarm ID | alarm ID |
| Production row | `ProductionRecord.production_id` | production ID | production ID |
| Quality/alarm/telemetry summary | digest of scope+window | `<KIND>-SUMMARY-<digest>` | `None` (truthful aggregate) |

Identity field: `EvidenceProvenance.record_id` (with `source_id` mirroring it
for individual rows). Validators and nullability unchanged (STEP 04 frozen).

## Aggregate-evidence semantics

Aggregates (quality summary, alarm recurrence count, telemetry summary) cover
many rows and MUST NOT claim one arbitrary member row ID. They use
`record_id=None`, a `*-SUMMARY-<digest>` source ID, and explicit
`aggregation` metadata. The frozen contract has no contributor-list field;
adding one is out of scope — recorded as **PROVENANCE CONTRACT LIMITATION**
for telemetry summaries (38k contributors cannot be enumerated per item).

## What was fixed

Nothing in production: diagnosis proved no identity is lost for evidence that
directly represents an identifiable record. Changing limits, ranking, or
expectations to chase the score is forbidden by the STEP 19A charter.

## What remains unrepresentable

- Individual `TEL-*` identities inside telemetry summaries (contract limitation D).
- Exhaustive historical `QI-*` sets beyond frozen top-k evidence budgets (design E).

## Before/after metrics

`record_identity_recall`: 0.445 → unchanged (no production change; finding
stands as documented). All other STEP 18B metrics verified non-regressed.

## Tests

`backend/tests/agents/test_record_identity_provenance.py` (14 tests): per-type
identity preservation, repository agreement, no index-derived IDs, aggregate
truthfulness, no-fabrication negatives, evaluation-truth firewall over
agents/repositories/fusion.

## Limitations

- Recall remains < 1.0 for the documented D/E reasons.
- No claim is made about industrial audit sufficiency beyond the measured scope.
