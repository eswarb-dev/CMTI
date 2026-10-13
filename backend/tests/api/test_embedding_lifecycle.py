from __future__ import annotations

import numpy as np
from fastapi.testclient import TestClient

from app.main import create_app
from tests.api.test_query_api import FakeOrchestrator


class CountingEmbedder:
    constructions = 0
    encode_calls: list[tuple[tuple[str, ...], bool]] = []

    def __init__(self) -> None:
        type(self).constructions += 1

    async def aencode(self, texts, *, as_query: bool = False):
        self.encode(texts, as_query=as_query)
        return np.ones((len(texts), 384), dtype=np.float32)

    def encode(self, texts, *, as_query: bool = False):
        type(self).encode_calls.append((tuple(texts), as_query))
        return np.ones((len(texts), 384), dtype=np.float32)


def test_embedding_model_constructed_once_and_warmed_across_three_queries(monkeypatch):
    CountingEmbedder.constructions = 0
    CountingEmbedder.encode_calls = []

    monkeypatch.setattr("app.main.build_embedding_model", lambda *args, **kwargs: CountingEmbedder())
    orchestrator = FakeOrchestrator(mode="human_review")
    app = create_app(orchestrator_factory=lambda **_kwargs: orchestrator)

    with TestClient(app) as client:
        for index in range(3):
            response = client.post("/api/query", json={"query": f"query {index}"})
            assert response.status_code == 200

    assert CountingEmbedder.constructions == 1
    assert CountingEmbedder.encode_calls == [(("manufacturing",), True)]
    assert len(orchestrator.calls) == 3
