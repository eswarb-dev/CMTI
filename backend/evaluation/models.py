"""Evaluation-only models for STEP 18A.

These models live OUTSIDE ``app/contracts`` on purpose: they describe the
evaluation harness, not the production system. Production contracts must not
import this module.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

EvaluationMode = Literal["offline", "gemini-live", "full-provider"]

FAILURE_CATEGORIES = (
    "routing_mismatch",
    "missing_expected_evidence",
    "scope_mismatch",
    "invalid_provenance",
    "invalid_citation",
    "unsupported_reasoning_reference",
    "causal_overreach_warning",
    "unsafe_recommendation_warning",
    "provider_failure",
    "unexpected_exception",
    "determinism_failure",
)


class EvaluationCase(BaseModel):
    """One evaluation case.

    Fields prefixed ``expected_`` / ``hidden_`` are EVALUATOR-ONLY ground
    truth. The runner must produce the workflow result BEFORE this module's
    comparison helpers read them, and they must NEVER be placed into
    ``QueryRequest``, agent inputs, or provider prompts.
    """

    case_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    query: str = Field(min_length=1)
    machine_id: str | None = None
    product_id: str | None = None
    batch_id: str | None = None
    time_start: str | None = None
    time_end: str | None = None
    document_context: dict[str, Any] = Field(default_factory=dict)
    expected_agents: list[str] = Field(default_factory=list)
    expected_source_types: list[str] = Field(default_factory=list)
    expected_evidence_ids: list[str] = Field(default_factory=list)
    expected_document_ids: list[str] = Field(default_factory=list)
    expected_keywords: list[str] = Field(default_factory=list)
    expected_record_ids: list[str] = Field(default_factory=list)
    expected_clarification: bool = False
    expected_review_action: str | None = None
    expected_hidden_cause: str | None = None
    safety_expectation: str | None = None
    notes: str | None = None

    @field_validator("case_id", "category", "query")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("evaluation case identifiers and query must not be blank")
        return value

    def hidden_strings(self) -> list[str]:
        """Evaluator-only strings that must never reach production inputs."""

        hidden: list[str] = []
        for value in (
            self.expected_hidden_cause,
            self.notes,
        ):
            if value and value.strip():
                hidden.append(value)
        hidden.extend(self.expected_keywords)
        hidden.extend(self.expected_document_ids)
        hidden.extend(self.expected_record_ids)
        return hidden


class MetricResult(BaseModel):
    """One named metric outcome for a case."""

    name: str
    value: float | None = None
    passed: bool | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class CaseResult(BaseModel):
    """Per-case evaluation record (no secrets, no raw provider responses)."""

    case_id: str
    category: str
    mode: str
    query: str
    machine_id: str | None = None
    product_id: str | None = None
    batch_id: str | None = None
    routing_agents: list[str] = Field(default_factory=list)
    routing_provider_status: str | None = None
    needs_clarification: bool = False
    agents_executed: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_source_types: list[str] = Field(default_factory=list)
    citation_ids: list[str] = Field(default_factory=list)
    reasoning_provider_status: str | None = None
    review_action: str | None = None
    metrics: list[MetricResult] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    latency_ms: float | None = None
    # Evaluator-only comparisons (hidden truth may appear HERE ONLY).
    hidden_cause_alignment: str | None = None
    warnings: list[str] = Field(default_factory=list)


class EvaluationRun(BaseModel):
    """Whole-run record with environment metadata (never secrets)."""

    run_id: str
    mode: str
    suite: str
    started_at: str
    finished_at: str | None = None
    case_count: int = 0
    environment: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
