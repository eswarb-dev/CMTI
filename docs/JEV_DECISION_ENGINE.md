# STEP 11 — Jev Decision Engine

## Purpose

`JevDecisionEngine` (`backend/app/decision/jev.py`) implements the frozen
`DecisionEngine` protocol by routing queries to appropriate agents using
the official TypeSafe Python SDK.

**Critical boundary**: Jev decides **WHAT** should run. LangGraph later
decides **HOW/WHEN** it runs. No agent execution happens here.

## Architecture

```
                     ┌─ route_document Noul
                     ├─ route_maintenance Noul
QueryRequest → Jev ──┼─ route_quality Noul
                     └─ route_production Noul
                              ↓
                       threshold in code
                              ↓
                    RoutingDecision
                    .selected_agents
                              ↓
                    [STOP STEP 11]
```

## Official SDK

- **Package**: `typesafe-sdk>=0.7.0`
- **Environment**: `TYPESAFE_API_KEY`
- **Client**: `AsyncTypeSafeClient`
- **Default model**: `jev-latest` (configurable)
- **Primary call**: `client.system_one(state=..., questions=..., model=..., retry=..., timeout=...)`

## State Schema

```json
{
  "query": "<verbatim query text>",
  "machine_id": "<as supplied or null>",
  "product_id": "<as supplied or null>",
  "batch_id": "<as supplied or null>",
  "time_start": "<ISO-8601 or null>",
  "time_end": "<ISO-8601 or null>",
  "routing_context": {
    "document_type": "<if in allowlist>",
    "manufacturer": "<if in allowlist>",
    "machine_family": "<if in allowlist>",
    "model": "<if in allowlist>",
    "document_id": "<if in allowlist>",
    "language": "<if in allowlist>"
  }
}
```

## User Context Allowlist

Only these keys from `QueryRequest.user_context` are forwarded:
`document_type`, `manufacturer`, `machine_family`, `model`,
`document_id`, `language`. All other user_context fields are excluded.

## Four Noul Routing Questions

| Question name | Agent | Focus |
|---|---|---|
| `route_document` | DOCUMENT | Technical documentation, manuals, safety procedures |
| `route_maintenance` | MAINTENANCE | Maintenance history, alarms, telemetry, machine condition |
| `route_quality` | QUALITY | Quality inspections, measurements, pass/fail, defects |
| `route_production` | PRODUCTION | Production orders, quantities, reject rates |

Each question is an independent `Noul` judgment. Multi-label routing is
supported.

## Threshold Semantics

- Default: `jev_route_threshold = 0.50`
- Selection rule: `noul >= threshold` (inclusive)
- Below threshold: agent not selected

## Selected Agents Construction

- Only implemented agents: DOCUMENT, MAINTENANCE, QUALITY, PRODUCTION
- Canonical order: DOCUMENT → MAINTENANCE → QUALITY → PRODUCTION
- No duplicates (enforced by RoutingDecision validator)
- `selected_agents` is the sole public routing source of truth

## Intent Mapping

| Selected agents | Intent |
|---|---|
| Single DOCUMENT | DOCUMENTATION |
| Single MAINTENANCE | MAINTENANCE |
| Single QUALITY | QUALITY |
| Single PRODUCTION | PRODUCTION |
| Multiple | MULTI_DOMAIN |
| None | UNKNOWN |

## RiskLevel Handling

`RoutingDecision.risk_level` is required by the frozen contract. STEP 11
uses `RiskLevel.LOW` as a conservative default. No risk taxonomy is
invented here.

## Fallback Policy

Deterministic conservative fallback (never another AI model):

| Scope | Fallback agents |
|---|---|
| No structured IDs | [DOCUMENT] |
| machine_id only | [DOCUMENT, MAINTENANCE, QUALITY, PRODUCTION] |
| product_id only | [DOCUMENT, QUALITY, PRODUCTION] |
| batch_id only | [DOCUMENT, QUALITY, PRODUCTION] |
| machine_id + product_id | [DOCUMENT, MAINTENANCE, QUALITY, PRODUCTION] |

Fallback triggers:
- `TYPESAFE_API_KEY` absent
- `jev_enabled = false`
- Provider timeout / connection / API error
- Malformed/missing routing answers
- All probabilities below threshold

## Configuration

| Setting | Default | Meaning |
|---|---|---|
| `jev_model` | `"jev-latest"` | TypeSafe model alias |
| `jev_route_threshold` | `0.50` | Noul probability cutoff |
| `jev_timeout_seconds` | `10.0` | Request timeout |
| `jev_max_retries` | `1` | SDK retry policy |
| `jev_enabled` | `true` | Enable/disable provider |
| `typesafe_api_key` | `None` | API key from environment |

## Provider Error Handling

Expected provider exceptions caught:
- `ProviderUnavailableError`
- `ConnectionError`
- `TimeoutError`

All produce deterministic fallback with `ProviderStatus.FALLBACK`.
Unexpected programming errors propagate.

## Client Lifecycle

One reusable `AsyncTypeSafeClient` per `JevDecisionEngine` instance.
`aclose()` method provided for cleanup. Future FastAPI lifespan wiring
will own long-lived lifecycle.

## Privacy / Logging

Logged diagnostics: `query_id`, `selected_agents`, `provider_status`,
`fallback_used`, `latency_ms`. Never logged: API keys, authorization
headers, full user_context, raw SDK request/response bodies.

## DecisionEngine Contract Mapping

| Protocol method | Status |
|---|---|
| `route()` | Fully implemented (STEP 11) |
| `score_evidence()` | Placeholder — returns input unchanged |
| `review()` | Fully implemented (STEP 14) |

## Tests

- `tests/decision/test_jev_decision_engine.py` — 50 offline unit tests
- `tests/decision/test_jev_live.py` — optional live tests (skipped without API key)

## Known Limitations

- `score_evidence` remains a placeholder; `review` was implemented in STEP 14
- Live tests require `TYPESAFE_API_KEY` and are skipped otherwise
- RiskLevel is conservatively set to LOW (no risk taxonomy in STEP 11)
- No entity extraction from query text
