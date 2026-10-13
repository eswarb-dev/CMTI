from __future__ import annotations

import asyncio
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

DEFAULT_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


@dataclass(slots=True)
class EmbeddingModel:
    """Local sentence-transformers encoder used for chunks and queries."""

    model_name: str
    device: str | None = None
    query_prefix: str = ""
    batch_size: int = 32
    query_cache_size: int = 128
    _model: Any = field(default=None, repr=False, compare=False)
    _load_seconds: float = field(default=0.0, repr=False)
    _query_cache: OrderedDict[str, np.ndarray] = field(default_factory=OrderedDict, repr=False, compare=False)
    _cache_lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)

    def load(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            started = time.perf_counter()
            self._model = SentenceTransformer(self.model_name, device=self.device)
            self._load_seconds = time.perf_counter() - started
        return self._model

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def dimension(self) -> int:
        model = self.load()
        getter = getattr(model, "get_embedding_dimension", None)
        if getter is None:  # sentence-transformers < 6.x
            getter = model.get_sentence_embedding_dimension
        return int(getter())

    @property
    def resolved_device(self) -> str:
        model = self.load()
        return str(model.device)

    def encode(self, texts: Sequence[str], *, as_query: bool = False) -> np.ndarray:
        if not texts:
            raise ValueError("cannot embed an empty batch of texts")
        if as_query and len(texts) == 1 and self.query_cache_size > 0:
            key = self._prepare(texts[0], as_query=True)
            with self._cache_lock:
                cached = self._query_cache.get(key)
                if cached is not None:
                    self._query_cache.move_to_end(key)
                    return cached.reshape(1, -1).copy()
        model = self.load()
        prepared = [self._prepare(text, as_query=as_query) for text in texts]
        vectors = model.encode(
            prepared,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        array = np.asarray(vectors, dtype=np.float32)
        shaped = array.reshape(len(prepared), -1)
        if as_query and len(texts) == 1 and self.query_cache_size > 0:
            with self._cache_lock:
                self._query_cache[prepared[0]] = shaped[0].copy()
                self._query_cache.move_to_end(prepared[0])
                while len(self._query_cache) > self.query_cache_size:
                    self._query_cache.popitem(last=False)
        return shaped

    async def aencode(self, texts: Sequence[str], *, as_query: bool = False) -> np.ndarray:
        return await asyncio.to_thread(self.encode, texts, as_query=as_query)

    def _prepare(self, text: str, *, as_query: bool) -> str:
        cleaned = text.strip()
        if as_query and self.query_prefix:
            return f"{self.query_prefix}{cleaned}"
        return cleaned

    def describe(self) -> dict[str, Any]:
        return {
            "embedding_model": self.model_name,
            "device": self.resolved_device if self.is_loaded else (self.device or "unloaded"),
            "dimension": self.dimension if self.is_loaded else None,
            "load_seconds": round(self._load_seconds, 3),
            "query_prefix": self.query_prefix,
        }


def build_embedding_model(
    model_name: str,
    *,
    device: str | None = None,
    query_prefix: str = DEFAULT_QUERY_PREFIX,
    query_cache_size: int = 128,
) -> EmbeddingModel:
    """Create an embedding model, enabling the query prefix for bge-style models."""

    prefix = query_prefix if "bge" in model_name.lower() else ""
    return EmbeddingModel(
        model_name=model_name,
        device=device,
        query_prefix=prefix,
        query_cache_size=query_cache_size,
    )
