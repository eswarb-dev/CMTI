from __future__ import annotations

import asyncio
import logging
import time
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.dependencies import OrchestratorLike, get_orchestrator
from app.api.schemas import ApiQueryRequest, ApiQueryResponse, HealthResponse, ReadyResponse
from app.contracts.enums import ReviewAction
from app.contracts.query import QueryRequest

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", include_in_schema=False)
async def service_info() -> dict[str, str]:
    return {"service": "manufacturaiq", "version": "0.1.0"}


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service="manufacturaiq")


@router.get("/ready", response_model=ReadyResponse)
async def ready(orchestrator: Annotated[OrchestratorLike, Depends(get_orchestrator)]) -> ReadyResponse:
    if orchestrator is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="service not ready")
    return ReadyResponse(status="ready", service="manufacturaiq", orchestrator="available")


@router.post("/api/query", response_model=ApiQueryResponse)
async def query(
    request: ApiQueryRequest,
    http_request: Request,
    orchestrator: Annotated[OrchestratorLike, Depends(get_orchestrator)],
) -> ApiQueryResponse:
    query_request = QueryRequest(
        query_id=str(uuid4()),
        query=request.query,
        machine_id=request.machine_id,
        product_id=request.product_id,
        batch_id=request.batch_id,
        time_start=request.time_start,
        time_end=request.time_end,
        user_context=request.document_context.to_user_context() if request.document_context else {},
    )

    started = time.perf_counter()
    try:
        timeout_seconds = getattr(http_request.app.state.settings, "query_total_timeout_seconds", 20.0)
        logger.warning("[query_stage] query=%s workflow START", query_request.query_id)
        async with asyncio.timeout(timeout_seconds):
            result = await orchestrator.run(query_request)
        logger.warning(
            "[query_stage] query=%s workflow END duration_ms=%s",
            query_request.query_id,
            round((time.perf_counter() - started) * 1000, 3),
        )
    except TimeoutError:
        logger.warning(
            "[query_stage] query=%s workflow TIMEOUT duration_ms=%s",
            query_request.query_id,
            round((time.perf_counter() - started) * 1000, 3),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "query deadline exceeded"},
        ) from None
    except Exception:
        logger.exception("query failed", extra={"query_id": query_request.query_id})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "internal server error"},
        ) from None

    serialization_started = time.perf_counter()
    response = _workflow_result_to_response(result)
    serialization_ms = round((time.perf_counter() - serialization_started) * 1000, 3)
    result.setdefault("perf_timings", {})["serialization_ms"] = serialization_ms
    latency_ms = round((time.perf_counter() - started) * 1000, 3)
    review = result.get("review_decision")
    routing = result.get("routing_decision")
    reasoning = result.get("reasoning_result")
    perf = dict(result.get("perf_timings") or {})
    logger.info(
        "query completed",
        extra={
            "query_id": response.query_id,
            "status": response.status,
            "review_action": getattr(getattr(review, "action", None), "value", None),
            "latency_ms": latency_ms,
        },
    )
    logger.warning(
        "[query_perf] route=%sms agents=%sms document_agent=%sms maintenance_agent=%sms quality_agent=%sms production_agent=%sms retrieval=%sms fusion=%sms reasoning=%sms review=%sms serialization=%sms total=%sms reasoning_attempts=%s reasoning_status=%s routing_status=%s review_status=%s",
        perf.get("routing_ms"),
        perf.get("agents_ms"),
        perf.get("document_agent_ms"),
        perf.get("maintenance_agent_ms"),
        perf.get("quality_agent_ms"),
        perf.get("production_agent_ms"),
        perf.get("document_retrieval_ms"),
        perf.get("fusion_ms"),
        perf.get("reasoning_ms"),
        perf.get("review_ms"),
        perf.get("serialization_ms"),
        perf.get("total_ms"),
        (getattr(reasoning, "metadata", {}) or {}).get("attempts") if reasoning is not None else None,
        getattr(getattr(reasoning, "provider_status", None), "value", None),
        getattr(getattr(routing, "provider_status", None), "value", None),
        getattr(getattr(review, "provider_status", None), "value", None),
        extra={"query_id": response.query_id},
    )
    return response


def _workflow_result_to_response(result: dict[str, Any]) -> ApiQueryResponse:
    routing = result.get("routing_decision")
    if routing is None:
        raise RuntimeError("workflow result missing routing_decision")

    evidence_bundle = result.get("evidence_bundle")
    reasoning = result.get("reasoning_result")
    review = result.get("review_decision")

    if routing.needs_clarification:
        api_status = "needs_clarification"
    elif review is not None and review.action == ReviewAction.PASS:
        api_status = "pass"
    elif review is not None and review.action == ReviewAction.HUMAN_REVIEW:
        api_status = "human_review"
    else:
        raise RuntimeError("workflow result missing terminal review decision")

    return ApiQueryResponse(
        query_id=result["query_id"],
        status=api_status,
        routing=_dump_model(routing),
        evidence=_dump_model(evidence_bundle) if evidence_bundle is not None else None,
        reasoning=_dump_model(reasoning) if reasoning is not None else None,
        review=_dump_model(review) if review is not None else None,
    )


def _dump_model(value: Any) -> dict[str, Any]:
    return value.model_dump(mode="json")

