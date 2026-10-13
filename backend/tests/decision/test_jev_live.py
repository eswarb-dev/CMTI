"""Optional live Jev integration tests. Skipped when TYPESAFE_API_KEY is absent."""
from __future__ import annotations

import os

import pytest

from app.contracts.enums import AgentName
from app.contracts.query import QueryRequest
from app.core.config import get_settings
from app.decision.jev import build_jev_decision_engine

pytestmark = pytest.mark.skipif(
    not os.environ.get("TYPESAFE_API_KEY"),
    reason="TYPESAFE_API_KEY not set",
)


@pytest.mark.asyncio
async def test_live_document_route() -> None:
    engine = build_jev_decision_engine()
    try:
        result = await engine.route(
            QueryRequest(query_id="LIVE-DOC", query="Show the lockout/tagout procedure.")
        )
        assert AgentName.DOCUMENT in result.selected_agents
    finally:
        await engine.aclose()


@pytest.mark.asyncio
async def test_live_maintenance_route() -> None:
    engine = build_jev_decision_engine()
    try:
        result = await engine.route(
            QueryRequest(
                query_id="LIVE-MNT",
                query="Show recent alarms and maintenance activity for this machine.",
                machine_id="CNC-05",
            )
        )
        assert AgentName.MAINTENANCE in result.selected_agents
    finally:
        await engine.aclose()


@pytest.mark.asyncio
async def test_live_quality_route() -> None:
    engine = build_jev_decision_engine()
    try:
        result = await engine.route(
            QueryRequest(
                query_id="LIVE-QLT",
                query="Check inspection failures for this batch.",
                batch_id="B-001",
            )
        )
        assert AgentName.QUALITY in result.selected_agents
    finally:
        await engine.aclose()


@pytest.mark.asyncio
async def test_live_production_route() -> None:
    engine = build_jev_decision_engine()
    try:
        result = await engine.route(
            QueryRequest(
                query_id="LIVE-PRD",
                query="Show rejected production output for this product.",
                product_id="SHAFT-A",
            )
        )
        assert AgentName.PRODUCTION in result.selected_agents
    finally:
        await engine.aclose()


@pytest.mark.asyncio
async def test_live_multi_domain_route() -> None:
    engine = build_jev_decision_engine()
    try:
        result = await engine.route(
            QueryRequest(
                query_id="LIVE-MULTI",
                query="Investigate why CNC-05 rejects increased and whether there were machine alarms.",
                machine_id="CNC-05",
            )
        )
        assert AgentName.MAINTENANCE in result.selected_agents
    finally:
        await engine.aclose()
