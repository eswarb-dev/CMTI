from __future__ import annotations

import hashlib
import time
from datetime import date, datetime, timedelta
from typing import Any

from app.contracts.agents import AgentResult
from app.contracts.enums import AgentName, EvidenceSourceType, SourceKind
from app.contracts.evidence import Evidence, EvidenceProvenance
from app.contracts.query import QueryRequest
from app.core.config import Settings, get_settings
from app.core.exceptions import DatabaseError
from app.db.models import AlarmRecord, MaintenanceRecord
from app.repositories.alarms import AlarmRepository
from app.repositories.maintenance import MaintenanceRepository
from app.repositories.telemetry import TelemetryRepository, TelemetrySummary

__all__ = ["MaintenanceAgent", "build_maintenance_agent"]

#: Source failures that map to safe partial/failed AgentResults.
#: Anything else stays visible.
EXPECTED_SOURCE_FAILURES = (
    DatabaseError,
    ConnectionError,
    TimeoutError,
)

TELEMETRY_SUMMARY_SCHEMA = "telemetry_summary_v1"

_MISSING_MACHINE_WARNING = (
    "machine_id is required for maintenance evidence; "
    "no repository queries were performed."
)


def _iso(value: datetime | date | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
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


def maintenance_record_to_evidence(record: MaintenanceRecord) -> Evidence:
    """Map one maintenance row to frozen Evidence (facts only, no diagnosis)."""

    observed = record.started_at if record.started_at is not None else record.created_at
    lines = [
        ("Maintenance type", record.maintenance_type),
        ("Symptom", record.symptom),
        ("Component", record.component),
        ("Failure code", record.failure_code),
        ("Inspection findings", record.inspection_findings),
        ("Action taken", record.action_taken),
        ("Status", record.status),
        ("Planned downtime (min)", record.planned_downtime_min),
        ("Actual downtime (min)", record.actual_downtime_min),
        ("Created at", _iso(record.created_at)),
        ("Started at", _iso(record.started_at)),
        ("Completed at", _iso(record.completed_at)),
    ]
    content = "\n".join(f"{label}: {value}" for label, value in lines if value is not None)
    maintenance_type = record.maintenance_type or "unspecified type"
    return Evidence(
        evidence_id=f"EVIDENCE-MAINTENANCE-{record.maintenance_id}",
        source_type=EvidenceSourceType.MAINTENANCE,
        provenance=EvidenceProvenance(
            source_kind=SourceKind.DEMO_FACTORY,
            source_dataset=record.source_dataset,
            source_id=record.maintenance_id,
            record_id=record.maintenance_id,
        ),
        machine_id=record.machine_id,
        title=f"Maintenance {record.maintenance_id} — {record.machine_id} — {maintenance_type}",
        content=content,
        observed_at=observed,
        metadata={
            "record_type": "maintenance",
            "is_synthetic": record.is_synthetic,
            "maintenance_type": record.maintenance_type,
            "status": record.status,
        },
    )


def alarm_record_to_evidence(record: AlarmRecord) -> Evidence:
    """Map one alarm row to frozen Evidence (facts only, no diagnosis)."""

    lines = [
        ("Alarm code", record.alarm_code),
        ("Severity", record.severity),
        ("Category", record.category),
        ("Description", record.description),
        ("Timestamp", _iso(record.timestamp)),
        ("Acknowledged", record.acknowledged),
        ("Acknowledged at", _iso(record.acknowledged_at)),
        ("Related batch", record.related_batch_id),
    ]
    content = "\n".join(f"{label}: {value}" for label, value in lines if value is not None)
    code = record.alarm_code or record.alarm_id
    return Evidence(
        evidence_id=f"EVIDENCE-ALARM-{record.alarm_id}",
        source_type=EvidenceSourceType.ALARM,
        provenance=EvidenceProvenance(
            source_kind=SourceKind.DEMO_FACTORY,
            source_dataset=record.source_dataset,
            source_id=record.alarm_id,
            record_id=record.alarm_id,
        ),
        machine_id=record.machine_id,
        title=f"Alarm {code} — {record.machine_id}",
        content=content,
        observed_at=record.timestamp,
        metadata={
            "record_type": "alarm",
            "is_synthetic": record.is_synthetic,
            "alarm_code": record.alarm_code,
            "severity": record.severity,
        },
    )


def alarm_summary_to_evidence(
    machine_id: str,
    alarm_code: str,
    count: int,
    start_text: str | None,
    end_text: str | None,
    source_dataset: str,
) -> Evidence:
    """Deterministic recurrence count for one alarm code (counting, not diagnosis)."""

    digest = _stable_digest(machine_id, alarm_code, start_text or "", end_text or "")
    if start_text and end_text:
        scope = f" between {start_text} and {end_text}."
    else:
        scope = " across all recorded history."
    return Evidence(
        evidence_id=f"EVIDENCE-ALARM-SUMMARY-{machine_id}-{alarm_code}-{digest}",
        source_type=EvidenceSourceType.ALARM,
        provenance=EvidenceProvenance(
            source_kind=SourceKind.DEMO_FACTORY,
            source_dataset=source_dataset,
            source_id=f"ALARM-SUMMARY-{machine_id}-{alarm_code}-{digest}",
            record_id=None,
        ),
        machine_id=machine_id,
        title=f"Alarm recurrence {alarm_code} — {machine_id} — {count} occurrences",
        content=f"Alarm {alarm_code} occurred {count} times for {machine_id}{scope}",
        metadata={
            "record_type": "alarm_summary",
            "aggregation": "count",
            "alarm_code": alarm_code,
            "occurrence_count": count,
            "time_start": start_text,
            "time_end": end_text,
        },
    )


def telemetry_summary_to_evidence(
    machine_id: str,
    summary: TelemetrySummary,
) -> Evidence:
    """Map one repository telemetry summary to frozen Evidence (values only)."""

    digest = _stable_digest(
        machine_id, summary.start_time or "", summary.end_time or "", TELEMETRY_SUMMARY_SCHEMA
    )
    lines = [
        f"Telemetry summary for {machine_id} "
        f"({summary.sample_count} samples between {summary.start_time} and {summary.end_time})."
    ]
    for name in sorted(summary.metrics):
        stats = summary.metrics[name]
        lines.append(
            f"{name}: count={stats.count}, min={_number_text(stats.min)}, "
            f"max={_number_text(stats.max)}, mean={_number_text(stats.mean)}, "
            f"first={_number_text(stats.first)}, last={_number_text(stats.last)}"
        )
    return Evidence(
        evidence_id=f"EVIDENCE-TELEMETRY-SUMMARY-{machine_id}-{digest}",
        source_type=EvidenceSourceType.TELEMETRY,
        provenance=EvidenceProvenance(
            source_kind=SourceKind.DEMO_FACTORY,
            source_dataset="manufacturaiq_demo_factory",
            source_id=f"TELEMETRY-SUMMARY-{machine_id}-{digest}",
            record_id=None,
        ),
        machine_id=machine_id,
        title=f"Telemetry summary — {machine_id} — {summary.sample_count} samples",
        content="\n".join(lines),
        metadata={
            "record_type": "telemetry_summary",
            "aggregation": "summary",
            "time_start": summary.start_time,
            "time_end": summary.end_time,
            "metrics": sorted(summary.metrics),
            "sample_count": summary.sample_count,
        },
    )


class MaintenanceAgent:
    """Answers "what maintenance/alarm/condition evidence exists?" and nothing more.

    Thin async wrapper over the three structured repositories: it resolves a
    deterministic time window per source, maps rows to frozen ``Evidence``
    with stable IDs, and packages them into a frozen ``AgentResult``. No
    thresholds, no diagnosis, no LLM, no RAG, no fusion.
    """

    def __init__(
        self,
        maintenance_repository: MaintenanceRepository,
        alarm_repository: AlarmRepository,
        telemetry_repository: TelemetryRepository,
        *,
        settings: Settings | None = None,
        maintenance_limit: int | None = None,
        alarm_limit: int | None = None,
        telemetry_lookback_hours: int | float | None = None,
        alarm_summary_limit: int | None = None,
    ) -> None:
        resolved = settings or get_settings()
        self._maintenance_repository = maintenance_repository
        self._alarm_repository = alarm_repository
        self._telemetry_repository = telemetry_repository
        self._settings = resolved
        self._maintenance_limit = self._checked_limit(
            maintenance_limit, resolved.maintenance_agent_maintenance_limit, "maintenance_limit"
        )
        self._alarm_limit = self._checked_limit(
            alarm_limit, resolved.maintenance_agent_alarm_limit, "alarm_limit"
        )
        self._alarm_summary_limit = self._checked_limit(
            alarm_summary_limit,
            resolved.maintenance_agent_alarm_summary_limit,
            "alarm_summary_limit",
        )
        lookback = (
            telemetry_lookback_hours
            if telemetry_lookback_hours is not None
            else resolved.maintenance_agent_telemetry_lookback_hours
        )
        if isinstance(lookback, bool) or not isinstance(lookback, (int, float)) or lookback <= 0:
            raise ValueError("telemetry_lookback_hours must be a positive number")
        self._telemetry_lookback_hours = lookback

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

    async def _resolve_telemetry_window(
        self, machine_id: str, query: QueryRequest
    ) -> tuple[datetime | None, datetime | None]:
        """Deterministic (start, end) for the telemetry summary, or (None, None)."""

        start = query.time_start
        end = query.time_end
        if start is not None and end is not None:
            return start, end
        lookback = timedelta(hours=self._telemetry_lookback_hours)
        if start is not None:
            latest = await self._telemetry_repository.latest_for_machine(machine_id)
            if latest is not None and latest.timestamp is not None and latest.timestamp >= start:
                return start, latest.timestamp
            return None, None
        if end is not None:
            return end - lookback, end
        latest = await self._telemetry_repository.latest_for_machine(machine_id)
        if latest is not None and latest.timestamp is not None:
            return latest.timestamp - lookback, latest.timestamp
        return None, None

    async def run(self, query: QueryRequest) -> AgentResult:
        """Collect structured maintenance evidence without interpreting it."""

        started = time.perf_counter()
        machine_id = query.machine_id
        if not machine_id:
            return AgentResult(
                agent_name=AgentName.MAINTENANCE,
                query_id=query.query_id,
                evidence=[],
                warnings=[_MISSING_MACHINE_WARNING],
                latency_ms=self._latency_ms(started),
                metadata=self._base_metadata(query, "missing_machine_id", 0, 0, 0, 0, None, None),
            )

        evidence: list[Evidence] = []
        warnings: list[str] = []
        errors: list[str] = []
        completed = 0
        failed = 0
        maintenance_count = 0
        alarm_count = 0
        alarm_summary_count = 0
        telemetry_summary_count = 0
        resolved_telemetry: tuple[datetime | None, datetime | None] = (None, None)

        # --- maintenance records (independent boundary) ---
        maintenance_failed = False
        try:
            if query.time_start is not None or query.time_end is not None:
                maintenance_rows = await self._maintenance_repository.list_by_machine_and_time_range(
                    machine_id, query.time_start, query.time_end, limit=self._maintenance_limit
                )
            else:
                maintenance_rows = await self._maintenance_repository.recent_for_machine(
                    machine_id, limit=self._maintenance_limit
                )
            completed += 1
        except EXPECTED_SOURCE_FAILURES as exc:
            maintenance_rows = []
            maintenance_failed = True
            failed += 1
            errors.append(f"Maintenance retrieval failed: {exc}")
            warnings.append("Maintenance evidence unavailable; returning partial results.")
        maintenance_evidence = [maintenance_record_to_evidence(row) for row in maintenance_rows]
        maintenance_count = len(maintenance_evidence)
        if not maintenance_rows and not maintenance_failed:
            warnings.append(f"No maintenance history found for {machine_id}.")
        evidence.extend(maintenance_evidence)

        # --- alarm records (independent boundary) ---
        alarm_rows: list[AlarmRecord] = []
        alarm_list_failed = False
        try:
            if query.time_start is not None or query.time_end is not None:
                alarm_rows = await self._alarm_repository.list_by_machine_and_time_range(
                    machine_id, query.time_start, query.time_end, limit=self._alarm_limit
                )
            else:
                alarm_rows = await self._alarm_repository.recent_for_machine(
                    machine_id, limit=self._alarm_limit
                )
            completed += 1
        except EXPECTED_SOURCE_FAILURES as exc:
            alarm_list_failed = True
            failed += 1
            errors.append(f"Alarm retrieval failed: {exc}")
            warnings.append("Alarm evidence unavailable; returning partial results.")

        # --- alarm recurrence summaries (deterministic counts, not diagnosis) ---
        summary_evidence: list[Evidence] = []
        if alarm_rows:
            seen_codes: list[str] = []
            for row in alarm_rows:
                if row.alarm_code and row.alarm_code not in seen_codes:
                    seen_codes.append(row.alarm_code)
            window_start = _iso(query.time_start)
            window_end = _iso(query.time_end)
            for code in seen_codes:
                if len(summary_evidence) >= self._alarm_summary_limit:
                    break
                try:
                    count = await self._alarm_repository.count_occurrences(
                        machine_id, code, query.time_start, query.time_end
                    )
                except EXPECTED_SOURCE_FAILURES as exc:
                    failed += 1
                    errors.append(f"Alarm recurrence count failed for {code}: {exc}")
                    warnings.append("Alarm evidence unavailable; returning partial results.")
                    continue
                if count > 1:
                    representative = next(row for row in alarm_rows if row.alarm_code == code)
                    summary_evidence.append(
                        alarm_summary_to_evidence(
                            machine_id,
                            code,
                            count,
                            window_start,
                            window_end,
                            representative.source_dataset,
                        )
                    )
        alarm_summary_count = len(summary_evidence)
        evidence.extend(summary_evidence)
        alarm_evidence = [alarm_record_to_evidence(row) for row in alarm_rows]
        alarm_count = len(alarm_evidence)
        if not alarm_rows and not alarm_list_failed:
            warnings.append(f"No alarms found for {machine_id}.")
        evidence.extend(alarm_evidence)

        # --- telemetry summary (independent boundary) ---
        try:
            resolved_telemetry = await self._resolve_telemetry_window(machine_id, query)
            telemetry_start, telemetry_end = resolved_telemetry
            if telemetry_start is None or telemetry_end is None:
                warnings.append(
                    "No telemetry available for the requested machine/time window."
                )
            else:
                summary = await self._telemetry_repository.summarize(
                    machine_id, telemetry_start, telemetry_end
                )
                completed += 1
                if summary.sample_count == 0:
                    warnings.append(
                        "No telemetry available for the requested machine/time window."
                    )
                else:
                    evidence.append(telemetry_summary_to_evidence(machine_id, summary))
                    telemetry_summary_count = 1
        except EXPECTED_SOURCE_FAILURES as exc:
            failed += 1
            resolved_telemetry = (None, None)
            errors.append(f"Telemetry retrieval failed: {exc}")
            warnings.append("Telemetry evidence unavailable; returning partial results.")

        if failed > 0 and completed == 0:
            status = "failed"
        elif failed > 0:
            status = "partial"
        elif not evidence:
            status = "empty"
        else:
            status = "ok"
        return AgentResult(
            agent_name=AgentName.MAINTENANCE,
            query_id=query.query_id,
            evidence=evidence,
            warnings=warnings,
            errors=errors,
            latency_ms=self._latency_ms(started),
            metadata=self._base_metadata(
                query,
                status,
                maintenance_count,
                alarm_count,
                alarm_summary_count,
                telemetry_summary_count,
                _iso(resolved_telemetry[0]),
                _iso(resolved_telemetry[1]),
            ),
        )

    def _base_metadata(
        self,
        query: QueryRequest,
        status: str,
        maintenance_count: int,
        alarm_count: int,
        alarm_summary_count: int,
        telemetry_summary_count: int,
        resolved_telemetry_start: str | None,
        resolved_telemetry_end: str | None,
    ) -> dict[str, Any]:
        return {
            "machine_id": query.machine_id,
            "maintenance_count": maintenance_count,
            "alarm_count": alarm_count,
            "alarm_summary_count": alarm_summary_count,
            "telemetry_summary_count": telemetry_summary_count,
            "requested_time_start": _iso(query.time_start),
            "requested_time_end": _iso(query.time_end),
            "resolved_telemetry_start": resolved_telemetry_start,
            "resolved_telemetry_end": resolved_telemetry_end,
            "retrieval_status": status,
        }


def build_maintenance_agent(
    settings: Settings | None = None,
    database_path: str | None = None,
) -> MaintenanceAgent:
    """Construct a MaintenanceAgent on the canonical operational database."""

    from app.db.connection import DatabaseConnection

    resolved = settings or get_settings()
    database = DatabaseConnection(database_path) if database_path else DatabaseConnection()
    return MaintenanceAgent(
        MaintenanceRepository(database),
        AlarmRepository(database),
        TelemetryRepository(database),
        settings=resolved,
    )
