# Backend Contracts

STEP 04 defines the shared backend contracts and provider-neutral protocols for ManufacturaIQ. It does not implement routes, agents, databases, RAG, Jev, LangGraph, Gemini, embeddings, or frontend behavior.

## QueryRequest

Fields: `query_id`, `query`, optional `machine_id`, `product_id`, `batch_id`, optional `time_start`, `time_end`, and `user_context`.

Validation trims `query`, rejects empty `query_id` or `query`, and rejects `time_start > time_end`.

## EvidenceProvenance

Fields: `source_kind`, `source_dataset`, `source_id`, `source_file`, `document_id`, `record_id`, `raw_record_id`, `chunk_id`, `page_start`, `page_end`, `chapter`, `section`, `subsection`.

Page numbers must be positive, and `page_start <= page_end` when both are present.

## Evidence

Evidence is the common currency returned by all future agents. It includes `evidence_id`, `source_type`, `provenance`, optional machine/product/batch filters, `title`, `content`, optional `observed_at`, optional scores, and `metadata`.

`content` must be human-readable evidence and must never include hidden evaluation ground truth.

## AgentResult

Fields: `agent_name`, `query_id`, `evidence`, `warnings`, `errors`, `latency_ms`, `metadata`.

An agent returns evidence, not the final engineering answer.

## RoutingDecision

Fields: `query_id`, `intent`, `selected_agents`, `needs_clarification`, `clarification_reason`, `risk_level`, `confidence`, `provider_status`, `decision_metadata`.

`selected_agents` is the single source of truth for routing and must contain unique agent names.

## EvidenceConflict

Fields: `conflict_id`, `evidence_ids`, `conflict_type`, `description`, `severity`, `resolved`, `resolution_note`.

## EvidenceBundle

Fields: `query_id`, `evidence`, `conflicts`, `missing_information`, `warnings`, `metadata`.

The future reasoner receives this fused evidence bundle.

## EvidenceCitation

Fields: `evidence_id`, `label`.

The reasoner cites evidence IDs. The frontend can later resolve IDs to provenance.

## ReasoningResult

Fields: `query_id`, `observations`, `possible_causes`, `recommended_checks`, `missing_information`, `citations`, `raw_answer`, `provider_status`, `model`, `metadata`.

There is no `confirmed_root_cause` field. Hypotheses must not be treated as proof.

## ReviewDecision

Fields: `query_id`, `action`, `reasons`, `confidence`, `provider_status`, `metadata`.

## Protocols

Provider-neutral async protocols:

- `Agent.run(query) -> AgentResult`
- `DocumentRetriever.retrieve(query, top_k=10) -> list[Evidence]`
- `DecisionEngine.route(query) -> RoutingDecision`
- `DecisionEngine.score_evidence(query, evidence) -> list[Evidence]`
- `DecisionEngine.review(query, bundle, reasoning) -> ReviewDecision`
- `EvidenceFusionService.fuse(query, agent_results) -> EvidenceBundle`
- `Reasoner.reason(query, evidence) -> ReasoningResult`
- `ReviewGate.evaluate(query, evidence, reasoning) -> ReviewDecision`

These protocols intentionally do not import TypeSafe/Jev, LangGraph, Gemini, vector database, or retrieval SDK classes.

## Ground-Truth Boundary

Application backend code must not import, load, or reference `datasets/synthetic/demo_cases.json` or `hidden_simulated_cause`. That file is evaluation-only and is outside the application evidence path.

## Contract Freeze Policy

After STEP 04 is approved, shared contract fields and meanings are considered frozen. Later modules must import these contracts rather than recreating them. If a future schema change is genuinely required, document the migration reason, update tests, and update dependent modules deliberately.

