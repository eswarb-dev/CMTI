# STEP 14 — Jev Final Review Gate

## Purpose

`JevDecisionEngine.review()` (`backend/app/decision/jev.py`) implements the frozen `DecisionEngine.review()` protocol. It determines whether a `ReasoningResult` is safe and sufficiently supported to PASS automatically, or should be sent to HUMAN_REVIEW.

**Critical boundary**: STEP 14 does NOT rewrite reasoning, generate better answers, retrieve evidence, execute agents, or perform final approval. It decides disposition only.

## Frozen Protocol Signature

```python
async def review(
    self,
    query: QueryRequest,
    bundle: EvidenceBundle,
    reasoning: ReasoningResult,
) -> ReviewDecision
```

## ReviewDecision Fields

| Field | Type | Required | Source |
|---|---|---|---|
| `query_id` | `str` | Yes | From inputs |
| `action` | `ReviewAction` | Yes | Application (PASS or HUMAN_REVIEW) |
| `reasons` | `list[str]` | Yes | Application (triggered check codes) |
| `confidence` | `float \| None` | No | Always None |
| `provider_status` | `ProviderStatus` | Yes | Application |
| `metadata` | `dict[str, Any]` | No | Application (diagnostics) |

## Configuration

| Setting | Default | Meaning |
|---|---|---|
| `jev_review_threshold` | `0.50` | Issue score cutoff |
| `jev_review_enabled` | `true` | Enable/disable review |

Reuses STEP 11: `jev_model`, `jev_timeout_seconds`, `jev_max_retries`, `jev_enabled`, `typesafe_api_key`.

## Four Noul Review Questions

| Question | Issue Code | Focus |
|---|---|---|
| `review_grounding_failure` | `grounding_failure` | Unsupported/overstated claims |
| `review_causal_overreach` | `causal_overreach` | Correlation presented as causation |
| `review_conflict_gap_failure` | `conflict_gap_failure` | Ignored material conflicts/gaps |
| `review_safety_failure` | `safety_failure` | Unsafe/unbounded recommendations |

## Deterministic Prechecks

Before any provider call:

1. **Query ID consistency** — query/bundle/reasoning query_ids must match
2. **Reasoning provider status** — UNAVAILABLE/ERROR → HUMAN_REVIEW
3. **Empty reasoning** — no observations/causes/checks → HUMAN_REVIEW
4. **Citation integrity** — all citations must reference bundle evidence IDs

Any precheck failure → HUMAN_REVIEW without provider call.

## PASS Rule

PASS requires:
- All deterministic prechecks pass
- Provider call succeeds
- All four issue scores below threshold

## HUMAN_REVIEW Rule

HUMAN_REVIEW when:
- Any issue score >= threshold
- Any deterministic precheck fails
- Provider review unavailable/invalid

## Fail-Closed Policy

Provider uncertainty/failure NEVER becomes PASS. Conservative fallback is always HUMAN_REVIEW.

## Issue Score Semantics

- Score >= threshold → issue triggered
- Threshold equality is inclusive (>=)
- Multiple issues preserved in stable order

## Conflicts Behavior

EvidenceBundle.conflicts does NOT automatically require HUMAN_REVIEW. A correctly cautious Gemini response may already acknowledge the conflict. The `review_conflict_gap_failure` question judges whether reasoning mishandles a material conflict.

## Missing Information Behavior

`missing_information` is not itself a failure. Review detects whether material gaps were IGNORED, not whether any gap exists.

## Possible Causes Behavior

`possible_causes` do NOT force HUMAN_REVIEW. A possible cause may PASS when clearly hypothetical, grounded, and not overstated.

## Privacy

Never sent: API keys, filesystem paths, vector embeddings, hidden ground truth, arbitrary user_context, application logs.

## STEP 11 Stub Warning

`score_evidence()` remains a STEP 11 placeholder. STEP 14 does NOT implement it.

## Tests

- `tests/decision/test_jev_review_gate.py` — 67 offline unit tests

## Known Limitations

- No live review tests (all offline)
- `confidence` always None (no deterministic derivation rule)
- Review is single-turn and stateless
