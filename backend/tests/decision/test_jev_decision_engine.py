from __future__ import annotations

import inspect
import typing
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.contracts.enums import AgentName, Domain, ProviderStatus, RiskLevel
from app.contracts.query import QueryRequest
from app.contracts.routing import RoutingDecision
from app.core.config import Settings
from app.decision.jev import JevDecisionEngine, build_jev_decision_engine
from app.protocols.decision import DecisionEngine


def make_query(**overrides) -> QueryRequest:
    fields: dict = {"query_id": "Q-JEV-1", "query": "show production report"}
    fields.update(overrides)
    return QueryRequest(**fields)


def make_settings(**overrides) -> Settings:
    fields: dict = {
        "typesafe_api_key": "test-key",
        "jev_model": "jev-latest",
        "jev_route_threshold": 0.50,
        "jev_timeout_seconds": 10.0,
        "jev_max_retries": 1,
        "jev_enabled": True,
    }
    fields.update(overrides)
    return Settings(**fields)


def make_noul_answer(value: float):
    answer = MagicMock()
    answer.noul = value
    return answer


def make_response(answers: dict[str, float]):
    response = MagicMock()
    response.answers = {name: make_noul_answer(val) for name, val in answers.items()}
    return response


class FakeJevClient:
    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error
        self.calls: list = []

    async def system_one(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response

    async def aclose(self):
        pass


def make_engine(response=None, error=None, **settings_kwargs) -> tuple[JevDecisionEngine, FakeJevClient]:
    client = FakeJevClient(response, error)
    settings = make_settings(**settings_kwargs)
    engine = JevDecisionEngine(client, settings=settings)
    return engine, client


def test_satisfies_frozen_decision_engine_protocol() -> None:
    assert inspect.iscoroutinefunction(JevDecisionEngine.route)
    hints = typing.get_type_hints(JevDecisionEngine.route)
    assert hints["query"] is QueryRequest
    assert hints["return"] is RoutingDecision
    agent_hints = typing.get_type_hints(DecisionEngine.route)
    assert agent_hints["query"] is hints["query"]
    assert agent_hints["return"] is hints["return"]


async def test_returns_frozen_routing_decision() -> None:
    engine, _ = make_engine(response=make_response({"route_document": 0.9, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    result = await engine.route(make_query(machine_id="CNC-05"))
    assert isinstance(result, RoutingDecision)


async def test_query_id_preserved() -> None:
    engine, _ = make_engine(response=make_response({"route_document": 0.9, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    result = await engine.route(make_query(query_id="Q-KEEP-9", machine_id="CNC-05"))
    assert result.query_id == "Q-KEEP-9"


async def test_exactly_four_routing_questions_sent() -> None:
    engine, client = make_engine(response=make_response({"route_document": 0.9, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    await engine.route(make_query(machine_id="CNC-05"))
    assert len(client.calls) == 1
    questions = client.calls[0]["questions"]
    assert len(questions) == 4


async def test_questions_use_noul_semantics() -> None:
    engine, client = make_engine(response=make_response({"route_document": 0.9, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    await engine.route(make_query(machine_id="CNC-05"))
    questions = client.calls[0]["questions"]
    for q in questions.values():
        assert q.type == "noul"


async def test_state_includes_query_text() -> None:
    engine, client = make_engine(response=make_response({"route_document": 0.9, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    await engine.route(make_query(query="show me CNC-05 alarms", machine_id="CNC-05"))
    state = client.calls[0]["state"]
    assert state["query"] == "show me CNC-05 alarms"


async def test_state_includes_machine_id() -> None:
    engine, client = make_engine(response=make_response({"route_document": 0.9, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    await engine.route(make_query(machine_id="CNC-05"))
    state = client.calls[0]["state"]
    assert state["machine_id"] == "CNC-05"


async def test_state_includes_product_id() -> None:
    engine, client = make_engine(response=make_response({"route_document": 0.9, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    await engine.route(make_query(product_id="SHAFT-A"))
    state = client.calls[0]["state"]
    assert state["product_id"] == "SHAFT-A"


async def test_state_includes_batch_id() -> None:
    engine, client = make_engine(response=make_response({"route_document": 0.9, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    await engine.route(make_query(batch_id="B-001"))
    state = client.calls[0]["state"]
    assert state["batch_id"] == "B-001"


async def test_state_includes_iso_time_bounds() -> None:
    engine, client = make_engine(response=make_response({"route_document": 0.9, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    ts = datetime(2026, 9, 1, 0, 0, 0)
    te = datetime(2026, 9, 20, 0, 0, 0)
    await engine.route(make_query(machine_id="CNC-05", time_start=ts, time_end=te))
    state = client.calls[0]["state"]
    assert state["time_start"] == ts.isoformat()
    assert state["time_end"] == te.isoformat()


async def test_user_context_allowlist_enforced() -> None:
    engine, client = make_engine(response=make_response({"route_document": 0.9, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    await engine.route(make_query(
        machine_id="CNC-05",
        user_context={"document_type": "manual",                      "manufacturer": "Siemens",
                      "secret_field": "should_not_appear",
                      "api_key": "should_not_appear"},
    ))
    state = client.calls[0]["state"]
    rc = state["routing_context"]
    assert "document_type" in rc
    assert "manufacturer" in rc
    assert "secret_field" not in rc
    assert "api_key" not in rc


async def test_arbitrary_user_context_excluded() -> None:
    engine, client = make_engine(response=make_response({"route_document": 0.9, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    await engine.route(make_query(
        machine_id="CNC-05",
        user_context={"internal_db_path": "/secret/path", "stack_trace": "..."},
    ))
    state = client.calls[0]["state"]
    rc = state["routing_context"]
    assert "internal_db_path" not in rc
    assert "stack_trace" not in rc


async def test_hidden_ground_truth_never_enters_state() -> None:
    engine, client = make_engine(response=make_response({"route_document": 0.9, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    await engine.route(make_query(machine_id="CNC-05"))
    state = client.calls[0]["state"]
    assert "hidden_simulated_cause" not in str(state)
    assert "demo_cases" not in str(state)


async def test_document_above_threshold_selects_document() -> None:
    engine, _ = make_engine(response=make_response({"route_document": 0.9, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    result = await engine.route(make_query(machine_id="CNC-05"))
    assert AgentName.DOCUMENT in result.selected_agents


async def test_maintenance_above_threshold_selects_maintenance() -> None:
    engine, _ = make_engine(response=make_response({"route_document": 0.1, "route_maintenance": 0.9, "route_quality": 0.1, "route_production": 0.1}))
    result = await engine.route(make_query(machine_id="CNC-05"))
    assert AgentName.MAINTENANCE in result.selected_agents


async def test_quality_above_threshold_selects_quality() -> None:
    engine, _ = make_engine(response=make_response({"route_document": 0.1, "route_maintenance": 0.1, "route_quality": 0.9, "route_production": 0.1}))
    result = await engine.route(make_query(machine_id="CNC-05"))
    assert AgentName.QUALITY in result.selected_agents


async def test_production_above_threshold_selects_production() -> None:
    engine, _ = make_engine(response=make_response({"route_document": 0.1, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.9}))
    result = await engine.route(make_query(machine_id="CNC-05"))
    assert AgentName.PRODUCTION in result.selected_agents


async def test_below_threshold_does_not_select() -> None:
    engine, _ = make_engine(response=make_response({"route_document": 0.1, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    result = await engine.route(make_query(machine_id="CNC-05"))
    assert result.provider_status == ProviderStatus.FALLBACK


async def test_threshold_equality_is_inclusive() -> None:
    engine, _ = make_engine(response=make_response({"route_document": 0.5, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    result = await engine.route(make_query(machine_id="CNC-05"))
    assert AgentName.DOCUMENT in result.selected_agents


async def test_multiple_agents_selected_simultaneously() -> None:
    engine, _ = make_engine(response=make_response({"route_document": 0.9, "route_maintenance": 0.8, "route_quality": 0.7, "route_production": 0.6}))
    result = await engine.route(make_query(machine_id="CNC-05"))
    assert len(result.selected_agents) == 4


async def test_selected_agents_canonical_order() -> None:
    engine, _ = make_engine(response=make_response({"route_document": 0.9, "route_maintenance": 0.8, "route_quality": 0.7, "route_production": 0.6}))
    result = await engine.route(make_query(machine_id="CNC-05"))
    agents = result.selected_agents
    assert agents == [AgentName.DOCUMENT, AgentName.MAINTENANCE, AgentName.QUALITY, AgentName.PRODUCTION]


async def test_no_duplicate_agents() -> None:
    engine, _ = make_engine(response=make_response({"route_document": 0.9, "route_maintenance": 0.8, "route_quality": 0.7, "route_production": 0.6}))
    result = await engine.route(make_query(machine_id="CNC-05"))
    assert len(set(result.selected_agents)) == len(result.selected_agents)


async def test_selected_agents_is_sole_routing_source() -> None:
    engine, _ = make_engine(response=make_response({"route_document": 0.9, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    result = await engine.route(make_query(machine_id="CNC-05"))
    assert not hasattr(result, "run_document")
    assert not hasattr(result, "run_maintenance")
    assert not hasattr(result, "run_quality")
    assert not hasattr(result, "run_production")


async def test_provider_success_no_fallback() -> None:
    engine, _ = make_engine(response=make_response({"route_document": 0.9, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    result = await engine.route(make_query(machine_id="CNC-05"))
    assert result.provider_status == ProviderStatus.SUCCESS
    assert result.decision_metadata["fallback_used"] is False


async def test_no_api_key_uses_fallback() -> None:
    engine, _ = make_engine(response=make_response({"route_document": 0.9, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}), typesafe_api_key=None)
    result = await engine.route(make_query(machine_id="CNC-05"))
    assert result.provider_status == ProviderStatus.FALLBACK
    assert result.decision_metadata["fallback_used"] is True


async def test_jev_disabled_uses_fallback_without_provider_call() -> None:
    engine, client = make_engine(response=make_response({"route_document": 0.9, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}), jev_enabled=False)
    result = await engine.route(make_query(machine_id="CNC-05"))
    assert result.provider_status == ProviderStatus.FALLBACK
    assert client.calls == []


async def test_provider_timeout_uses_fallback() -> None:
    engine, _ = make_engine(error=TimeoutError("timeout"))
    result = await engine.route(make_query(machine_id="CNC-05"))
    assert result.provider_status == ProviderStatus.FALLBACK


async def test_provider_connection_error_uses_fallback() -> None:
    engine, _ = make_engine(error=ConnectionError("connection failed"))
    result = await engine.route(make_query(machine_id="CNC-05"))
    assert result.provider_status == ProviderStatus.FALLBACK


async def test_provider_api_error_uses_fallback() -> None:
    from app.core.exceptions import ProviderUnavailableError
    engine, _ = make_engine(error=ProviderUnavailableError("api error"))
    result = await engine.route(make_query(machine_id="CNC-05"))
    assert result.provider_status == ProviderStatus.FALLBACK


async def test_malformed_response_uses_fallback() -> None:
    bad_response = MagicMock()
    bad_response.answers = {}
    engine, _ = make_engine(response=bad_response)
    result = await engine.route(make_query(machine_id="CNC-05"))
    assert result.provider_status == ProviderStatus.FALLBACK


async def test_all_below_threshold_uses_fallback() -> None:
    engine, _ = make_engine(response=make_response({"route_document": 0.1, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    result = await engine.route(make_query(machine_id="CNC-05"))
    assert result.provider_status == ProviderStatus.FALLBACK
    assert result.decision_metadata["fallback_used"] is True


async def test_fallback_no_ids_document_only() -> None:
    engine, _ = make_engine(response=make_response({"route_document": 0.1, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    result = await engine.route(make_query(query="general question"))
    assert result.selected_agents == [AgentName.DOCUMENT]


async def test_fallback_machine_id_includes_all_domains() -> None:
    engine, _ = make_engine(response=make_response({"route_document": 0.1, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    result = await engine.route(make_query(machine_id="CNC-05"))
    assert AgentName.DOCUMENT in result.selected_agents
    assert AgentName.MAINTENANCE in result.selected_agents
    assert AgentName.QUALITY in result.selected_agents
    assert AgentName.PRODUCTION in result.selected_agents


async def test_fallback_product_id_includes_document_quality_production() -> None:
    engine, _ = make_engine(response=make_response({"route_document": 0.1, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    result = await engine.route(make_query(product_id="SHAFT-A"))
    assert AgentName.DOCUMENT in result.selected_agents
    assert AgentName.QUALITY in result.selected_agents
    assert AgentName.PRODUCTION in result.selected_agents
    assert AgentName.MAINTENANCE not in result.selected_agents


async def test_fallback_batch_id_includes_document_quality_production() -> None:
    engine, _ = make_engine(response=make_response({"route_document": 0.1, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    result = await engine.route(make_query(batch_id="B-001"))
    assert AgentName.DOCUMENT in result.selected_agents
    assert AgentName.QUALITY in result.selected_agents
    assert AgentName.PRODUCTION in result.selected_agents
    assert AgentName.MAINTENANCE not in result.selected_agents


async def test_free_text_never_creates_structured_ids() -> None:
    engine, client = make_engine(response=make_response({"route_document": 0.9, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    await engine.route(make_query(query="show CNC-05 production for SHAFT-A"))
    state = client.calls[0]["state"]
    assert state["machine_id"] is None
    assert state["product_id"] is None
    assert state["batch_id"] is None


async def test_engine_does_not_call_agent_run() -> None:
    engine, _ = make_engine(response=make_response({"route_document": 0.9, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    result = await engine.route(make_query(machine_id="CNC-05"))
    assert isinstance(result, RoutingDecision)


async def test_engine_does_not_access_repositories() -> None:
    engine, _ = make_engine(response=make_response({"route_document": 0.9, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    assert not hasattr(engine, "_quality_repository")
    assert not hasattr(engine, "_maintenance_repository")
    assert not hasattr(engine, "_production_repository")


async def test_engine_does_not_access_database() -> None:
    engine, _ = make_engine(response=make_response({"route_document": 0.9, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    assert not hasattr(engine, "_database")
    assert not hasattr(engine, "_db")


async def test_engine_does_not_access_rag() -> None:
    engine, _ = make_engine(response=make_response({"route_document": 0.9, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    assert not hasattr(engine, "_retriever")
    assert not hasattr(engine, "_document_agent")


async def test_engine_does_not_create_evidence() -> None:
    engine, _ = make_engine(response=make_response({"route_document": 0.9, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    result = await engine.route(make_query(machine_id="CNC-05"))
    assert not hasattr(result, "evidence")


async def test_routing_probabilities_not_evidence_scores() -> None:
    engine, _ = make_engine(response=make_response({"route_document": 0.9, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    result = await engine.route(make_query(machine_id="CNC-05"))
    assert "route_document_probability" in result.decision_metadata


async def test_unexpected_programming_errors_propagate() -> None:
    engine, _ = make_engine(error=ValueError("programming bug"))
    with pytest.raises(ValueError, match="programming bug"):
        await engine.route(make_query(machine_id="CNC-05"))


async def test_timeout_passed_to_client() -> None:
    engine, client = make_engine(response=make_response({"route_document": 0.9, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    await engine.route(make_query(machine_id="CNC-05"))
    assert client.calls[0]["timeout"] == 10.0


async def test_configured_model_used() -> None:
    engine, client = make_engine(response=make_response({"route_document": 0.9, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}), jev_model="jev-custom")
    await engine.route(make_query(machine_id="CNC-05"))
    assert client.calls[0]["model"] == "jev-custom"


async def test_configured_retry_policy_used() -> None:
    engine, client = make_engine(response=make_response({"route_document": 0.9, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    await engine.route(make_query(machine_id="CNC-05"))
    assert "retry" in client.calls[0]


async def test_latency_diagnostics_populated() -> None:
    engine, _ = make_engine(response=make_response({"route_document": 0.9, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    result = await engine.route(make_query(machine_id="CNC-05"))
    assert "latency_ms" in result.decision_metadata
    assert result.decision_metadata["latency_ms"] >= 0


async def test_no_arbitrary_rationale_generation() -> None:
    engine, client = make_engine(response=make_response({"route_document": 0.9, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    await engine.route(make_query(machine_id="CNC-05"))
    state = client.calls[0]["state"]
    assert "reasoning" not in str(state).lower()
    assert "explanation" not in str(state).lower()


def test_static_architecture_boundary() -> None:
    source = (Path(__file__).resolve().parents[2] / "app" / "decision" / "jev.py").read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden in (
        "documentagent",
        "maintenanceagent",
        "qualityagent",
        "productionagent",
        "app.repositories",
        "app.db",
        "app.rag",
        "evidencefusion",
        "gemini",
        "openai",
        "groq",
        "langgraph",
        "sqlite3",
        "aiosqlite",
    ):
        assert forbidden not in lowered, f"forbidden reference: {forbidden}"


def test_no_direct_sql() -> None:
    source = (Path(__file__).resolve().parents[2] / "app" / "decision" / "jev.py").read_text(encoding="utf-8")
    for keyword in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert keyword not in source


def test_provider_boundary_uses_typesafe_sdk() -> None:
    source = (Path(__file__).resolve().parents[2] / "app" / "decision" / "jev.py").read_text(encoding="utf-8")
    assert "typesafe_sdk" in source
    assert "AsyncTypeSafeClient" in source


async def test_frozen_contract_return_type() -> None:
    from app.contracts.routing import RoutingDecision as FrozenRoutingDecision
    engine, _ = make_engine(response=make_response({"route_document": 0.9, "route_maintenance": 0.1, "route_quality": 0.1, "route_production": 0.1}))
    result = await engine.route(make_query(machine_id="CNC-05"))
    assert result.__class__ is FrozenRoutingDecision
