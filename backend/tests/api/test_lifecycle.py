from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


class CloseableOrchestrator:
    def __init__(self) -> None:
        self.closed = 0
        self.calls = 0

    async def run(self, query):
        self.calls += 1
        raise AssertionError("lifecycle tests do not call query")

    async def aclose(self) -> None:
        self.closed += 1


class FailingCloseOrchestrator(CloseableOrchestrator):
    async def aclose(self) -> None:
        self.closed += 1
        raise RuntimeError("close failed")


def test_app_owned_orchestrator_constructed_once_and_reused():
    created: list[CloseableOrchestrator] = []

    def factory() -> CloseableOrchestrator:
        instance = CloseableOrchestrator()
        created.append(instance)
        return instance

    app = create_app(orchestrator_factory=factory)
    with TestClient(app) as client:
        first = client.get("/ready")
        second = client.get("/ready")

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(created) == 1
    assert created[0].closed == 1


def test_externally_injected_orchestrator_not_closed_by_default():
    orchestrator = CloseableOrchestrator()
    app = create_app(orchestrator=orchestrator)

    with TestClient(app) as client:
        assert client.get("/ready").status_code == 200

    assert orchestrator.closed == 0


def test_no_orchestrator_construction_at_module_import(monkeypatch):
    import app.main as main

    def boom():
        raise AssertionError("module import must not construct orchestrator")

    monkeypatch.setattr(main, "build_manufacturaiq_orchestrator", boom)
    importlib.reload(main)
    assert hasattr(main, "create_app")


def test_startup_failure_prevents_ready_state():
    def factory():
        raise RuntimeError("startup failed")

    app = create_app(orchestrator_factory=factory)
    with pytest.raises(RuntimeError, match="startup failed"):
        with TestClient(app):
            pass


def test_no_duplicate_startup_construction():
    count = 0

    def factory() -> CloseableOrchestrator:
        nonlocal count
        count += 1
        return CloseableOrchestrator()

    app = create_app(orchestrator_factory=factory)
    with TestClient(app) as client:
        assert client.get("/ready").status_code == 200

    assert count == 1


def test_shutdown_failure_is_logged_and_not_raised(caplog):
    app = create_app(orchestrator_factory=FailingCloseOrchestrator)

    with caplog.at_level("ERROR"):
        with TestClient(app) as client:
            assert client.get("/ready").status_code == 200

    assert "orchestrator shutdown failed" in caplog.text

