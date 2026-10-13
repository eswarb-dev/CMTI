# STEP 13 — Grounded Gemini Reasoner

## Purpose

`GeminiReasoner` (`backend/app/reasoning/gemini.py`) implements the frozen `Reasoner` protocol. It interprets a supplied `EvidenceBundle` using the official `google-genai` Interactions API and returns a frozen `ReasoningResult`.

**Critical boundary**: Gemini receives ONLY the query and fused evidence supplied by the application. It does not search for additional manufacturing facts, call tools, query databases, access RAG, execute agents, or control equipment.

## Frozen Protocol Signature

```python
async def reason(self, query: QueryRequest, evidence: EvidenceBundle) -> ReasoningResult
```

## ReasoningResult Fields

| Field | Type | Required | Source |
|---|---|---|---|
| `query_id` | `str` | Yes | Application (from QueryRequest) |
| `observations` | `list[str]` | Yes | Gemini (grounded claims) |
| `possible_causes` | `list[str]` | Yes | Gemini (hypothetical claims) |
| `recommended_checks` | `list[str]` | Yes | Gemini (verification steps) |
| `missing_information` | `list[str]` | Yes | Gemini + application |
| `citations` | `list[EvidenceCitation]` | Yes | Application (from valid evidence IDs) |
| `raw_answer` | `str` | Yes | Gemini |
| `provider_status` | `ProviderStatus` | Yes | Application |
| `model` | `str \| None` | No | Application (configured model) |
| `metadata` | `dict[str, Any]` | No | Application (diagnostics) |

## Official SDK

- **Package**: `google-genai>=2.22.0,<3`
- **Installed version**: `2.25.0`
- **API**: Interactions API (`client.aio.interactions.create`)
- **Text extraction**: successful completed interactions use `interaction.output_text`
  as the primary and only response-text extraction path.
- **Default model**: `gemini-3.8-flash`
- **Default thinking**: `medium`
- **Environment**: `GEMINI_API_KEY`

## Configuration

| Setting | Default | Meaning |
|---|---|---|
| `gemini_model` | `"gemini-3.8-flash"` | Model alias |
| `gemini_enabled` | `true` | Enable/disable provider |
| `gemini_thinking_level` | `"medium"` | Thinking level (low/medium/high) |
| `gemini_timeout_seconds` | `90.0` | Request timeout |
| `gemini_max_output_tokens` | `8192` | Output token limit |
| `gemini_max_retries` | `1` | Bounded retry count |
| `gemini_api_key` | `None` | API key from environment |

## Provider Input Schema

```json
{
  "query": {
    "query_id": "...",
    "query_text": "...",
    "machine_id": "...",
    "product_id": "...",
    "batch_id": "...",
    "time_start": "...",
    "time_end": "..."
  },
  "evidence_bundle": {
    "query_id": "...",
    "evidence": [...],
    "conflicts": [...],
    "missing_information": [...],
    "warnings": [...]
  }
}
```

## Evidence Metadata Allowlist

Only these metadata keys are forwarded: `record_type`, `aggregation`, `parameter`, `result`, `defect_type`, `inspection_method`, `maintenance_type`, `status`, `alarm_code`, `severity`, `time_start`, `time_end`, `sample_count`, `metrics`, `production_status`, `shift`, `cycle_time_sec`, `heading_path`, `chapter`, `section`, `subsection`.

## Structured Output Schema

Gemini returns JSON with: `observations`, `possible_causes`, `recommended_checks`, `missing_information`, `answer`, `answer_evidence_ids`. Each claim contains `text` and `evidence_ids`.

## Citation Validation

Every returned evidence ID is validated against the actual `EvidenceBundle.evidence[*].evidence_id`. Invalid citations invalidate the entire response. No invented citation IDs are permitted.

## Score Preservation

- `retrieval_score` — preserved exactly as supplied by agents
- `decision_score` — preserved exactly as supplied by agents
- No normalization, no comparison across source types
- No new scoring fields introduced

## Empty Evidence

If `EvidenceBundle.evidence == []`, the provider is NOT called. Returns deterministic unavailable result with `ProviderStatus.UNAVAILABLE`.

## Missing API Key

If `GEMINI_API_KEY` is absent, the provider is NOT called. Returns deterministic unavailable result.

## Disabled Gemini

If `gemini_enabled = false`, the provider is NOT called. Returns deterministic unavailable result.

## Provider Failure Handling

Expected failures: timeout, connection error, API error, failed/cancelled/incomplete response, invalid JSON, schema validation failure, invalid citations. All produce deterministic unavailable result with `ProviderStatus.UNAVAILABLE`.

An empty or missing `output_text` still fails closed to `ProviderStatus.UNAVAILABLE`.
The reasoner does not fabricate an answer from retrieved evidence to hide a
provider failure.

## Retry Behavior

Bounded retry (`gemini_max_retries`). Same evidence sent on retry. No hidden external facts added. No grounding rules weakened.

## Privacy / Logging

Never logged: API keys, authorization headers, entire evidence bundle, raw
provider request/response bodies, prompts, or generated reasoning text. Logged:
query_id, model, evidence_count, conflict_count, provider status, latency,
validation/retry outcome, and safe Interactions response-shape diagnostics such
as response object type, status, whether `output_text` exists, whether it is
empty/populated, and step types.

## Prompt-Injection Boundary

Evidence content is treated as untrusted DATA. Text inside evidence such as "ignore previous instructions" never overrides the fixed system instruction.

## STEP 11 Stub Warning

`JevDecisionEngine.score_evidence()` and `JevDecisionEngine.review()` remain STEP 11 placeholders. STEP 13 does NOT invoke them. STEP 14 implements final review separately.

## Tests

- `tests/reasoning/test_gemini_reasoner.py` — 53 offline unit tests

## Known Limitations

- No live tests (all offline with fake client)
- No file upload to Gemini
- No server-side conversation chaining
- `missing_information` from bundle is always empty (STEP 12 limitation)
