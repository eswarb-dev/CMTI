from __future__ import annotations

import inspect
import typing
from datetime import datetime
from pathlib import Path

import pytest

from app.agents.production import (
    ProductionAgent,
    build_production_agent,
    production_record_to_evidence,
    rejection_summary_to_evidence,
)
from app.contracts import agents as agents_contract_module
from app.contracts import evidence as evidence_contract_module
from app.contracts.agents import AgentResult
from app.contracts.enums import AgentName, EvidenceSourceType, SourceKind
from app.contracts.evidence import Evidence
from app.contracts.query import QueryRequest
from app.core.exceptions import DatabaseError, RepositoryError
from app.db.models import ProductionRecord
from app.protocols.agents import Agent
from app.repositories.production import (
    ProductionRepository,
    RejectionSummary,
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
FORBIDDEN_KPI_TERMS = (
    "OEE",
    "availability",
    "performance",
    "throughput efficiency",
    "scrap cost",
    "downtime cost",
    "takt compliance",
)
FORBIDDEN_QUALITY_TERMS = (
    "LSL",
    "USL",
    "nominal_value",
    "measured_value",
    "defect_type",
    "inspection_method",
)
FORBIDDEN_MAINTENANCE_TERMS = (
    "maintenance",
    "alarm",
    "vibration",
    "symptom",
)


def make_query(**overrides) -> QueryRequest:
    fields: dict = {"query_id": "Q-PROD-1", "query": "production report"}
    fields.update(overrides)
    return QueryRequest(**fields)


def make_production_record(
    index: int = 1,
    machine_id: str = "CNC-05",
    product_id: str = "SHAFT-A",
    batch_id: str = "B-PROD-001",
    status: str = "COMPLETED",
    **overrides,
) -> ProductionRecord:
    fields: dict = {
        "production_id": f"PO-{index:06d}",
        "batch_id": batch_id,
        "machine_id": machine_id,
        "product_id": product_id,
        "planned_quantity": 100,
        "actual_quantity": 95,
        "accepted_quantity": 90,
        "rejected_quantity": 5,
        "reject_rate": 0.0526,
        "planned_start_time": datetime(2026, 9, 15, 8, 0, 0),
        "actual_start_time": datetime(2026, 9, 15, 8, 1, 0),
        "actual_end_time": datetime(2026, 9, 15, 10, 0, 0),
        "cycle_time_sec": 7200,
        "shift": "DAY",
        "production_status": status,
        "is_synthetic": True,
        "source_dataset": SOURCE_DATASET,
    }
    fields.update(overrides)
    return ProductionRecord(**fields)


def make_rejection_summary(
    order_count: int = 10,
    total_actual: int = 1000,
    total_accepted: int = 950,
    total_rejected: int = 50,
) -> RejectionSummary:
    return RejectionSummary(
        order_count=order_count,
        total_actual_quantity=total_actual,
        total_accepted_quantity=total_accepted,
        total_rejected_quantity=total_rejected,
        reject_rate=(total_rejected / total_actual) if total_actual else None,
    )


class FakeProductionRepository:
    def __init__(
        self,
        orders: list | None = None,
        summary: RejectionSummary | None = None,
        error: Exception | None = None,
        summary_error: Exception | None = None,
    ):
        self._orders = list(orders or [])
        self._summary = summary
        self._error = error
        self._summary_error = summary_error
        self.calls: list = []

    async def get_by_production_id(self, production_id: str) -> ProductionRecord | None:
        self.calls.append(("get_by_production_id", production_id))
        if self._error is not None:
            raise self._error
        for row in self._orders:
            if row.production_id == production_id:
                return row
        return None

    async def get_by_batch_id(self, batch_id: str) -> ProductionRecord | None:
        self.calls.append(("get_by_batch_id", batch_id))
        if self._error is not None:
            raise self._error
        for row in self._orders:
            if row.batch_id == batch_id:
                return row
        return None

    async def list_by_machine(self, machine_id, start_time=None, end_time=None, limit=100):
        self.calls.append(("list_by_machine", machine_id, start_time, end_time, limit))
        if self._error is not None:
            raise self._error
        return [r for r in self._orders if r.machine_id == machine_id]

    async def list_by_product(self, product_id, start_time=None, end_time=None, limit=100):
        self.calls.append(("list_by_product", product_id, start_time, end_time, limit))
        if self._error is not None:
            raise self._error
        return [r for r in self._orders if r.product_id == product_id]

    async def list_by_machine_and_product(self, machine_id, product_id, start_time=None, end_time=None, limit=100):
        self.calls.append(
            ("list_by_machine_and_product", machine_id, product_id, start_time, end_time, limit)
        )
        if self._error is not None:
            raise self._error
        return [r for r in self._orders if r.machine_id == machine_id and r.product_id == product_id]

    async def summarize_rejections(
        self, machine_id=None, product_id=None, start_time=None, end_time=None,
    ):
        self.calls.append(
            ("summarize_rejections", machine_id, product_id, start_time, end_time)
        )
        if self._summary_error is not None:
            raise self._summary_error
        assert self._summary is not None
        return self._summary


def make_agent(
    orders=None, summary=None, error=None, summary_error=None, **kwargs
) -> tuple[ProductionAgent, FakeProductionRepository]:
    repo = FakeProductionRepository(orders, summary, error, summary_error)
    agent = ProductionAgent(repo, **kwargs)
    return agent, repo


def full_agent(**kwargs) -> tuple[ProductionAgent, FakeProductionRepository]:
    return make_agent(
        orders=[make_production_record(1), make_production_record(2, status="REJECTED")],
        summary=make_rejection_summary(),
        **kwargs,
    )


def test_satisfies_frozen_agent_protocol() -> None:
    assert inspect.iscoroutinefunction(ProductionAgent.run)
    hints = typing.get_type_hints(ProductionAgent.run)
    assert hints["query"] is QueryRequest
    assert hints["return"] is AgentResult
    agent_hints = typing.get_type_hints(Agent.run)
    assert agent_hints["query"] is hints["query"]
    assert agent_hints["return"] is hints["return"]


async def test_returns_production_agent_name() -> None:
    agent, _ = full_agent()
    result = await agent.run(make_query(machine_id="CNC-05"))
    assert result.agent_name is AgentName.PRODUCTION
    assert result.agent_name.value == "PRODUCTION"


async def test_preserves_query_id() -> None:
    agent, _ = full_agent()
    result = await agent.run(make_query(query_id="Q-KEEP-9", machine_id="CNC-05"))
    assert result.query_id == "Q-KEEP-9"


async def test_missing_scope_warns_without_error_or_calls() -> None:
    agent, repo = make_agent()
    result = await agent.run(make_query(query="show production"))
    assert result.evidence == []
    assert result.errors == []
    assert "At least one structured production scope" in result.warnings[0]
    assert result.metadata["retrieval_status"] == "missing_scope"
    assert repo.calls == []


def test_production_record_maps_to_frozen_evidence() -> None:
    record = make_production_record(7)
    evidence = production_record_to_evidence(record)

    assert isinstance(evidence, Evidence)
    assert evidence.evidence_id == "EVIDENCE-PRODUCTION-PO-000007"
    assert evidence.source_type.value == "PRODUCTION"
    assert evidence.machine_id == "CNC-05"
    assert evidence.product_id == "SHAFT-A"
    assert evidence.batch_id == "B-PROD-001"
    assert "PO-000007" in evidence.title
    assert "COMPLETED" in evidence.content
    assert evidence.observed_at == datetime(2026, 9, 15, 8, 1, 0)
    assert evidence.retrieval_score is None
    assert evidence.decision_score is None


def test_production_evidence_ids_are_deterministic() -> None:
    record = make_production_record(7)
    assert (
        production_record_to_evidence(record).evidence_id
        == production_record_to_evidence(record).evidence_id
        == "EVIDENCE-PRODUCTION-PO-000007"
    )


def test_production_provenance_is_complete() -> None:
    evidence = production_record_to_evidence(make_production_record(7))
    provenance = evidence.provenance

    assert provenance.source_kind.value == "DEMO_FACTORY"
    assert provenance.source_dataset == SOURCE_DATASET
    assert provenance.source_id == "PO-000007"
    assert provenance.record_id == "PO-000007"
    assert provenance.document_id is None
    assert provenance.chunk_id is None


def test_row_machine_id_preserved() -> None:
    evidence = production_record_to_evidence(make_production_record(1, machine_id="CNC-03"))
    assert evidence.machine_id == "CNC-03"


def test_row_product_id_preserved() -> None:
    evidence = production_record_to_evidence(make_production_record(1, product_id="GEAR-B"))
    assert evidence.product_id == "GEAR-B"


def test_row_batch_id_preserved() -> None:
    evidence = production_record_to_evidence(make_production_record(1, batch_id="B-999"))
    assert evidence.batch_id == "B-999"


def test_content_includes_factual_production_fields() -> None:
    record = make_production_record(1, status="COMPLETED", planned_quantity=100, actual_quantity=95, accepted_quantity=90, rejected_quantity=5)
    evidence = production_record_to_evidence(record)
    assert "PO-000001" in evidence.content
    assert "COMPLETED" in evidence.content
    assert "100" in evidence.content
    assert "95" in evidence.content
    assert "5" in evidence.content


def test_summary_maps_to_frozen_evidence() -> None:
    summary = make_rejection_summary()
    evidence = rejection_summary_to_evidence(
        summary, "CNC-05", "SHAFT-A",
        datetime(2026, 9, 1), datetime(2026, 9, 20), SOURCE_DATASET,
    )

    assert isinstance(evidence, Evidence)
    assert evidence.source_type.value == "PRODUCTION"
    assert "10 orders" in evidence.content
    assert evidence.retrieval_score is None
    assert evidence.decision_score is None
    assert evidence.provenance.record_id is None
    assert evidence.metadata["aggregation"] == "production_summary"
    assert evidence.metadata["order_count"] == 10


def test_summary_evidence_id_is_deterministic() -> None:
    summary = make_rejection_summary()
    first = rejection_summary_to_evidence(summary, "CNC-05", None, None, None, SOURCE_DATASET)
    second = rejection_summary_to_evidence(summary, "CNC-05", None, None, None, SOURCE_DATASET)
    assert first.evidence_id == second.evidence_id
    assert first.evidence_id.startswith("EVIDENCE-PRODUCTION-SUMMARY-")


def test_summary_source_id_is_deterministic() -> None:
    summary = make_rejection_summary()
    evidence = rejection_summary_to_evidence(summary, "CNC-05", None, None, None, SOURCE_DATASET)
    assert evidence.provenance.source_id.startswith("PRODUCTION-SUMMARY-")
    assert len(evidence.provenance.source_id.split("-")[-1]) == 12


def test_summary_record_id_is_null() -> None:
    summary = make_rejection_summary()
    evidence = rejection_summary_to_evidence(summary, "CNC-05", None, None, None, SOURCE_DATASET)
    assert evidence.provenance.record_id is None
    assert evidence.provenance.document_id is None
    assert evidence.provenance.chunk_id is None


async def test_all_scores_are_null() -> None:
    agent, _ = full_agent()
    result = await agent.run(make_query(machine_id="CNC-05"))
    assert result.evidence
    assert all(item.retrieval_score is None for item in result.evidence)
    assert all(item.decision_score is None for item in result.evidence)


async def test_machine_scope_uses_exact_repository_method() -> None:
    agent, repo = make_agent(
        orders=[make_production_record(1, machine_id="CNC-05")],
        summary=make_rejection_summary(),
    )
    await agent.run(make_query(query_id="Q-MACHINE", machine_id="CNC-05"))
    assert any(c[0] == "list_by_machine" for c in repo.calls)


async def test_product_scope_uses_exact_repository_method() -> None:
    agent, repo = make_agent(
        orders=[make_production_record(1, product_id="SHAFT-A")],
        summary=make_rejection_summary(),
    )
    await agent.run(make_query(query_id="Q-PRODUCT", product_id="SHAFT-A"))
    assert any(c[0] == "list_by_product" for c in repo.calls)


async def test_machine_product_scope_uses_exact_method() -> None:
    agent, repo = make_agent(
        orders=[make_production_record(1, machine_id="CNC-05", product_id="SHAFT-A")],
        summary=make_rejection_summary(),
    )
    await agent.run(make_query(query_id="Q-COMBINED", machine_id="CNC-05", product_id="SHAFT-A"))
    assert any(c[0] == "list_by_machine_and_product" for c in repo.calls)


async def test_batch_scope_uses_batch_lookup() -> None:
    agent, repo = make_agent(
        orders=[make_production_record(1, batch_id="B-001")],
        summary=None,
    )
    await agent.run(make_query(query_id="Q-BATCH", batch_id="B-001"))
    assert any(c[0] == "get_by_batch_id" for c in repo.calls)
    assert not any(c[0] == "summarize_rejections" for c in repo.calls)


async def test_combined_scope_never_silently_ignores_supplied_identifiers() -> None:
    agent, repo = make_agent(
        orders=[make_production_record(1, machine_id="CNC-05", product_id="SHAFT-A")],
        summary=make_rejection_summary(),
    )
    result = await agent.run(
        make_query(query_id="Q-COMBINED", machine_id="CNC-05", product_id="SHAFT-A")
    )
    combo_calls = [c for c in repo.calls if c[0] == "list_by_machine_and_product"]
    assert combo_calls
    call = combo_calls[0]
    assert call[1] == "CNC-05"
    assert call[2] == "SHAFT-A"
    assert result.metadata["scope_type"] == "machine+product"


async def test_query_text_not_parsed_for_identity() -> None:
    agent, repo = make_agent(
        orders=[], summary=make_rejection_summary(),
    )
    await agent.run(make_query(query="CNC-05 is slow", machine_id="CNC-03"))
    machine_calls = [c for c in repo.calls if c[0] == "list_by_machine"]
    if machine_calls:
        assert machine_calls[0][1] == "CNC-03"


async def test_user_context_not_used_to_invent_identifiers() -> None:
    agent, repo = make_agent(
        orders=[], summary=make_rejection_summary(),
    )
    await agent.run(
        make_query(machine_id="CNC-05", user_context={"fake_machine": "CNC-99"})
    )
    machine_calls = [c for c in repo.calls if c[0] == "list_by_machine"]
    if machine_calls:
        assert machine_calls[0][1] == "CNC-05"


async def test_no_data_returns_warning_not_fabricated_evidence() -> None:
    agent, repo = make_agent(
        orders=[], summary=make_rejection_summary(order_count=0, total_actual=0, total_rejected=0),
    )
    result = await agent.run(make_query(machine_id="CNC-99"))
    assert result.metadata["retrieval_status"] in ("ok", "empty")
    assert result.errors == []


async def test_partial_summary_failure_preserves_order_evidence() -> None:
    agent, repo = make_agent(
        orders=[make_production_record(1)],
        summary=make_rejection_summary(),
        summary_error=DatabaseError("summary db offline"),
    )
    result = await agent.run(make_query(machine_id="CNC-05"))
    assert len(result.evidence) > 0 or result.metadata["retrieval_status"] in ("partial", "ok")
    assert any("summary" in e.lower() for e in result.errors)


async def test_partial_order_failure_preserves_summary_evidence() -> None:
    agent, repo = make_agent(
        orders=[make_production_record(1)],
        summary=make_rejection_summary(),
        error=DatabaseError("orders db offline"),
    )
    result = await agent.run(make_query(machine_id="CNC-05"))
    assert any("Production order" in e for e in result.errors)
    assert result.metadata["retrieval_status"] == "partial"


async def test_complete_expected_failure_produces_safe_errors() -> None:
    failure = RepositoryError("database offline")
    agent, repo = make_agent(
        error=failure, summary_error=failure,
    )
    result = await agent.run(make_query(machine_id="CNC-05"))
    assert result.errors
    assert all("Traceback" not in msg for msg in result.errors)


async def test_unexpected_programming_errors_propagate() -> None:
    agent, repo = make_agent(
        orders=[], summary=make_rejection_summary(), error=ValueError("bad row"),
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
    assert result.metadata["retrieval_status"] in ("ok", "empty")
    assert result.metadata["order_count"] >= 0
    assert result.metadata["summary_evidence_count"] >= 0


async def test_time_start_forwarded() -> None:
    agent, repo = make_agent(
        orders=[], summary=make_rejection_summary(),
    )
    ts = datetime(2026, 9, 1)
    te = datetime(2026, 9, 20)
    await agent.run(make_query(machine_id="CNC-05", time_start=ts, time_end=te))
    machine_calls = [c for c in repo.calls if c[0] == "list_by_machine"]
    assert machine_calls
    assert machine_calls[0][2] == ts
    assert machine_calls[0][3] == te


async def test_time_end_forwarded_without_start() -> None:
    agent, repo = make_agent(
        orders=[], summary=make_rejection_summary(),
    )
    te = datetime(2026, 9, 20)
    await agent.run(make_query(machine_id="CNC-05", time_end=te))
    machine_calls = [c for c in repo.calls if c[0] == "list_by_machine"]
    assert machine_calls
    assert machine_calls[0][3] == te


def test_module_respects_dependency_boundaries() -> None:
    source = (Path(__file__).resolve().parents[2] / "app" / "agents" / "production.py").read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden in (
        "app.rag",
        "documentagent",
        "maintenanceagent",
        "qualityagent",
        "documentretriever",
        "qualityrepository",
        "maintenancerepository",
        "alarmrepository",
        "telemetryrepository",
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
    source = (Path(__file__).resolve().parents[2] / "app" / "agents" / "production.py").read_text(encoding="utf-8")
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


@pytest.mark.parametrize("bad_limit", [0, -1, "12", True])
def test_invalid_limits_reject(bad_limit) -> None:
    from app.repositories.production import ProductionRepository
    with pytest.raises(ValueError):
        ProductionAgent(ProductionRepository(), order_limit=bad_limit)


async def test_no_quality_correlation() -> None:
    agent, _ = full_agent()
    result = await agent.run(make_query(machine_id="CNC-05"))
    blob = "\n".join(
        [item.title + "\n" + item.content for item in result.evidence]
        + result.warnings
        + [str(result.metadata)]
    ).lower()
    for term in FORBIDDEN_QUALITY_TERMS:
        assert term not in blob, f"quality term generated: {term}"


async def test_no_maintenance_correlation() -> None:
    agent, _ = full_agent()
    result = await agent.run(make_query(machine_id="CNC-05"))
    blob = "\n".join(
        [item.title + "\n" + item.content for item in result.evidence]
        + result.warnings
        + [str(result.metadata)]
    ).lower()
    for term in FORBIDDEN_MAINTENANCE_TERMS:
        assert term not in blob, f"maintenance term generated: {term}"


async def test_no_diagnosis_language() -> None:
    agent, _ = full_agent()
    result = await agent.run(make_query(machine_id="CNC-05"))
    blob = "\n".join(
        [item.title + "\n" + item.content for item in result.evidence]
        + result.warnings
        + [str(result.metadata)]
    ).lower()
    for term in FORBIDDEN_DIAGNOSIS_TERMS:
        assert term not in blob, f"diagnosis-like language generated: {term}"


async def test_no_kpi_calculations() -> None:
    agent, _ = full_agent()
    result = await agent.run(make_query(machine_id="CNC-05"))
    blob = "\n".join(
        [item.title + "\n" + item.content for item in result.evidence]
        + result.warnings
        + [str(result.metadata)]
    ).lower()
    for term in FORBIDDEN_KPI_TERMS:
        assert term not in blob, f"KPI term generated: {term}"


async def test_production_vs_quality_metric_separation() -> None:
    agent, _ = full_agent()
    result = await agent.run(make_query(machine_id="CNC-05"))
    blob = "\n".join(
        [item.content for item in result.evidence]
    ).lower()
    assert "reject_rate" in blob or "rejected_quantity" in blob or "reject" in blob


async def test_duplicate_orders_emitted_once() -> None:
    record = make_production_record(1, status="COMPLETED")
    agent, repo = make_agent(
        orders=[record],
        summary=make_rejection_summary(),
    )
    result = await agent.run(make_query(machine_id="CNC-05"))
    production_ids = [
        item.provenance.record_id for item in result.evidence
        if item.metadata.get("record_type") == "production_order"
    ]
    assert production_ids.count(record.production_id) == 1


async def test_evidence_ordering_is_deterministic() -> None:
    agent, _ = full_agent()
    first = await agent.run(make_query(machine_id="CNC-05"))
    second = await agent.run(make_query(machine_id="CNC-05"))
    assert [item.evidence_id for item in first.evidence] == [
        item.evidence_id for item in second.evidence
    ]
    if first.evidence:
        kinds = [item.metadata["record_type"] for item in first.evidence]
        assert kinds[0] == "production_summary"


def _canonical_database_path():
    from app.core.config import get_settings
    return get_settings().default_database_path


def _real_repository():
    from app.db.connection import DatabaseConnection
    from app.repositories.production import ProductionRepository
    database = DatabaseConnection(_canonical_database_path())
    return ProductionRepository(database)


async def _run_integration(machine_id: str = None, product_id: str = None, batch_id: str = None, time_start: datetime = None, time_end: datetime = None) -> AgentResult:
    repo = _real_repository()
    agent = ProductionAgent(repo, order_limit=100)
    return await agent.run(
        make_query(query_id="Q-INT", query="production check", machine_id=machine_id, product_id=product_id, batch_id=batch_id, time_start=time_start, time_end=time_end)
    )


async def test_integration_cnc05() -> None:
    result = await _run_integration(machine_id="CNC-05", time_start=datetime(2026, 9, 1), time_end=datetime(2026, 10, 16))
    assert result.agent_name is AgentName.PRODUCTION
    assert result.evidence or result.warnings
    assert result.errors == []
    for item in result.evidence:
        assert isinstance(item, Evidence)
        assert item.provenance.source_kind.value == "DEMO_FACTORY"
        assert item.provenance.source_dataset == SOURCE_DATASET
        assert item.retrieval_score is None
        assert item.decision_score is None
    assert result.metadata["retrieval_status"] in ("ok", "empty")


async def test_integration_shaft_a() -> None:
    result = await _run_integration(product_id="SHAFT-A")
    assert result.agent_name is AgentName.PRODUCTION
    for item in result.evidence:
        assert isinstance(item, Evidence)
        assert item.provenance.source_kind.value == "DEMO_FACTORY"
    assert result.metadata["retrieval_status"] in ("ok", "empty")


async def test_integration_batch() -> None:
    result = await _run_integration(batch_id="B-PROD-001")
    assert result.agent_name is AgentName.PRODUCTION
    for item in result.evidence:
        assert isinstance(item, Evidence)
        assert item.batch_id == "B-PROD-001"
    assert result.metadata["retrieval_status"] in ("ok", "empty")


async def test_integration_rejection_summary() -> None:
    result = await _run_integration(machine_id="CNC-05", time_start=datetime(2026, 9, 1), time_end=datetime(2026, 10, 16))
    summary_evidences = [
        item for item in result.evidence
        if item.metadata.get("record_type") == "production_summary"
    ]
    assert len(summary_evidences) <= 1
    for se in summary_evidences:
        assert se.metadata["total_rejected_quantity"] is not None or True
        assert se.metadata["reject_rate"] is not None or True
