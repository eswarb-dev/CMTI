from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


class NoCallOrchestrator:
    calls = 0

    async def run(self, query):  # pragma: no cover - health must not call this
        self.calls += 1
        raise AssertionError("health must not call orchestrator")


def test_health_returns_liveness_without_orchestrator_call():
    orchestrator = NoCallOrchestrator()
    app = create_app(orchestrator=orchestrator)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "manufacturaiq"}
    assert orchestrator.calls == 0


def test_ready_reports_injected_orchestrator_available():
    app = create_app(orchestrator=NoCallOrchestrator())

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "service": "manufacturaiq",
        "orchestrator": "available",
    }


def test_health_works_without_provider_keys(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    app = create_app(orchestrator=NoCallOrchestrator())

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200

