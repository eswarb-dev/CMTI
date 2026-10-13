from __future__ import annotations

import pytest

from app.rag.vector_store import VectorStore, point_id_for


def test_point_ids_are_stable_uuid5_values() -> None:
    value = point_id_for("CHUNK-1")

    assert value == point_id_for("CHUNK-1")
    assert value != point_id_for("CHUNK-2")
    assert len(value.split("-")) == 5


def test_vector_store_refuses_a_second_client_on_the_same_path(tmp_path) -> None:
    path = tmp_path / "store"
    first = VectorStore(path, "test_collection")
    first.ensure_collection(4)
    assert first.collection_exists()

    second = VectorStore(path, "test_collection")
    with pytest.raises(RuntimeError, match="already open"):
        second.client

    first.close()
    second.close()

    third = VectorStore(path, "test_collection")
    assert third.collection_exists()
    third.close()


def test_upsert_and_search_round_trip_with_filters(tmp_path) -> None:
    path = tmp_path / "store"
    store = VectorStore(path, "test_collection")
    try:
        store.ensure_collection(3)
        store.upsert(
            ["CHUNK-A", "CHUNK-B"],
            [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            [
                {"chunk_id": "CHUNK-A", "document_id": "DOC-A", "source_type": "SAFETY"},
                {"chunk_id": "CHUNK-B", "document_id": "DOC-B", "source_type": "MANUAL"},
            ],
        )
        assert store.point_count() == 2

        from qdrant_client import models

        hits = store.search([1.0, 0.0, 0.0], 5)
        assert len(hits) == 2
        assert hits[0].chunk_id == "CHUNK-A"

        safety_only = store.search(
            [1.0, 0.0, 0.0],
            5,
            models.Filter(
                must=[models.FieldCondition(key="source_type", match=models.MatchValue(value="SAFETY"))]
            ),
        )
        assert [hit.chunk_id for hit in safety_only] == ["CHUNK-A"]

        assert store.search([1.0, 0.0, 0.0], 0) == []
    finally:
        store.close()
