from __future__ import annotations

import hashlib
import time
from datetime import datetime
from typing import Any

from app.contracts.agents import AgentResult
from app.contracts.enums import AgentName, EvidenceSourceType, SourceKind
from app.contracts.evidence import Evidence, EvidenceProvenance
from app.contracts.query import QueryRequest
from app.core.config import Settings, get_settings
from app.core.exceptions import DatabaseError
from app.db.models import ProductionRecord
from app.repositories.production import (
    ProductionRepository,
    RejectionSummary,
)

__all__ = ["ProductionAgent", "build_production_agent"]

EXPECTED_SOURCE_FAILURES = (
    DatabaseError,
    ConnectionError,
    TimeoutError,
)

_MISSING_SCOPE_WARNING = (
    "At least one structured production scope (batch_id, machine_id, or "
    "product_id) is required; no repository queries were performed."
)

SOURCE_DATASET = "manufacturaiq_demo_factory"


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _number_text(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _stable_digest(*parts: str, length: int = 12) -> str:
    joined = "|".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:length]


def production_record_to_evidence(record: ProductionRecord) -> Evidence:
    lines = [
        ("Production ID", record.production_id),
        ("Batch ID", record.batch_id),
        ("Machine ID", record.machine_id),
        ("Product ID", record.product_id),
        ("Production Status", record.production_status),
        ("Planned Quantity", record.planned_quantity),
        ("Actual Quantity", record.actual_quantity),
        ("Accepted Quantity", record.accepted_quantity),
        ("Rejected Quantity", record.rejected_quantity),
        ("Reject Rate", _number_text(record.reject_rate)),
        ("Planned Start", _iso(record.planned_start_time)),
        ("Actual Start", _iso(record.actual_start_time)),
        ("Actual End", _iso(record.actual_end_time)),
        ("Cycle Time (sec)", record.cycle_time_sec),
        ("Shift", record.shift),
        ("Timestamp", _iso(record.actual_start_time)),
    ]
    content = "\n".join(
        f"{label}: {value}" for label, value in lines if value is not None
    )
    return Evidence(
        evidence_id=f"EVIDENCE-PRODUCTION-{record.production_id}",
        source_type=EvidenceSourceType.PRODUCTION,
        provenance=EvidenceProvenance(
            source_kind=SourceKind.DEMO_FACTORY,
            source_dataset=record.source_dataset,
            source_id=record.production_id,
            record_id=record.production_id,
        ),
        machine_id=record.machine_id,
        product_id=record.product_id,
        batch_id=record.batch_id,
        title=f"Production {record.production_id} — {record.product_id} — {record.machine_id} — {record.production_status}",
        content=content,
        observed_at=record.actual_start_time,
        metadata={
            "record_type": "production_order",
            "production_status": record.production_status,
            "is_synthetic": record.is_synthetic,
            "shift": record.shift,
            "cycle_time_sec": record.cycle_time_sec,
        },
    )


def rejection_summary_to_evidence(
    summary: RejectionSummary,
    machine_id: str | None,
    product_id: str | None,
    start_time: datetime | None,
    end_time: datetime | None,
    source_dataset: str,
) -> Evidence:
    digest = _stable_digest(
        str(machine_id or ""),
        str(product_id or ""),
        _iso(start_time) or "",
        _iso(end_time) or "",
        "production_summary_v1",
    )
    lines = [
        f"Production summary: {summary.order_count} orders, "
        f"total actual={summary.total_actual_quantity}, "
        f"accepted={summary.total_accepted_quantity}, "
        f"rejected={summary.total_rejected_quantity}, "
        f"reject rate {_number_text(summary.reject_rate)}.",
    ]
    scope_parts = []
    if machine_id:
        scope_parts.append(f"machine {machine_id}")
    if product_id:
        scope_parts.append(f"product {product_id}")
    scope = ", ".join(scope_parts) if scope_parts else "all scope"
    return Evidence(
        evidence_id=f"EVIDENCE-PRODUCTION-SUMMARY-{digest}",
        source_type=EvidenceSourceType.PRODUCTION,
        provenance=EvidenceProvenance(
            source_kind=SourceKind.DEMO_FACTORY,
            source_dataset=source_dataset,
            source_id=f"PRODUCTION-SUMMARY-{digest}",
            record_id=None,
        ),
        machine_id=machine_id,
        product_id=product_id,
        batch_id=None,
        title=f"Production rejection summary — {scope}",
        content="\n".join(lines),
        metadata={
            "record_type": "production_summary",
            "aggregation": "production_summary",
            "order_count": summary.order_count,
            "total_actual_quantity": summary.total_actual_quantity,
            "total_accepted_quantity": summary.total_accepted_quantity,
            "total_rejected_quantity": summary.total_rejected_quantity,
            "reject_rate": summary.reject_rate,
            "machine_id": machine_id,
            "product_id": product_id,
            "time_start": _iso(start_time),
            "time_end": _iso(end_time),
        },
    )


class ProductionAgent:
    """Answers "what production-order and output evidence exists?" and nothing more.

    Thin async wrapper over ProductionRepository: it resolves a deterministic
    scope from structured filters, maps rows to frozen ``Evidence`` with
    stable IDs, and packages them into a frozen ``AgentResult``. No
    thresholds, no diagnosis, no LLM, no RAG, no fusion.
    """

    def __init__(
        self,
        production_repository: ProductionRepository,
        *,
        settings: Settings | None = None,
        order_limit: int | None = None,
    ) -> None:
        resolved = settings or get_settings()
        self._production_repository = production_repository
        self._settings = resolved
        self._order_limit = self._checked_limit(
            order_limit, resolved.production_agent_order_limit, "order_limit"
        )

    @staticmethod
    def _checked_limit(value: int | None, default: int, name: str) -> int:
        if value is None:
            return default
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} must be an integer")
        if value < 1:
            raise ValueError(f"{name} must be greater than zero")
        return value

    @staticmethod
    def _latency_ms(started: float) -> float:
        return max(0.0, (time.perf_counter() - started) * 1000.0)

    def _scope_canonical(
        self, query: QueryRequest
    ) -> tuple[str | None, str | None, str | None]:
        return query.machine_id, query.product_id, query.batch_id

    async def run(self, query: QueryRequest) -> AgentResult:
        started = time.perf_counter()
        machine_id, product_id, batch_id = self._scope_canonical(query)

        if not machine_id and not product_id and not batch_id:
            return AgentResult(
                agent_name=AgentName.PRODUCTION,
                query_id=query.query_id,
                evidence=[],
                warnings=[_MISSING_SCOPE_WARNING],
                errors=[],
                latency_ms=self._latency_ms(started),
                metadata={
                    "scope_type": "none",
                    "machine_id": None,
                    "product_id": None,
                    "batch_id": None,
                    "retrieval_status": "missing_scope",
                },
            )

        scope_parts = []
        if batch_id:
            scope_parts.append("batch")
        if machine_id:
            scope_parts.append("machine")
        if product_id:
            scope_parts.append("product")
        scope_type = "+".join(scope_parts)

        has_time = query.time_start is not None or query.time_end is not None
        evidence: list[Evidence] = []
        warnings: list[str] = []
        errors: list[str] = []
        completed = 0
        failed = 0
        order_count = 0
        summary_evidence_count = 0

        # --- production orders ---
        order_rows: list[ProductionRecord] = []
        order_failed = False
        single_record_scope = batch_id and not machine_id and not product_id

        try:
            if single_record_scope:
                record = await self._production_repository.get_by_batch_id(batch_id)
                order_rows = [record] if record is not None else []
            elif machine_id and product_id and not batch_id:
                order_rows = await self._production_repository.list_by_machine_and_product(
                    machine_id, product_id, query.time_start, query.time_end, limit=self._order_limit
                )
            elif machine_id and not product_id and not batch_id:
                order_rows = await self._production_repository.list_by_machine(
                    machine_id, query.time_start, query.time_end, limit=self._order_limit
                )
            elif product_id and not machine_id and not batch_id:
                order_rows = await self._production_repository.list_by_product(
                    product_id, query.time_start, query.time_end, limit=self._order_limit
                )
            elif batch_id and (machine_id or product_id):
                record = await self._production_repository.get_by_batch_id(batch_id)
                if record is not None:
                    if machine_id and record.machine_id != machine_id:
                        order_rows = []
                    elif product_id and record.product_id != product_id:
                        order_rows = []
                    else:
                        order_rows = [record]
                else:
                    order_rows = []
            else:
                order_rows = await self._production_repository.list_by_machine(
                    machine_id, query.time_start, query.time_end, limit=self._order_limit
                )
            completed += 1
        except EXPECTED_SOURCE_FAILURES as exc:
            order_rows = []
            order_failed = True
            failed += 1
            errors.append(f"Production order retrieval failed: {exc}")
            warnings.append("Production order evidence unavailable; returning partial results.")

        order_evidence = [production_record_to_evidence(row) for row in order_rows]
        order_count = len(order_evidence)

        # --- rejection summary ---
        summary: RejectionSummary | None = None
        summary_failed = False
        has_summary_scope = machine_id or product_id
        can_summarize = has_summary_scope and not batch_id

        try:
            if can_summarize:
                summary = await self._production_repository.summarize_rejections(
                    machine_id=machine_id,
                    product_id=product_id,
                    start_time=query.time_start,
                    end_time=query.time_end,
                )
            completed += 1
        except EXPECTED_SOURCE_FAILURES as exc:
            summary_failed = True
            failed += 1
            summary = None
            errors.append(f"Production rejection summary retrieval failed: {exc}")
            warnings.append("Production summary evidence unavailable; returning partial results.")

        if summary is not None:
            summary_evidence = rejection_summary_to_evidence(
                summary, machine_id, product_id,
                query.time_start, query.time_end, SOURCE_DATASET,
            )
            evidence.append(summary_evidence)
            summary_evidence_count = 1

        evidence.extend(order_evidence)

        if not order_rows and not order_failed and not batch_id:
            warnings.append(
                f"No production evidence found for scope {scope_type}."
            )
        if batch_id and not order_rows and not order_failed:
            warnings.append(f"No production order found for batch {batch_id}.")

        if failed > 0 and completed == 0:
            status = "failed"
        elif failed > 0:
            status = "partial"
        elif not evidence:
            status = "empty"
        else:
            status = "ok"

        return AgentResult(
            agent_name=AgentName.PRODUCTION,
            query_id=query.query_id,
            evidence=evidence,
            warnings=warnings,
            errors=errors,
            latency_ms=self._latency_ms(started),
            metadata=self._base_metadata(
                query, scope_type, status, order_count, summary_evidence_count,
            ),
        )

    def _base_metadata(
        self,
        query: QueryRequest,
        scope_type: str,
        status: str,
        order_count: int,
        summary_evidence_count: int,
    ) -> dict[str, Any]:
        return {
            "scope_type": scope_type,
            "machine_id": query.machine_id,
            "product_id": query.product_id,
            "batch_id": query.batch_id,
            "requested_time_start": _iso(query.time_start),
            "requested_time_end": _iso(query.time_end),
            "order_count": order_count,
            "summary_evidence_count": summary_evidence_count,
            "retrieval_status": status,
        }


def build_production_agent(
    settings: Settings | None = None,
    database_path: str | None = None,
) -> ProductionAgent:
    """Construct a ProductionAgent on the canonical operational database."""
    from app.db.connection import DatabaseConnection

    resolved = settings or get_settings()
    database = (
        DatabaseConnection(database_path) if database_path else DatabaseConnection()
    )
    return ProductionAgent(
        ProductionRepository(database),
        settings=resolved,
    )
