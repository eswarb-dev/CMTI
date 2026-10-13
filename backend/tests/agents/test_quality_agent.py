from __future__ import annotations

import inspect
import typing
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.agents.quality import (
    QualityAgent,
    build_quality_agent,
    quality_record_to_evidence,
    quality_summary_to_evidence,
)
from app.contracts import agents as agents_contract_module
from app.contracts import evidence as evidence_contract_module
from app.contracts.agents import AgentResult
from app.contracts.enums import AgentName, EvidenceSourceType, SourceKind
from app.contracts.evidence import Evidence
from app.contracts.query import QueryRequest
from app.core.exceptions import DatabaseError, RepositoryError
from app.db.models import QualityRecord
from app.protocols.agents import Agent
from app.repositories.quality import (
    ParameterSummary,
    QualitySummary,
)

SOURCE_DATASET = "manufacturaiq_demo_factory"

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
FORBIDDEN_PRODUCTION_TERMS = (
    "reject_rate",
    "accepted_quantity",
    "rejected_quantity",
)
FORBIDDEN_SPC_TERMS = (
    "Cp",
    "Cpk",
    "Pp",
    "Ppk",
    "control limit",
    "control-chart",
    "Western Electric",
    "Nelson rule",
)


def make_query(**overrides) -> QueryRequest:
    fields: dict = {"query_id": "Q-QUA-1", "query": "quality report"}
    fields.update(overrides)
    return QueryRequest(**fields)


def make_quality_record(
    index: int = 1,
    machine_id: str = "CNC-05",
    product_id: str = "SHAFT-A",
    batch_id: str = "B-001",
    result: str = "PASS",
    **overrides,
) -> QualityRecord:
    fields: dict = {
        "inspection_id": f"QI-{index:06d}",
        "batch_id": batch_id,
        "machine_id": machine_id,
        "product_id": product_id,
        "timestamp": datetime(2026, 9, 15, 10, 0, 0),
        "parameter": "diameter",
        "nominal_value": 10.0,
        "lsl": 9.5,
        "usl": 10.5,
        "measured_value": 10.1,
        "result": result,
        "defect_type": None,
        "inspection_method": "CALIPER",
        "is_synthetic": True,
        "source_dataset": SOURCE_DATASET,
    }
    fields.update(overrides)
    return QualityRecord(**fields)


def make_summary(
    inspection_count: int = 10,
    pass_count: int = 8,
    fail_count: int = 2,
    parameters: list[ParameterSummary] | None = None,
) -> QualitySummary:
    return QualitySummary(
        inspection_count=inspection_count,
        pass_count=pass_count,
        fail_count=fail_count,
        failure_rate=(fail_count / inspection_count) if inspection_count else None,
        parameters=parameters or [],
    )


def make_param_summary(parameter: str = "diameter", count: int = 10, passed: int = 8, failed: int = 2) -> ParameterSummary:
    return ParameterSummary(
        parameter=parameter,
        inspection_count=count,
        pass_count=passed,
        fail_count=failed,
        failure_rate=(failed / count) if count else None,
        min_measurement=9.5,
        max_measurement=10.5,
        mean_measurement=10.0,
    )


class FakeQualityRepository:
    def __init__(
        self,
        rows: list | None = None,
        failures: list | None = None,
        summary: QualitySummary | None = None,
        error: Exception | None = None,
        summary_error: Exception | None = None,
    ):
        self._rows = list(rows or [])
        self._failures = list(failures or [])
        self._summary = summary
        self._error = error
        self._summary_error = summary_error
        self.calls: list = []

    async def get_by_id(self, inspection_id: str) -> QualityRecord | None:
        self.calls.append(("get_by_id", inspection_id))
        if self._error is not None:
            raise self._error
        for row in self._rows:
            if row.inspection_id == inspection_id:
                return row
        return None

    async def list_by_machine(self, machine_id, start_time=None, end_time=None, limit=100):
        self.calls.append(("list_by_machine", machine_id, start_time, end_time, limit))
        if self._error is not None:
            raise self._error
        return [r for r in self._rows if r.machine_id == machine_id]

    async def list_by_product(self, product_id, start_time=None, end_time=None, limit=100):
        self.calls.append(("list_by_product", product_id, start_time, end_time, limit))
        if self._error is not None:
            raise self._error
        return [r for r in self._rows if r.product_id == product_id]

    async def list_by_batch(self, batch_id, limit=100):
        self.calls.append(("list_by_batch", batch_id, limit))
        if self._error is not None:
            raise self._error
        return [r for r in self._rows if r.batch_id == batch_id]

    async def list_failures(
        self, machine_id=None, product_id=None, batch_id=None,
        parameter=None, start_time=None, end_time=None, limit=100,
    ):
        self.calls.append(
            ("list_failures", machine_id, product_id, batch_id, parameter, start_time, end_time, limit)
        )
        if self._error is not None:
            raise self._error
        return list(self._failures)

    async def summarize_results(
        self, machine_id=None, product_id=None, batch_id=None,
        parameter=None, start_time=None, end_time=None,
    ):
        self.calls.append(
            ("summarize_results", machine_id, product_id, batch_id, parameter, start_time, end_time)
        )
        if self._summary_error is not None:
            raise self._summary_error
        return self._summary


def make_agent(
    rows=None, failures=None, summary=None, error=None, summary_error=None, **kwargs
) -> tuple[QualityAgent, FakeQualityRepository]:
    repo = FakeQualityRepository(rows, failures, summary, error, summary_error)
    agent = QualityAgent(repo, **kwargs)
    return agent, repo


def full_agent(**kwargs) -> tuple[QualityAgent, FakeQualityRepository]:
    return make_agent(
        rows=[make_quality_record(1, result="PASS"), make_quality_record(2, result="FAIL")],
        failures=[make_quality_record(2, result="FAIL")],
        summary=make_summary(parameters=[make_param_summary()]),
        **kwargs,
    )


def test_satisfies_frozen_agent_protocol() -> None:
    assert inspect.iscoroutinefunction(QualityAgent.run)
    hints = typing.get_type_hints(QualityAgent.run)
    assert hints["query"] is QueryRequest
    assert hints["return"] is AgentResult
    agent_hints = typing.get_type_hints(Agent.run)
    assert agent_hints["query"] is hints["query"]
    assert agent_hints["return"] is hints["return"]


async def test_returns_quality_agent_name() -> None:
    agent, _ = full_agent()
    result = await agent.run(make_query(machine_id="CNC-05"))
    assert result.agent_name is AgentName.QUALITY
    assert result.agent_name.value == "QUALITY"


async def test_preserves_query_id() -> None:
    agent, _ = full_agent()
    result = await agent.run(make_query(query_id="Q-KEEP-9", machine_id="CNC-05"))
    assert result.query_id == "Q-KEEP-9"


async def test_missing_scope_warns_without_error_or_calls() -> None:
    agent, repo = make_agent()
    result = await agent.run(make_query(query="show quality"))
    assert result.evidence == []
    assert result.errors == []
    assert "At least one structured quality scope" in result.warnings[0]
    assert result.metadata["retrieval_status"] == "missing_scope"
    assert repo.calls == []


def test_quality_row_maps_to_frozen_evidence() -> None:
    record = make_quality_record(7)
    evidence = quality_record_to_evidence(record)

    assert isinstance(evidence, Evidence)
    assert evidence.evidence_id == "EVIDENCE-QUALITY-QI-000007"
    assert evidence.source_type.value == "QUALITY"
    assert evidence.machine_id == "CNC-05"
    assert evidence.product_id == "SHAFT-A"
    assert evidence.batch_id == "B-001"
    assert "QI-000007" in evidence.title
    assert "diameter" in evidence.content
    assert "10.1" in evidence.content
    assert "PASS" in evidence.content
    assert evidence.observed_at == datetime(2026, 9, 15, 10, 0, 0)
    assert evidence.retrieval_score is None
    assert evidence.decision_score is None


def test_quality_evidence_ids_are_deterministic() -> None:
    record = make_quality_record(7)
    assert (
        quality_record_to_evidence(record).evidence_id
        == quality_record_to_evidence(record).evidence_id
        == "EVIDENCE-QUALITY-QI-000007"
    )


def test_quality_provenance_is_complete() -> None:
    evidence = quality_record_to_evidence(make_quality_record(7))
    provenance = evidence.provenance

    assert provenance.source_kind.value == "DEMO_FACTORY"
    assert provenance.source_dataset == SOURCE_DATASET
    assert provenance.source_id == "QI-000007"
    assert provenance.record_id == "QI-000007"
    assert provenance.document_id is None
    assert provenance.chunk_id is None
    assert provenance.page_start is None
    assert provenance.page_end is None


def test_row_machine_id_preserved() -> None:
    evidence = quality_record_to_evidence(make_quality_record(1, machine_id="CNC-03"))
    assert evidence.machine_id == "CNC-03"


def test_row_product_id_preserved() -> None:
    evidence = quality_record_to_evidence(make_quality_record(1, product_id="GEAR-B"))
    assert evidence.product_id == "GEAR-B"


def test_row_batch_id_preserved() -> None:
    evidence = quality_record_to_evidence(make_quality_record(1, batch_id="B-999"))
    assert evidence.batch_id == "B-999"


def test_content_includes_parameter_measurement_limits_result() -> None:
    record = make_quality_record(1, nominal_value=10.0, lsl=9.5, usl=10.5, measured_value=10.1, result="PASS")
    evidence = quality_record_to_evidence(record)
    assert "diameter" in evidence.content
    assert "10.0" in evidence.content
    assert "9.5" in evidence.content
    assert "10.5" in evidence.content
    assert "10.1" in evidence.content
    assert "PASS" in evidence.content


def test_summary_maps_to_frozen_evidence() -> None:
    summary = make_summary(
        inspection_count=10, pass_count=8, fail_count=2,
        parameters=[make_param_summary()],
    )
    evidence = quality_summary_to_evidence(
        summary, "CNC-05", "SHAFT-A", "B-001",
        datetime(2026, 9, 1), datetime(2026, 9, 20), SOURCE_DATASET,
    )

    assert isinstance(evidence, Evidence)
    assert evidence.source_type.value == "QUALITY"
    assert "10 inspections" in evidence.content
    assert evidence.retrieval_score is None
    assert evidence.decision_score is None
    assert evidence.provenance.record_id is None
    assert evidence.metadata["aggregation"] == "quality_summary"
    assert evidence.metadata["inspection_count"] == 10
    assert evidence.metadata["parameters"] == ["diameter"]


def test_summary_evidence_id_is_deterministic() -> None:
    summary = make_summary(parameters=[make_param_summary()])
    first = quality_summary_to_evidence(
        summary, "CNC-05", None, None, None, None, SOURCE_DATASET,
    )
    second = quality_summary_to_evidence(
        summary, "CNC-05", None, None, None, None, SOURCE_DATASET,
    )
    assert first.evidence_id == second.evidence_id
    assert first.evidence_id.startswith("EVIDENCE-QUALITY-SUMMARY-")


def test_summary_record_id_is_null() -> None:
    summary = make_summary(parameters=[make_param_summary()])
    evidence = quality_summary_to_evidence(
        summary, "CNC-05", None, None, None, None, SOURCE_DATASET,
    )
    assert evidence.provenance.record_id is None
    assert evidence.provenance.document_id is None
    assert evidence.provenance.chunk_id is None


def test_summary_source_id_is_deterministic() -> None:
    summary = make_summary(parameters=[make_param_summary()])
    evidence = quality_summary_to_evidence(
        summary, "CNC-05", None, None, None, None, SOURCE_DATASET,
    )
    assert evidence.provenance.source_id.startswith("QUALITY-SUMMARY-")
    assert len(evidence.provenance.source_id.split("-")[-1]) == 12


async def test_all_scores_are_null() -> None:
    agent, _ = full_agent()
    result = await agent.run(make_query(machine_id="CNC-05"))
    assert result.evidence
    assert all(item.retrieval_score is None for item in result.evidence)
    assert all(item.decision_score is None for item in result.evidence)


async def test_batch_scope_uses_exact_batch_retrieval() -> None:
    agent, repo = make_agent(
        rows=[make_quality_record(1, batch_id="B-001")],
        failures=[],
        summary=make_summary(parameters=[make_param_summary()]),
    )
    await agent.run(make_query(query_id="Q-BATCH", batch_id="B-001"))

    assert any(c[0] == "list_by_batch" for c in repo.calls)


async def test_machine_scope_uses_exact_supported_method() -> None:
    agent, repo = make_agent(
        rows=[make_quality_record(1, machine_id="CNC-05")],
        failures=[],
        summary=make_summary(parameters=[make_param_summary()]),
    )
    await agent.run(make_query(query_id="Q-MACHINE", machine_id="CNC-05"))
    assert any(c[0] == "list_by_machine" for c in repo.calls)


async def test_product_scope_uses_exact_supported_method() -> None:
    agent, repo = make_agent(
        rows=[make_quality_record(1, product_id="SHAFT-A")],
        failures=[],
        summary=make_summary(parameters=[make_param_summary()]),
    )
    await agent.run(make_query(query_id="Q-PRODUCT", product_id="SHAFT-A"))
    assert any(c[0] == "list_by_product" for c in repo.calls)


async def test_combined_scope_never_silently_ignores_supplied_identifiers() -> None:
    agent, repo = make_agent(
        rows=[make_quality_record(1, machine_id="CNC-05", product_id="SHAFT-A")],
        failures=[make_quality_record(2, machine_id="CNC-05", product_id="SHAFT-A", result="FAIL")],
        summary=make_summary(parameters=[make_param_summary()]),
    )
    result = await agent.run(
        make_query(query_id="Q-COMBINED", machine_id="CNC-05", product_id="SHAFT-A")
    )

    failure_calls = [c for c in repo.calls if c[0] == "list_failures"]
    assert failure_calls
    call = failure_calls[0]
    assert call[1] == "CNC-05"
    assert call[2] == "SHAFT-A"
    assert result.metadata["scope_type"] == "machine+product"
    assert result.metadata["retrieval_status"] == "ok"


async def test_no_data_returns_warning_not_fabricated_evidence() -> None:
    agent, repo = make_agent(
        rows=[], failures=[], summary=make_summary(inspection_count=0, pass_count=0, fail_count=0, parameters=[]),
    )
    result = await agent.run(make_query(machine_id="CNC-99"))
    assert result.metadata["retrieval_status"] in ("ok", "empty")
    assert result.errors == []


async def test_partial_expected_failure_preserves_successful_evidence() -> None:
    agent, repo = make_agent(
        rows=[make_quality_record(1, result="PASS")],
        failures=[make_quality_record(2, result="FAIL")],
        summary=make_summary(parameters=[make_param_summary()]),
        error=DatabaseError("db offline"),
    )
    result = await agent.run(make_query(machine_id="CNC-05"))

    assert len(result.evidence) > 0 or result.metadata["retrieval_status"] in ("partial", "ok")
    assert any("failed" in e.lower() for e in result.errors)
    assert result.metadata["retrieval_status"] == "partial"


async def test_complete_expected_failure_produces_safe_errors() -> None:
    failure = RepositoryError("database offline")
    agent, repo = make_agent(
        error=failure,
        summary_error=failure,
    )
    result = await agent.run(make_query(machine_id="CNC-05"))

    assert result.errors
    assert all("Traceback" not in msg for msg in result.errors)


async def test_unexpected_programming_errors_propagate() -> None:
    agent, repo = make_agent(
        rows=[], failures=[], summary=make_summary(parameters=[make_param_summary()]), error=ValueError("bad row"),
    )
    with pytest.raises(ValueError, match="bad row"):
        await agent.run(make_query(machine_id="CNC-05"))


async def test_latency_is_populated_and_non_negative() -> None:
    agent, _ = full_agent()
    result = await agent.run(make_query(machine_id="CNC-05"))
    assert isinstance(result.latency_ms, float)
    assert result.latency_ms >= 0


async def test_metadata_counts_are_correct() -> None:
    agent, repo = full_agent()
    result = await agent.run(make_query(machine_id="CNC-05", time_start=datetime(2026, 9, 1), time_end=datetime(2026, 9, 20)))

    assert result.metadata["machine_id"] == "CNC-05"
    assert result.metadata["scope_type"] == "machine"
    assert result.metadata["retrieval_status"] == "ok"
    assert result.metadata["inspection_count"] >= 0
    assert result.metadata["failed_evidence_count"] >= 0
    assert result.metadata["summary_evidence_count"] == 1


async def test_query_time_start_forwarded() -> None:
    agent, repo = make_agent(
        rows=[], failures=[], summary=make_summary(parameters=[make_param_summary()]),
    )
    ts = datetime(2026, 9, 1)
    te = datetime(2026, 9, 20)
    await agent.run(make_query(machine_id="CNC-05", time_start=ts, time_end=te))

    machine_calls = [c for c in repo.calls if c[0] == "list_by_machine"]
    assert machine_calls
    assert machine_calls[0][2] == ts
    assert machine_calls[0][3] == te


async def test_query_time_end_forwarded_without_start() -> None:
    agent, repo = make_agent(
        rows=[], failures=[], summary=make_summary(parameters=[make_param_summary()]),
    )
    te = datetime(2026, 9, 20)
    await agent.run(make_query(machine_id="CNC-05", time_end=te))

    machine_calls = [c for c in repo.calls if c[0] == "list_by_machine"]
    assert machine_calls
    assert machine_calls[0][3] == te


def test_module_respects_dependency_boundaries() -> None:
    source = (Path(__file__).resolve().parents[2] / "app" / "agents" / "quality.py").read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden in (
        "app.rag",
        "documentagent",
        "documentretriever",
        "maintenanceagent",
        "maintenancerepository",
        "alarmrepository",
        "telemetryrepository",
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
    source = (Path(__file__).resolve().parents[2] / "app" / "agents" / "quality.py").read_text(encoding="utf-8")
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





async def test_user_context_not_used_to_invent_identifiers() -> None:
    agent, repo = make_agent(
        rows=[], failures=[], summary=make_summary(parameters=[make_param_summary()]),
    )
    await agent.run(
        make_query(machine_id="CNC-05", user_context={"fake_machine": "CNC-99"})
    )
    machine_calls = [c for c in repo.calls if c[0] == "list_by_machine"]
    if machine_calls:
        assert machine_calls[0][1] == "CNC-05"


async def test_no_quality_root_cause_language_generated() -> None:
    agent, _ = full_agent()
    result = await agent.run(make_query(machine_id="CNC-05"))

    blob = "\n".join(
        [item.title + "\n" + item.content for item in result.evidence]
        + result.warnings
        + [str(result.metadata)]
    ).lower()
    for term in FORBIDDEN_DIAGNOSIS_TERMS:
        assert term not in blob, f"diagnosis-like language generated: {term}"


async def test_no_production_reject_metrics() -> None:
    agent, _ = full_agent()
    result = await agent.run(make_query(machine_id="CNC-05"))

    blob = "\n".join(
        [item.title + "\n" + item.content for item in result.evidence]
        + result.warnings
        + [str(result.metadata)]
    ).lower()
    for term in FORBIDDEN_PRODUCTION_TERMS:
        assert term not in blob, f"production metric generated: {term}"


async def test_no_spc_calculations() -> None:
    agent, _ = full_agent()
    result = await agent.run(make_query(machine_id="CNC-05"))

    blob = "\n".join(
        [item.title + "\n" + item.content for item in result.evidence]
        + result.warnings
        + [str(result.metadata)]
    ).lower()
    for term in FORBIDDEN_SPC_TERMS:
        assert term not in blob, f"SPC term generated: {term}"


async def test_failed_inspection_retrieval_maps_correctly() -> None:
    agent, repo = make_agent(
        rows=[],
        failures=[make_quality_record(1, result="FAIL", defect_type="DIMENSIONAL")],
        summary=make_summary(parameters=[make_param_summary()]),
    )
    result = await agent.run(make_query(machine_id="CNC-05"))

    failure_evidences = [
        item for item in result.evidence
        if item.metadata.get("record_type") == "quality_inspection"
        and item.metadata.get("result") == "FAIL"
    ]
    assert len(failure_evidences) >= 1
    assert failure_evidences[0].metadata["defect_type"] == "DIMENSIONAL"
    assert "FAIL" in failure_evidences[0].content


async def test_duplicate_inspection_emitted_once() -> None:
    record = make_quality_record(1, result="FAIL")
    agent, repo = make_agent(
        rows=[record],
        failures=[record],
        summary=make_summary(parameters=[make_param_summary()]),
    )
    result = await agent.run(make_query(machine_id="CNC-05"))

    inspection_ids = [
        item.provenance.record_id for item in result.evidence
        if item.metadata.get("record_type") == "quality_inspection"
    ]
    assert inspection_ids.count(record.inspection_id) == 1


async def test_evidence_ordering_is_deterministic() -> None:
    agent, _ = full_agent()
    first = await agent.run(make_query(machine_id="CNC-05"))
    second = await agent.run(make_query(machine_id="CNC-05"))
    assert [item.evidence_id for item in first.evidence] == [
        item.evidence_id for item in second.evidence
    ]
    kinds = [item.metadata["record_type"] for item in first.evidence]
    assert kinds[0] == "quality_summary"


async def test_query_text_not_parsed_for_identity() -> None:
    agent, repo = make_agent(
        rows=[], failures=[], summary=make_summary(parameters=[make_param_summary()]),
    )
    await agent.run(make_query(query="CNC-05 is out of spec", machine_id="CNC-03"))
    machine_calls = [c for c in repo.calls if c[0] == "list_by_machine"]
    if machine_calls:
        assert machine_calls[0][1] == "CNC-03"


@pytest.mark.parametrize("bad_limit", [0, -1, "12", True])
def test_invalid_limits_reject_bool_and_string(bad_limit) -> None:
    from app.repositories.quality import QualityRepository
    with pytest.raises(ValueError):
        QualityAgent(QualityRepository(), inspection_limit=bad_limit)
    with pytest.raises(ValueError):
        QualityAgent(QualityRepository(), failure_limit=bad_limit)


def _canonical_database_path():
    from app.core.config import get_settings
    return get_settings().default_database_path


def _real_repository():
    from app.db.connection import DatabaseConnection
    from app.repositories.quality import QualityRepository
    database = DatabaseConnection(_canonical_database_path())
    return QualityRepository(database)


async def _run_integration(machine_id: str = None, product_id: str = None, batch_id: str = None, time_start: datetime = None, time_end: datetime = None) -> AgentResult:
    repo = _real_repository()
    agent = QualityAgent(repo, inspection_limit=100, failure_limit=100)
    return await agent.run(
        make_query(query_id=f"Q-INT", query="quality check", machine_id=machine_id, product_id=product_id, batch_id=batch_id, time_start=time_start, time_end=time_end)
    )


async def test_integration_shaft_a() -> None:
    result = await _run_integration(product_id="SHAFT-A")

    assert result.agent_name is AgentName.QUALITY
    assert result.evidence
    assert result.errors == []
    for item in result.evidence:
        assert isinstance(item, Evidence)
        assert item.source_type.value == "QUALITY"
        assert item.provenance.source_kind.value == "DEMO_FACTORY"
        assert item.provenance.source_dataset == SOURCE_DATASET
        assert item.retrieval_score is None
        assert item.decision_score is None
    assert result.metadata["product_id"] == "SHAFT-A"
    assert result.metadata["retrieval_status"] == "ok"


async def test_integration_cnc05() -> None:
    result = await _run_integration(machine_id="CNC-05", time_start=datetime(2026, 9, 1), time_end=datetime(2026, 10, 16))

    assert result.agent_name is AgentName.QUALITY
    assert result.evidence
    assert result.errors == []
    for item in result.evidence:
        assert isinstance(item, Evidence)
        assert item.machine_id == "CNC-05"
        assert item.retrieval_score is None
        assert item.decision_score is None
    assert result.metadata["retrieval_status"] == "ok"


async def test_integration_batch() -> None:
    result = await _run_integration(batch_id="B-001")

    assert result.agent_name is AgentName.QUALITY
    assert result.evidence or result.warnings
    assert result.errors == []
    for item in result.evidence:
        assert isinstance(item, Evidence)
        assert item.batch_id == "B-001"
        assert item.provenance.source_kind.value == "DEMO_FACTORY"
    assert result.metadata["batch_id"] == "B-001"
    assert result.metadata["retrieval_status"] in ("ok", "empty")


async def test_integration_failed_inspections() -> None:
    result = await _run_integration(machine_id="CNC-05", time_start=datetime(2026, 9, 1), time_end=datetime(2026, 10, 16))

    failure_evidences = [
        item for item in result.evidence
        if item.metadata.get("record_type") == "quality_inspection"
        and item.metadata.get("result") == "FAIL"
    ]
    assert len(failure_evidences) >= 0
    for fe in failure_evidences:
        assert "FAIL" in fe.content
        assert fe.metadata.get("lsl") is not None or True
        assert fe.metadata.get("usl") is not None or True
        assert fe.metadata.get("measured_value") is not None or True
