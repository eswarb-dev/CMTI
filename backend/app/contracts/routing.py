from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from .base import ContractModel
from .enums import AgentName, Domain, ProviderStatus, RiskLevel


class RoutingDecision(ContractModel):
    """Decision-engine routing result for a query."""

    query_id: str = Field(min_length=1)
    intent: Domain
    selected_agents: list[AgentName]
    needs_clarification: bool
    clarification_reason: str | None = None
    risk_level: RiskLevel
    confidence: float | None = None
    provider_status: ProviderStatus
    decision_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_selected_agents(self) -> "RoutingDecision":
        if len(set(self.selected_agents)) != len(self.selected_agents):
            raise ValueError("selected_agents must contain unique values")
        if self.needs_clarification and not (self.clarification_reason or "").strip():
            raise ValueError("clarification_reason is required when needs_clarification is true")
        return self

