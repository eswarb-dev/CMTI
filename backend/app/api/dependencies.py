from __future__ import annotations

from typing import Any, Protocol

from fastapi import Request

from app.contracts.query import QueryRequest
from app.orchestration.state import WorkflowResult


class OrchestratorLike(Protocol):
    async def run(self, query: QueryRequest) -> WorkflowResult:
        """Run the ManufacturaIQ workflow for one query."""


def get_orchestrator(request: Request) -> OrchestratorLike:
    """Return the application-owned or injected orchestrator."""

    return request.app.state.orchestrator


def get_document_service(request: Request) -> Any | None:
    """Return the application-owned or injected document service (or None)."""

    return getattr(request.app.state, "document_service", None)


async def close_resource(resource: Any) -> None:
    """Close an app-owned resource if it exposes a close method."""

    close = getattr(resource, "aclose", None)
    if callable(close):
        await close()
        return

    close = getattr(resource, "close", None)
    if callable(close):
        result = close()
        if hasattr(result, "__await__"):
            await result

