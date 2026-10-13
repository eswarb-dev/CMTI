from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from qdrant_client import QdrantClient, models

POINT_ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "manufacturaiq/chunk")

# Local Qdrant only supports one live client per storage path. Opening a
# second client silently reports an empty collection, so overlapping opens are
# refused instead of returning no results.
_ACTIVE_CLIENTS: dict[str, "VectorStore"] = {}


def point_id_for(chunk_id: str) -> str:
    """Deterministic UUID5 so repeated ingestion overwrites the same point."""

    return str(uuid.uuid5(POINT_ID_NAMESPACE, chunk_id))


@dataclass(slots=True)
class SearchHit:
    chunk_id: str
    score: float
    payload: dict[str, Any]


class VectorStore:
    """Thin wrapper around a local (on-disk) Qdrant collection."""

    def __init__(self, path: Path | str, collection: str) -> None:
        self.path = Path(path)
        self.collection = collection
        self._client: QdrantClient | None = None
        self._path_key: str | None = None

    @property
    def client(self) -> QdrantClient:
        if self._client is None:
            self.path.mkdir(parents=True, exist_ok=True)
            key = str(self.path.resolve())
            if key in _ACTIVE_CLIENTS:
                raise RuntimeError(
                    f"vector store at {self.path} is already open in this process; "
                    "reuse the existing VectorStore instead of opening a second one"
                )
            self._client = QdrantClient(path=str(self.path))
            self._path_key = key
            _ACTIVE_CLIENTS[key] = self
        return self._client

    def close(self) -> None:
        if self._client is not None:
            key = self._path_key
            self._client.close()
            if key is not None and _ACTIVE_CLIENTS.get(key) is self:
                _ACTIVE_CLIENTS.pop(key, None)
            self._client = None
            self._path_key = None

    def __enter__(self) -> "VectorStore":
        self.client
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def collection_exists(self) -> bool:
        try:
            return self.client.collection_exists(self.collection)
        except Exception:
            return False

    def ensure_collection(self, dimension: int) -> None:
        if self.collection_exists():
            info = self.client.get_collection(self.collection)
            existing = int(info.config.params.vectors.size or 0)
            if existing != dimension:
                raise ValueError(
                    f"collection '{self.collection}' has dimension {existing}, expected {dimension}"
                )
            return
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=models.VectorParams(size=dimension, distance=models.Distance.COSINE),
        )

    def point_count(self) -> int:
        if not self.collection_exists():
            return 0
        return int(self.client.count(self.collection, exact=True).count)

    def upsert(
        self,
        chunk_ids: Sequence[str],
        vectors: Sequence[Sequence[float]],
        payloads: Sequence[dict[str, Any]],
        *,
        batch_size: int = 256,
    ) -> int:
        if not (len(chunk_ids) == len(vectors) == len(payloads)):
            raise ValueError("chunk ids, vectors and payloads must have the same length")
        written = 0
        for start in range(0, len(chunk_ids), batch_size):
            stop = start + batch_size
            points = [
                models.PointStruct(
                    id=point_id_for(chunk_id),
                    vector=[float(value) for value in vector],
                    payload=payload,
                )
                for chunk_id, vector, payload in zip(
                    chunk_ids[start:stop], vectors[start:stop], payloads[start:stop]
                )
            ]
            self.client.upsert(collection_name=self.collection, points=points, wait=True)
            written += len(points)
        return written

    def search(
        self,
        vector: Sequence[float],
        limit: int,
        query_filter: models.Filter | None = None,
    ) -> list[SearchHit]:
        if not self.collection_exists() or limit <= 0:
            return []
        points = self.client.query_points(
            collection_name=self.collection,
            query=[float(value) for value in vector],
            limit=limit,
            query_filter=query_filter,
            with_payload=True,
            with_vectors=False,
        ).points
        hits: list[SearchHit] = []
        for point in points:
            payload = dict(point.payload or {})
            chunk_id = str(payload.get("chunk_id") or point.id)
            hits.append(SearchHit(chunk_id=chunk_id, score=float(point.score), payload=payload))
        return hits

    def delete_collection(self) -> None:
        if self.collection_exists():
            self.client.delete_collection(self.collection)

    def reset(self) -> None:
        self.close()
        shutil.rmtree(self.path, ignore_errors=True)
        self.path.mkdir(parents=True, exist_ok=True)
