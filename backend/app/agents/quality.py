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
from app.db.models import QualityRecord
from app.repositories.quality import (
    QualityRepository,
    QualitySummary,
    ParameterSummary,
)

__all__ = ["QualityAgent", "build_quality_agent"]

EXPECTED_SOURCE_FAILURES = (
    DatabaseError,
    ConnectionError,
    TimeoutError,
)

_MISSING_SCOPE_WARNING = (
    "At least one structured quality scope (batch_id, machine_id, or product_id) "
    "is required; no repository queries were performed."
)


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


SOURCE_DATASET = "manufacturaiq_demo_factory"


def quality_record_to_evidence(record: QualityRecord) -> Evidence:
    lines = [
        ("Inspection ID", record.inspection_id),
        ("Batch ID", record.batch_id),
        ("Machine ID", record.machine_id),
        ("Product ID", record.product_id),
        ("Timestamp", _iso(record.timestamp)),
        ("Parameter", record.parameter),
        ("Nominal value", record.nominal_value),
        ("LSL", record.lsl),
        ("USL", record.usl),
        ("Measured value", record.measured_value),
        ("Result", record.result),
        ("Defect type", record.defect_type),
        ("Inspection method", record.inspection_method),
    ]
    content = "\n".join(
        f"{label}: {value}" for label, value in lines if value is not None
    )
    return Evidence(
        evidence_id=f"EVIDENCE-QUALITY-{record.inspection_id}",
        source_type=EvidenceSourceType.QUALITY,
        provenance=EvidenceProvenance(
            source_kind=SourceKind.DEMO_FACTORY,
            source_dataset=record.source_dataset,
            source_id=record.inspection_id,
            record_id=record.inspection_id,
        ),
        machine_id=record.machine_id,
        product_id=record.product_id,
        batch_id=record.batch_id,
        title=f"Quality {record.inspection_id} — {record.product_id} — {record.parameter} — {record.result}",
        content=content,
        observed_at=record.timestamp,
        metadata={
            "record_type": "quality_inspection",
            "parameter": record.parameter,
            "result": record.result,
            "defect_type": record.defect_type,
            "inspection_method": record.inspection_method,
            "is_synthetic": record.is_synthetic,
        },
    )


def quality_summary_to_evidence(
    summary: QualitySummary,
    machine_id: str | None,
    product_id: str | None,
    batch_id: str | None,
    start_time: datetime | None,
    end_time: datetime | None,
    source_dataset: str,
) -> Evidence:
    digest = _stable_digest(
        str(machine_id or ""),
        str(product_id or ""),
        str(batch_id or ""),
        _iso(start_time) or "",
        _iso(end_time) or "",
        "quality_summary_v1",
    )
    lines = [
        f"Quality summary: {summary.inspection_count} inspections, "
        f"{summary.pass_count} pass, {summary.fail_count} fail, "
        f"failure rate {_number_text(summary.failure_rate)}.",
    ]
    for param in summary.parameters:
        lines.append(
            f"{param.parameter}: count={param.inspection_count}, "
            f"pass={param.pass_count}, fail={param.fail_count}, "
            f"min={_number_text(param.min_measurement)}, "
            f"max={_number_text(param.max_measurement)}, "
            f"mean={_number_text(param.mean_measurement)}"
        )
    scope_parts = []
    if machine_id:
        scope_parts.append(f"machine {machine_id}")
    if product_id:
        scope_parts.append(f"product {product_id}")
    if batch_id:
        scope_parts.append(f"batch {batch_id}")
    scope = ", ".join(scope_parts) if scope_parts else "all scope"
    return Evidence(
        evidence_id=f"EVIDENCE-QUALITY-SUMMARY-{digest}",
        source_type=EvidenceSourceType.QUALITY,
        provenance=EvidenceProvenance(
            source_kind=SourceKind.DEMO_FACTORY,
            source_dataset=source_dataset,
            source_id=f"QUALITY-SUMMARY-{digest}",
            record_id=None,
        ),
        machine_id=machine_id,
        product_id=product_id,
        batch_id=batch_id,
        title=f"Quality summary — {scope}",
        content="\n".join(lines),
        metadata={
            "record_type": "quality_summary",
            "aggregation": "quality_summary",
            "inspection_count": summary.inspection_count,
            "pass_count": summary.pass_count,
            "fail_count": summary.fail_count,
            "failure_rate": summary.failure_rate,
            "parameters": [p.parameter for p in summary.parameters if p.parameter],
            "machine_id": machine_id,
            "product_id": product_id,
            "batch_id": batch_id,
            "time_start": _iso(start_time),
            "time_end": _iso(end_time),
        },
    )


class QualityAgent:
    """Answers "what quality inspection evidence exists?" and nothing more.

    Thin async wrapper over QualityRepository: it resolves a deterministic
    scope from structured filters, maps rows to frozen ``Evidence`` with
    stable IDs, and packages them into a frozen ``AgentResult``. No
    thresholds, no diagnosis, no LLM, no RAG, no fusion.
    """

    def __init__(
        self,
        quality_repository: QualityRepository,
        *,
        settings: Settings | None = None,
        inspection_limit: int | None = None,
        failure_limit: int | None = None,
    ) -> None:
        resolved = settings or get_settings()
        self._quality_repository = quality_repository
        self._settings = resolved
        self._inspection_limit = self._checked_limit(
            inspection_limit, resolved.quality_agent_inspection_limit, "inspection_limit"
        )
        self._failure_limit = self._checked_limit(
            failure_limit, resolved.quality_agent_failure_limit, "failure_limit"
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

    def _resolve_scope(self, query: QueryRequest) -> tuple[bool, str | None, str | None, str | None, bool]:
        has_time = query.time_start is not None or query.time_end is not None
        has_batch = query.batch_id is not None
        has_machine = query.machine_id is not None
        has_product = query.product_id is not None
        return has_time, has_batch, has_machine, has_product, has_time

    async def run(self, query: QueryRequest) -> AgentResult:
        started = time.perf_counter()
        machine_id = query.machine_id
        product_id = query.product_id
        batch_id = query.batch_id

        if not machine_id and not product_id and not batch_id:
            return AgentResult(
                agent_name=AgentName.QUALITY,
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

        scope_type = []
        if batch_id:
            scope_type.append("batch")
        if machine_id:
            scope_type.append("machine")
        if product_id:
            scope_type.append("product")
        scope_type_str = "+".join(scope_type)

        has_time = query.time_start is not None or query.time_end is not None

        evidence: list[Evidence] = []
        warnings: list[str] = []
        errors: list[str] = []
        completed = 0
        failed = 0
        inspection_count = 0
        failure_count = 0
        summary_count = 0

        # --- quality summary (supports all filters) ---
        summary: QualitySummary | None = None
        try:
            summary = await self._quality_repository.summarize_results(
                machine_id=machine_id,
                product_id=product_id,
                batch_id=batch_id,
                start_time=query.time_start,
                end_time=query.time_end,
            )
            completed += 1
            summary_count = 1
        except EXPECTED_SOURCE_FAILURES as exc:
            errors.append(f"Quality summary retrieval failed: {exc}")
            warnings.append("Quality summary evidence unavailable; returning partial results.")
            failed += 1

        if summary is not None:
            summary_evidence = quality_summary_to_evidence(
                summary, machine_id, product_id, batch_id,
                query.time_start, query.time_end,
                SOURCE_DATASET,
            )
            evidence.append(summary_evidence)

        # --- failure records (supports all filters via list_failures) ---
        failure_rows: list[QualityRecord] = []
        failure_failed = False
        try:
            failure_rows = await self._quality_repository.list_failures(
                machine_id=machine_id,
                product_id=product_id,
                batch_id=batch_id,
                start_time=query.time_start,
                end_time=query.time_end,
                limit=self._failure_limit,
            )
            completed += 1
        except EXPECTED_SOURCE_FAILURES as exc:
            failure_rows = []
            failure_failed = True
            failed += 1
            errors.append(f"Quality failure retrieval failed: {exc}")
            warnings.append("Quality failure evidence unavailable; returning partial results.")

        failure_evidence = [quality_record_to_evidence(row) for row in failure_rows]
        failure_count = len(failure_evidence)
        evidence.extend(failure_evidence)

        # --- general inspection records (specific method per scope) ---
        general_rows: list[QualityRecord] = []
        general_failed = False
        single_scope = (
            (batch_id and not machine_id and not product_id)
            or (machine_id and not product_id and not batch_id)
            or (product_id and not machine_id and not batch_id)
        )
        if single_scope:
            try:
                if batch_id and not has_time:
                    general_rows = await self._quality_repository.list_by_batch(
                        batch_id, limit=self._inspection_limit
                    )
                elif machine_id and not product_id and not batch_id:
                    general_rows = await self._quality_repository.list_by_machine(
                        machine_id, query.time_start, query.time_end, limit=self._inspection_limit
                    )
                elif product_id and not machine_id and not batch_id:
                    general_rows = await self._quality_repository.list_by_product(
                        product_id, query.time_start, query.time_end, limit=self._inspection_limit
                    )
                elif batch_id and has_time:
                    # list_by_batch doesn't support time; use list_failures for failures only
                    general_rows = []
                completed += 1
            except EXPECTED_SOURCE_FAILURES as exc:
                general_rows = []
                general_failed = True
                failed += 1
                errors.append(f"Quality inspection retrieval failed: {exc}")
                warnings.append("Quality inspection evidence unavailable; returning partial results.")

        general_evidence = [quality_record_to_evidence(row) for row in general_rows]
        inspection_count = len(general_evidence)

        # --- deduplicate: remove inspections already emitted as failures ---
        failure_ids = {row.inspection_id for row in failure_rows}
        deduped_evidence = [
            ev for ev in general_evidence if ev.provenance.record_id not in failure_ids
        ]
        evidence.extend(deduped_evidence)

        if not general_rows and not general_failed and not batch_id:
            warnings.append(
                f"No quality inspection evidence found for scope {scope_type_str}."
            )
        if batch_id and not general_rows and not general_failed:
            pass  # list_by_batch may return empty legitimately

        if failed > 0 and completed == 0:
            status = "failed"
        elif failed > 0:
            status = "partial"
        elif not evidence:
            status = "empty"
        else:
            status = "ok"

        return AgentResult(
            agent_name=AgentName.QUALITY,
            query_id=query.query_id,
            evidence=evidence,
            warnings=warnings,
            errors=errors,
            latency_ms=self._latency_ms(started),
            metadata=self._base_metadata(
                query,
                scope_type_str,
                status,
                inspection_count,
                failure_count,
                summary_count,
            ),
        )

    def _base_metadata(
        self,
        query: QueryRequest,
        scope_type: str,
        status: str,
        inspection_count: int,
        failure_count: int,
        summary_count: int,
    ) -> dict[str, Any]:
        return {
            "scope_type": scope_type,
            "machine_id": query.machine_id,
            "product_id": query.product_id,
            "batch_id": query.batch_id,
            "requested_time_start": _iso(query.time_start),
            "requested_time_end": _iso(query.time_end),
            "inspection_count": inspection_count,
            "failed_evidence_count": failure_count,
            "summary_evidence_count": summary_count,
            "retrieval_status": status,
        }


def build_quality_agent(
    settings: Settings | None = None,
    database_path: str | None = None,
) -> QualityAgent:
    """Construct a QualityAgent on the canonical operational database."""
    from app.db.connection import DatabaseConnection

    resolved = settings or get_settings()
    database = (
        DatabaseConnection(database_path) if database_path else DatabaseConnection()
    )
    return QualityAgent(
        QualityRepository(database),
        settings=resolved,
    )
