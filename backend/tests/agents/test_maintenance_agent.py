from __future__ import annotations

import inspect
import typing
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.agents.maintenance import (
    MaintenanceAgent,
    alarm_record_to_evidence,
    alarm_summary_to_evidence,
    build_maintenance_agent,
    maintenance_record_to_evidence,
    telemetry_summary_to_evidence,
)
from app.contracts import agents as agents_contract_module
from app.contracts import evidence as evidence_contract_module
from app.contracts.agents import AgentResult
from app.contracts.enums import AgentName, EvidenceSourceType, SourceKind
from app.contracts.evidence import Evidence
from app.contracts.query import QueryRequest
from app.core.exceptions import DatabaseError, RepositoryError
from app.db.models import AlarmRecord, MaintenanceRecord, TelemetryRecord
from app.protocols.agents import Agent
from app.repositories.telemetry import MetricStats, TelemetrySummary

SOURCE_DATASET = "manufacturaiq_demo_factory"
START = datetime(2026, 9, 10, 8, 0, 0)
END = datetime(2026, 9, 20, 8, 0, 0)

FORBIDDEN_DIAGNOSIS_TERMS = (
    "root cause",
    "diagnos",
    "anomal",
    "health score",
    "recommended repair",
    "probability",
    "predicted",
    "prediction",
    "abnormal",
    "overheat",
    "excessive vibration",
    "degradation",
)


def make_query(**overrides) -> QueryRequest:
    fields: dict = {"query_id": "Q-MNT-1", "query": "show maintenance history"}
    fields.update(overrides)
    return QueryRequest(**fields)


def make_maintenance(index: int, machine_id: str = "CNC-05", **overrides) -> MaintenanceRecord:
    fields: dict = {
        "maintenance_id": f"MNT-{index:06d}",
        "machine_id": machine_id,
        "created_at": START + timedelta(days=index),
        "started_at": START + timedelta(days=index, hours=1),
        "completed_at": START + timedelta(days=index, hours=3),
        "maintenance_type": "CONDITION_BASED",
        "symptom": f"symptom {index}",
        "component": "spindle",
        "failure_code": None,
        "inspection_findings": f"findings {index}",
        "action_taken": f"action {index}",
        "planned_downtime_min": 60,
        "actual_downtime_min": 45,
        "status": "COMPLETE",
        "is_synthetic": True,
        "source_dataset": SOURCE_DATASET,
    }
    fields.update(overrides)
    return MaintenanceRecord(**fields)


def make_alarm(
    index: int, machine_id: str = "CNC-05", code: str = "ALM-SERVO-03", **overrides
) -> AlarmRecord:
    fields: dict = {
        "alarm_id": f"ALM-{index:06d}",
        "machine_id": machine_id,
        "timestamp": START + timedelta(hours=index),
        "alarm_code": code,
        "severity": "WARNING",
        "category": "SERVO",
        "description": f"description {index}",
        "acknowledged": True,
        "acknowledged_at": START + timedelta(hours=index, minutes=30),
        "related_batch_id": None,
        "is_synthetic": True,
        "source_dataset": SOURCE_DATASET,
    }
    fields.update(overrides)
    return AlarmRecord(**fields)


def make_telemetry(timestamp: datetime = END, machine_id: str = "CNC-05") -> TelemetryRecord:
    return TelemetryRecord(
        telemetry_id="TEL-000001",
        machine_id=machine_id,
        timestamp=timestamp,
        rpm=2000.0,
        vibration_mm_s=1.1,
        temperature_c=45.0,
        current_a=5.0,
        load_pct=60.0,
        spindle_power_kw=3.0,
        is_synthetic=True,
        source_dataset=SOURCE_DATASET,
    )


def make_summary(start: datetime = START, end: datetime = END) -> TelemetrySummary:    return TelemetrySummary(
        machine_id="CNC-05",
        start_time=start.isoformat(),
        end_time=end.isoformat(),
        sample_count=100,
        metrics={
            "rpm": MetricStats(count=100, min=1000.0, max=3000.0, mean=2000.0, first=1000.0, last=3000.0),
            "vibration_mm_s": MetricStats(count=100, min=0.5, max=2.5, mean=1.1, first=0.5, last=2.5),
        },
    )


class FakeMaintenanceRepository:
    def __init__(self, rows: list | None = None, error: Exception | None = None):
        self._rows = list(rows or [])
        self._error = error
        self.calls: list = []

    async def list_by_machine_and_time_range(self, machine_id, start_time=None, end_time=None, limit=100):
        self.calls.append(("range", machine_id, start_time, end_time, limit))
        if self._error is not None:
            raise self._error
        return list(self._rows)

    async def recent_for_machine(self, machine_id, limit=10):
        self.calls.append(("recent", machine_id, limit))
        if self._error is not None:
            raise self._error
        return list(self._rows)[:limit]


class FakeAlarmRepository:
    def __init__(self, rows: list | None = None, counts: dict | None = None, error: Exception | None = None):
        self._rows = list(rows or [])
        self._counts = dict(counts or {})
        self._error = error
        self.calls: list = []

    async def list_by_machine_and_time_range(self, machine_id, start_time=None, end_time=None, limit=100):
        self.calls.append(("range", machine_id, start_time, end_time, limit))
        if self._error is not None:
            raise self._error
        return list(self._rows)

    async def recent_for_machine(self, machine_id, limit=10):
        self.calls.append(("recent", machine_id, limit))
        if self._error is not None:
            raise self._error
        return list(self._rows)[:limit]

    async def count_occurrences(self, machine_id, alarm_code, start_time=None, end_time=None):
        self.calls.append(("count", machine_id, alarm_code, start_time, end_time))
        if self._error is not None:
            raise self._error
        return self._counts.get(alarm_code, 0)


class FakeTelemetryRepository:
    def __init__(self, latest=None, summary: TelemetrySummary | None = None, error: Exception | None = None):
        self._latest = latest
        self._summary = summary
        self._error = error
        self.calls: list = []

    async def latest_for_machine(self, machine_id):
        self.calls.append(("latest", machine_id))
        if self._error is not None:
            raise self._error
        return self._latest

    async def summarize(self, machine_id, start_time=None, end_time=None):
        self.calls.append(("summarize", machine_id, start_time, end_time))
        if self._error is not None:
            raise self._error
        assert self._summary is not None
        return self._summary


def make_agent(
    maintenance=None, alarms=None, counts=None, latest=None, summary=None, error=None, **kwargs
) -> tuple[MaintenanceAgent, FakeMaintenanceRepository, FakeAlarmRepository, FakeTelemetryRepository]:
    maintenance_repo = FakeMaintenanceRepository(maintenance, error=error.get("maintenance") if error else None)
    alarm_repo = FakeAlarmRepository(alarms, counts, error=error.get("alarm") if error else None)
    telemetry_repo = FakeTelemetryRepository(latest, summary, error=error.get("telemetry") if error else None)
    agent = MaintenanceAgent(maintenance_repo, alarm_repo, telemetry_repo, **kwargs)
    return agent, maintenance_repo, alarm_repo, telemetry_repo


def full_agent(**kwargs) -> tuple[MaintenanceAgent, FakeMaintenanceRepository, FakeAlarmRepository, FakeTelemetryRepository]:
    return make_agent(
        maintenance=[make_maintenance(0), make_maintenance(1)],
        alarms=[make_alarm(0), make_alarm(1)],
        counts={"ALM-SERVO-03": 2},
        latest=make_telemetry(),
        summary=make_summary(),
        **kwargs,
    )


def test_satisfies_frozen_agent_protocol() -> None:
    assert inspect.iscoroutinefunction(MaintenanceAgent.run)
    hints = typing.get_type_hints(MaintenanceAgent.run)
    assert hints["query"] is QueryRequest
    assert hints["return"] is AgentResult
    agent_hints = typing.get_type_hints(Agent.run)
    assert agent_hints["query"] is hints["query"]
    assert agent_hints["return"] is hints["return"]


async def test_returns_maintenance_agent_name() -> None:
    agent, _, _, _ = full_agent()
    result = await agent.run(make_query(machine_id="CNC-05"))

    assert result.agent_name is AgentName.MAINTENANCE
    assert result.agent_name.value == "MAINTENANCE"


async def test_preserves_query_id() -> None:
    agent, _, _, _ = full_agent()
    result = await agent.run(make_query(query_id="Q-KEEP-9", machine_id="CNC-05"))

    assert result.query_id == "Q-KEEP-9"


async def test_missing_machine_id_warns_without_error_or_calls() -> None:
    agent, maintenance_repo, alarm_repo, telemetry_repo = full_agent()
    result = await agent.run(make_query(query="CNC-05 is vibrating"))

    assert result.evidence == []
    assert result.errors == []
    assert result.warnings == [
        "machine_id is required for maintenance evidence; no repository queries were performed."
    ]
    assert result.metadata["retrieval_status"] == "missing_machine_id"
    assert result.metadata["machine_id"] is None
    assert maintenance_repo.calls == []
    assert alarm_repo.calls == []
    assert telemetry_repo.calls == []


def test_maintenance_record_maps_to_frozen_evidence() -> None:
    evidence = maintenance_record_to_evidence(make_maintenance(7))

    assert isinstance(evidence, Evidence)
    assert evidence.evidence_id == "EVIDENCE-MAINTENANCE-MNT-000007"
    assert evidence.source_type.value == "MAINTENANCE"
    assert evidence.machine_id == "CNC-05"
    assert evidence.product_id is None
    assert evidence.batch_id is None
    assert "CONDITION_BASED" in evidence.title
    assert "MNT-000007" in evidence.title
    assert "symptom 7" in evidence.content
    assert "findings 7" in evidence.content
    assert evidence.observed_at == START + timedelta(days=7, hours=1)
    assert evidence.retrieval_score is None
    assert evidence.decision_score is None


def test_maintenance_evidence_ids_are_deterministic() -> None:
    record = make_maintenance(7)

    assert (
        maintenance_record_to_evidence(record).evidence_id
        == maintenance_record_to_evidence(record).evidence_id
        == "EVIDENCE-MAINTENANCE-MNT-000007"
    )


def test_maintenance_provenance_is_complete() -> None:
    evidence = maintenance_record_to_evidence(make_maintenance(7))
    provenance = evidence.provenance

    assert provenance.source_kind.value == "DEMO_FACTORY"
    assert provenance.source_dataset == SOURCE_DATASET
    assert provenance.source_id == "MNT-000007"
    assert provenance.record_id == "MNT-000007"
    assert provenance.document_id is None
    assert provenance.chunk_id is None
    assert provenance.page_start is None
    assert provenance.page_end is None


def test_alarm_record_maps_to_frozen_evidence() -> None:
    evidence = alarm_record_to_evidence(make_alarm(3))

    assert isinstance(evidence, Evidence)
    assert evidence.evidence_id == "EVIDENCE-ALARM-ALM-000003"
    assert evidence.source_type.value == "ALARM"
    assert evidence.machine_id == "CNC-05"
    assert "ALM-SERVO-03" in evidence.title
    assert "WARNING" in evidence.content
    assert "description 3" in evidence.content
    assert evidence.observed_at == START + timedelta(hours=3)
    assert evidence.retrieval_score is None
    assert evidence.decision_score is None


def test_alarm_evidence_ids_are_deterministic() -> None:
    record = make_alarm(3)

    assert (
        alarm_record_to_evidence(record).evidence_id
        == alarm_record_to_evidence(record).evidence_id
        == "EVIDENCE-ALARM-ALM-000003"
    )


def test_alarm_provenance_is_complete() -> None:
    evidence = alarm_record_to_evidence(make_alarm(3))
    provenance = evidence.provenance

    assert provenance.source_kind.value == "DEMO_FACTORY"
    assert provenance.source_id == "ALM-000003"
    assert provenance.record_id == "ALM-000003"
    assert provenance.document_id is None
    assert provenance.chunk_id is None


def test_telemetry_summary_maps_to_frozen_evidence() -> None:
    evidence = telemetry_summary_to_evidence("CNC-05", make_summary())

    assert isinstance(evidence, Evidence)
    assert evidence.source_type.value == "TELEMETRY"
    assert evidence.machine_id == "CNC-05"
    assert "100 samples" in evidence.title
    assert "rpm: count=100" in evidence.content
    assert "vibration_mm_s: count=100" in evidence.content
    assert evidence.retrieval_score is None
    assert evidence.decision_score is None
    assert evidence.metadata["aggregation"] == "summary"
    assert evidence.metadata["sample_count"] == 100
    assert evidence.metadata["metrics"] == ["rpm", "vibration_mm_s"]


def test_telemetry_summary_id_is_deterministic() -> None:
    first = telemetry_summary_to_evidence("CNC-05", make_summary())
    second = telemetry_summary_to_evidence("CNC-05", make_summary())

    assert first.evidence_id == second.evidence_id
    assert first.evidence_id.startswith("EVIDENCE-TELEMETRY-SUMMARY-CNC-05-")
    assert len(first.evidence_id.split("-")[-1]) == 12


def test_telemetry_aggregate_record_id_is_null() -> None:
    evidence = telemetry_summary_to_evidence("CNC-05", make_summary())

    assert evidence.provenance.record_id is None
    assert evidence.provenance.document_id is None
    assert evidence.provenance.chunk_id is None
    assert evidence.provenance.page_start is None


async def test_all_scores_are_null() -> None:
    agent, _, _, _ = full_agent()
    result = await agent.run(make_query(machine_id="CNC-05"))

    assert result.evidence
    assert all(item.retrieval_score is None for item in result.evidence)
    assert all(item.decision_score is None for item in result.evidence)


async def test_evidence_ordering_is_deterministic() -> None:
    agent, _, _, _ = full_agent()
    first = await agent.run(make_query(machine_id="CNC-05"))
    second = await agent.run(make_query(machine_id="CNC-05"))

    assert [item.evidence_id for item in first.evidence] == [
        item.evidence_id for item in second.evidence
    ]
    kinds = [item.metadata["record_type"] for item in first.evidence]
    assert kinds == ["maintenance", "maintenance", "alarm_summary", "alarm", "alarm", "telemetry_summary"]


async def test_repository_order_preserved_within_groups() -> None:
    rows = [make_maintenance(2), make_maintenance(0), make_maintenance(1)]
    agent, _, _, _ = make_agent(maintenance=rows, summary=make_summary())
    result = await agent.run(make_query(machine_id="CNC-05"))

    maintenance_ids = [
        item.provenance.record_id for item in result.evidence if item.metadata["record_type"] == "maintenance"
    ]
    assert maintenance_ids == ["MNT-000002", "MNT-000000", "MNT-000001"]


async def test_query_time_start_forwarded() -> None:
    agent, maintenance_repo, alarm_repo, telemetry_repo = full_agent()
    await agent.run(make_query(machine_id="CNC-05", time_start=START, time_end=END))

    assert maintenance_repo.calls[0] == ("range", "CNC-05", START, END, 8)
    assert alarm_repo.calls[0] == ("range", "CNC-05", START, END, 10)
    assert ("summarize", "CNC-05", START, END) in telemetry_repo.calls


async def test_query_time_end_forwarded_without_start() -> None:
    agent, _, _, telemetry_repo = full_agent()
    result = await agent.run(make_query(machine_id="CNC-05", time_end=END))

    expected_start = END - timedelta(hours=168)
    assert ("summarize", "CNC-05", expected_start, END) in telemetry_repo.calls
    assert result.metadata["resolved_telemetry_start"] == expected_start.isoformat()
    assert result.metadata["resolved_telemetry_end"] == END.isoformat()


async def test_no_time_window_uses_configured_telemetry_lookback() -> None:
    agent, maintenance_repo, alarm_repo, telemetry_repo = full_agent()
    result = await agent.run(make_query(machine_id="CNC-05"))

    assert maintenance_repo.calls[0] == ("recent", "CNC-05", 8)
    assert alarm_repo.calls[0] == ("recent", "CNC-05", 10)
    expected_start = END - timedelta(hours=168)
    assert ("summarize", "CNC-05", expected_start, END) in telemetry_repo.calls
    summaries = [item for item in result.evidence if item.metadata["record_type"] == "telemetry_summary"]
    assert len(summaries) == 1


async def test_only_start_resolves_end_from_latest_telemetry() -> None:
    agent, _, _, telemetry_repo = full_agent()
    result = await agent.run(make_query(machine_id="CNC-05", time_start=START))

    assert ("summarize", "CNC-05", START, END) in telemetry_repo.calls
    assert result.metadata["resolved_telemetry_end"] == END.isoformat()


async def test_no_telemetry_warns_but_preserves_other_evidence() -> None:
    agent, _, _, _ = make_agent(
        maintenance=[make_maintenance(0)], alarms=[make_alarm(0)], counts={"ALM-SERVO-03": 1}
    )
    result = await agent.run(make_query(machine_id="CNC-05"))

    assert result.errors == []
    assert "No telemetry available for the requested machine/time window." in result.warnings
    kinds = {item.metadata["record_type"] for item in result.evidence}
    assert kinds == {"maintenance", "alarm"}


async def test_no_maintenance_warns_but_preserves_other_evidence() -> None:
    agent, _, _, _ = make_agent(
        alarms=[make_alarm(0)],
        counts={"ALM-SERVO-03": 1},
        latest=make_telemetry(),
        summary=make_summary(),
    )
    result = await agent.run(make_query(machine_id="CNC-05"))

    assert "No maintenance history found for CNC-05." in result.warnings
    kinds = {item.metadata["record_type"] for item in result.evidence}
    assert kinds == {"alarm", "telemetry_summary"}


async def test_no_alarms_warns_but_preserves_other_evidence() -> None:
    agent, _, _, _ = make_agent(
        maintenance=[make_maintenance(0)], latest=make_telemetry(), summary=make_summary()
    )
    result = await agent.run(make_query(machine_id="CNC-05"))

    assert "No alarms found for CNC-05." in result.warnings
    kinds = {item.metadata["record_type"] for item in result.evidence}
    assert kinds == {"maintenance", "telemetry_summary"}


async def test_repeated_alarms_produce_deterministic_occurrence_summary() -> None:
    agent, _, _, _ = make_agent(
        alarms=[make_alarm(0), make_alarm(1)],
        counts={"ALM-SERVO-03": 3},
        summary=make_summary(),
    )
    result = await agent.run(make_query(machine_id="CNC-05", time_start=START, time_end=END))

    summaries = [item for item in result.evidence if item.metadata["record_type"] == "alarm_summary"]
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.metadata["occurrence_count"] == 3
    assert "occurred 3 times for CNC-05 between" in summary.content
    assert summary.provenance.record_id is None
    assert summary.evidence_id.startswith("EVIDENCE-ALARM-SUMMARY-CNC-05-ALM-SERVO-03-")
    repeat = await agent.run(make_query(machine_id="CNC-05", time_start=START, time_end=END))
    repeat_ids = [item.evidence_id for item in repeat.evidence if item.metadata["record_type"] == "alarm_summary"]
    assert repeat_ids == [summary.evidence_id]


async def test_single_alarm_creates_no_recurrence_summary() -> None:
    agent, _, _, _ = make_agent(
        alarms=[make_alarm(0)], counts={"ALM-SERVO-03": 1}, summary=make_summary()
    )
    result = await agent.run(make_query(machine_id="CNC-05"))

    assert [item for item in result.evidence if item.metadata["record_type"] == "alarm_summary"] == []


async def test_recurrence_count_uses_repository_count_not_list_length() -> None:
    agent, _, alarm_repo, _ = make_agent(
        alarms=[make_alarm(0)], counts={"ALM-SERVO-03": 5}, summary=make_summary()
    )
    result = await agent.run(make_query(machine_id="CNC-05"))

    assert ("count", "CNC-05", "ALM-SERVO-03", None, None) in alarm_repo.calls
    summaries = [item for item in result.evidence if item.metadata["record_type"] == "alarm_summary"]
    assert len(summaries) == 1
    assert "occurred 5 times" in summaries[0].content


async def test_partial_repository_failure_preserves_successful_evidence() -> None:
    agent, _, _, _ = make_agent(
        maintenance=[make_maintenance(0)],
        alarms=[make_alarm(0)],
        counts={"ALM-SERVO-03": 1},
        summary=make_summary(),
        error={"telemetry": DatabaseError("telemetry store offline")},
    )
    result = await agent.run(make_query(machine_id="CNC-05"))

    kinds = {item.metadata["record_type"] for item in result.evidence}
    assert kinds == {"maintenance", "alarm"}
    assert result.errors == ["Telemetry retrieval failed: telemetry store offline"]
    assert "Telemetry evidence unavailable; returning partial results." in result.warnings
    assert result.metadata["retrieval_status"] == "partial"


async def test_complete_repository_failure_returns_safe_errors() -> None:
    failure = RepositoryError("database offline")
    agent, _, _, _ = make_agent(
        error={"maintenance": failure, "alarm": failure, "telemetry": failure}
    )
    result = await agent.run(make_query(machine_id="CNC-05"))

    assert result.evidence == []
    assert len(result.errors) == 3
    assert all("Traceback" not in message for message in result.errors)
    assert result.metadata["retrieval_status"] == "failed"
    assert result.metadata["machine_id"] == "CNC-05"


async def test_unexpected_programming_error_propagates() -> None:
    agent, _, _, _ = make_agent(error={"maintenance": ValueError("bad row")})

    with pytest.raises(ValueError, match="bad row"):
        await agent.run(make_query(machine_id="CNC-05"))


async def test_latency_is_populated_and_non_negative() -> None:
    agent, _, _, _ = full_agent()
    result = await agent.run(make_query(machine_id="CNC-05"))

    assert isinstance(result.latency_ms, float)
    assert result.latency_ms >= 0


async def test_metadata_counts_are_correct() -> None:
    agent, _, _, _ = full_agent()
    result = await agent.run(make_query(machine_id="CNC-05", time_start=START, time_end=END))

    assert result.metadata["machine_id"] == "CNC-05"
    assert result.metadata["maintenance_count"] == 2
    assert result.metadata["alarm_count"] == 2
    assert result.metadata["alarm_summary_count"] == 1
    assert result.metadata["telemetry_summary_count"] == 1
    assert result.metadata["requested_time_start"] == START.isoformat()
    assert result.metadata["requested_time_end"] == END.isoformat()
    assert result.metadata["resolved_telemetry_start"] == START.isoformat()
    assert result.metadata["resolved_telemetry_end"] == END.isoformat()
    assert result.metadata["retrieval_status"] == "ok"


async def test_no_diagnosis_or_threshold_language_generated() -> None:
    agent, _, _, _ = full_agent()
    result = await agent.run(make_query(machine_id="CNC-05"))

    blob = "\n".join(
        [item.title + "\n" + item.content for item in result.evidence]
        + result.warnings
        + [str(result.metadata)]
    ).lower()
    for term in FORBIDDEN_DIAGNOSIS_TERMS:
        assert term not in blob, f"diagnosis-like language generated: {term}"


async def test_product_id_does_not_alter_maintenance_retrieval() -> None:
    agent, maintenance_repo, alarm_repo, _ = full_agent()
    plain = await agent.run(make_query(machine_id="CNC-05"))
    with_product = await agent.run(make_query(machine_id="CNC-05", product_id="SHAFT-A"))

    assert [item.evidence_id for item in with_product.evidence] == [
        item.evidence_id for item in plain.evidence
    ]
    assert maintenance_repo.calls == maintenance_repo.calls[:1] * 2
    assert alarm_repo.calls[:2] == alarm_repo.calls[2:]


async def test_batch_id_does_not_alter_maintenance_retrieval() -> None:
    agent, maintenance_repo, alarm_repo, _ = full_agent()
    plain = await agent.run(make_query(machine_id="CNC-05"))
    with_batch = await agent.run(make_query(machine_id="CNC-05", batch_id="B-77"))

    assert [item.evidence_id for item in with_batch.evidence] == [
        item.evidence_id for item in plain.evidence
    ]
    assert maintenance_repo.calls == maintenance_repo.calls[:1] * 2
    assert alarm_repo.calls[:2] == alarm_repo.calls[2:]


async def test_query_text_is_never_parsed_into_machine_id() -> None:
    agent, maintenance_repo, _, _ = full_agent()
    await agent.run(make_query(query="CNC-05 is vibrating", machine_id="CNC-03"))

    assert maintenance_repo.calls[0][1] == "CNC-03"


@pytest.mark.parametrize("bad_limit", [0, -1, "8", True])
def test_invalid_limits_are_rejected_loudly(bad_limit) -> None:
    from app.repositories.alarms import AlarmRepository
    from app.repositories.maintenance import MaintenanceRepository
    from app.repositories.telemetry import TelemetryRepository

    with pytest.raises(ValueError):
        MaintenanceAgent(
            MaintenanceRepository(),
            AlarmRepository(),
            TelemetryRepository(),
            maintenance_limit=bad_limit,
        )
    with pytest.raises(ValueError):
        MaintenanceAgent(
            MaintenanceRepository(),
            AlarmRepository(),
            TelemetryRepository(),
            alarm_limit=bad_limit,
        )
    with pytest.raises(ValueError):
        MaintenanceAgent(
            MaintenanceRepository(),
            AlarmRepository(),
            TelemetryRepository(),
            alarm_summary_limit=bad_limit,
        )


@pytest.mark.parametrize("bad_lookback", [0, -5, "168", True])
def test_invalid_lookback_is_rejected_loudly(bad_lookback) -> None:
    from app.repositories.alarms import AlarmRepository
    from app.repositories.maintenance import MaintenanceRepository
    from app.repositories.telemetry import TelemetryRepository

    with pytest.raises(ValueError):
        MaintenanceAgent(
            MaintenanceRepository(),
            AlarmRepository(),
            TelemetryRepository(),
            telemetry_lookback_hours=bad_lookback,
        )


def test_module_respects_dependency_boundaries() -> None:
    source = (Path(__file__).resolve().parents[2] / "app" / "agents" / "maintenance.py").read_text(
        encoding="utf-8"
    )
    lowered = source.lower()
    for forbidden in (
        "app.rag",
        "documentagent",
        "documentretriever",
        "qualityrepository",
        "productionrepository",
        "externaldatasetrepository",
        "app.reasoning",
        "app.decision",
        "app.orchestration",
        "gemini",
        "openai",
        "groq",
        "typesafe",
        "jev",
        "langgraph",
    ):
        assert forbidden not in lowered, f"forbidden dependency reference: {forbidden}"


def test_module_uses_repositories_not_sql() -> None:
    source = (Path(__file__).resolve().parents[2] / "app" / "agents" / "maintenance.py").read_text(
        encoding="utf-8"
    )
    assert "sqlite3" not in source
    assert "aiosqlite" not in source
    assert "sql_safety" not in source
    for keyword in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert keyword not in source


def test_returns_frozen_contract_models() -> None:
    assert agents_contract_module.AgentResult is AgentResult
    assert evidence_contract_module.Evidence is Evidence
    assert AgentResult.__module__ == "app.contracts.agents"
    assert Evidence.__module__ == "app.contracts.evidence"


def _canonical_database_path():
    from app.core.config import get_settings

    return get_settings().default_database_path


def _real_repositories():
    from app.db.connection import DatabaseConnection
    from app.repositories.alarms import AlarmRepository
    from app.repositories.maintenance import MaintenanceRepository
    from app.repositories.telemetry import TelemetryRepository

    database = DatabaseConnection(_canonical_database_path())
    return (
        MaintenanceRepository(database),
        AlarmRepository(database),
        TelemetryRepository(database),
    )


async def _run_cnc_case(machine_id: str, start: datetime, end: datetime) -> AgentResult:
    maintenance_repo, alarm_repo, telemetry_repo = _real_repositories()
    agent = MaintenanceAgent(
        maintenance_repo,
        alarm_repo,
        telemetry_repo,
        maintenance_limit=100,
        alarm_limit=100,
    )
    return await agent.run(make_query(query_id=f"Q-INT-{machine_id}", query="machine condition", machine_id=machine_id, time_start=start, time_end=end))


def _assert_factual_evidence(result: AgentResult, machine_id: str) -> None:
    assert result.agent_name is AgentName.MAINTENANCE
    assert result.evidence
    assert result.errors == []
    for item in result.evidence:
        assert isinstance(item, Evidence)
        assert item.machine_id == machine_id
        assert item.retrieval_score is None
        assert item.decision_score is None
        assert item.provenance.source_kind.value == "DEMO_FACTORY"
        assert item.provenance.source_dataset == SOURCE_DATASET


async def test_integration_cnc05_full_window() -> None:
    result = await _run_cnc_case("CNC-05", datetime(2026, 9, 1), datetime(2026, 10, 16))

    _assert_factual_evidence(result, "CNC-05")
    assert result.metadata["maintenance_count"] == 25
    assert result.metadata["alarm_count"] == 17
    assert result.metadata["alarm_summary_count"] == 2
    assert result.metadata["telemetry_summary_count"] == 1
    assert result.metadata["retrieval_status"] == "ok"


async def test_integration_cnc03_full_window() -> None:
    result = await _run_cnc_case("CNC-03", datetime(2026, 9, 1), datetime(2026, 10, 16))

    _assert_factual_evidence(result, "CNC-03")
    assert result.metadata["maintenance_count"] == 25
    assert result.metadata["alarm_count"] == 19
    assert result.metadata["alarm_summary_count"] == 2
    assert result.metadata["telemetry_summary_count"] == 1
    assert result.metadata["retrieval_status"] == "ok"


async def test_integration_recurring_alarm_summary() -> None:
    result = await _run_cnc_case("CNC-05", datetime(2026, 9, 1), datetime(2026, 10, 16))

    summaries = [item for item in result.evidence if item.metadata.get("record_type") == "alarm_summary"]
    by_code = {item.metadata["alarm_code"]: item for item in summaries}
    assert by_code["ALM-VIB-01"].metadata["occurrence_count"] == 2
    assert "occurred 2 times for CNC-05 between" in by_code["ALM-VIB-01"].content
    assert by_code["ALM-VIB-01"].provenance.record_id is None
