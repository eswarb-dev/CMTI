# STEP 12 — Deterministic Evidence Fusion

## Purpose

`DeterministicEvidenceFusionService` (`backend/app/fusion/service.py`) implements the frozen `EvidenceFusionService` protocol. It collects, validates, deduplicates, and orders evidence from multiple agents into a single deterministic `EvidenceBundle`.

**Critical boundary**: Evidence Fusion does NOT determine truth, diagnose, choose winning evidence, or assign confidence. It organizes and validates evidence for the future Reasoner.

## Frozen Protocol Signature

```python
async def fuse(self, query: QueryRequest, agent_results: list[AgentResult]) -> EvidenceBundle
```

## Input

- `query: QueryRequest` — supplies `query_id` and context
- `agent_results: list[AgentResult]` — results from selected agents

## Output: EvidenceBundle

| Field | Type | Description |
|---|---|---|
| `query_id` | `str` | From `QueryRequest.query_id` |
| `evidence` | `list[Evidence]` | Fused, deduplicated, ordered evidence |
| `conflicts` | `list[EvidenceConflict]` | Source-integrity conflicts |
| `missing_information` | `list[str]` | Always empty (no routing awareness) |
| `warnings` | `list[str]` | Compact agent-level diagnostics |
| `metadata` | `dict[str, Any]` | Counts and diagnostics |

## Canonical Agent Ordering

1. DOCUMENT
2. MAINTENANCE
3. QUALITY
4. PRODUCTION

Unknown/future agents sort after these four, ordered by `AgentName` value. Completion order never affects bundle order.

## Deduplication Rules

**Primary key**: `Evidence.evidence_id` — identical IDs with identical payloads emit once.

**Secondary key**: Provenance identity (source_kind + source_dataset + source_id + record_id + document_id + chunk_id + page_start + page_end) — same provenance with identical payloads deduplicates.

**NOT deduplicated**:
- Different record IDs with identical text
- Aggregate evidence vs raw records
- Different document chunks
- Same alarm description with different alarm IDs

## Source-Integrity Conflict Detection

Conflicts detected when the SAME source identity appears with incompatible facts:
- Same `evidence_id` with different payload → `factual_payload_mismatch`
- Same provenance with contradictory identity fields → `source_identity_mismatch`
- Same provenance with different factual fields → `factual_payload_mismatch`

**NOT conflicts**:
- Quality PASS vs FAIL from different inspections
- Different telemetry periods
- Different production orders
- Cross-domain factual differences

## Score Preservation

- `retrieval_score` — preserved exactly as supplied by agents
- `decision_score` — preserved exactly as supplied by agents
- No normalization, no comparison across source types
- No new scoring fields introduced

## AgentResult Partial-Error Behavior

- Evidence from agents with errors is preserved
- Agent errors/warnings carried into bundle warnings
- Zero-evidence results contribute no Evidence
- Warnings/errors never become Evidence

## Determinism & Idempotency

- Same logical input → same output regardless of completion order
- No timestamps introduced
- No UUIDs — conflict IDs use SHA-256
- Input objects never mutated

## Privacy Boundaries

- No Jev calls
- No DecisionEngine calls
- No agent execution
- No repository/DB/RAG access
- No LLM dependencies
- No hidden ground truth access

## STEP 11 Stub Warning

`JevDecisionEngine.score_evidence()` and `JevDecisionEngine.review()` are placeholders from STEP 11. EvidenceFusionService does NOT invoke them. STEP 14 addresses Jev final review separately.

## Tests

- `tests/fusion/test_evidence_fusion.py` — 55 offline unit tests

## Known Limitations

- No RoutingDecision input (fusion cannot know expected agents)
- No EvidenceCitation contract exists in frozen contracts
- `missing_information` always empty (no semantic gap detection)
