from __future__ import annotations

from typing import Any

from pydantic import Field

from .base import ContractModel
from .enums import AgentName
from .evidence import Evidence


class AgentResult(ContractModel):
    """Evidence returned by one domain agent for one query."""

    agent_name: AgentName
    query_id: str = Field(min_length=1)
    evidence: list[Evidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    latency_ms: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

