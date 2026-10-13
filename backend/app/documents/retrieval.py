"""Dynamic + composite document retrieval (STEP 19B1).

Dynamic chunks live in a separate Qdrant collection with compatible payloads.
The composite merges static and dynamic candidates on the same blended score
semantics, deterministically, without boosting either corpus.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.contracts.enums import EvidenceSourceType, SourceKind
from app.contracts.evidence import Evidence, EvidenceProvenance
from app.contracts.query import QueryRequest
from app.core.config import Settings, get_settings
from app.documents.ingestion import DYNAMIC_SOURCE_DATASET
from app.rag.embeddings import EmbeddingModel, build_embedding_model
from app.rag.filters import build_query_filter, validate_top_k
from app.rag.models import map_document_source_type
from app.rag.scoring import RankedHit, rank_hits
from app.rag.vector_store import SearchHit, VectorStore

DYNAMIC_CORPUS = "dynamic"


@dataclass(slots=True)
class _StaticShim:
    """Adapter so the composite treats both corpora uniformly."""

    name: str
    searcher: Any  # exposes search_sync(query, top_k) -> list[RankedHit]
    mapper: Any  # exposes to_evidence(ranked) -> Evidence


class DynamicDocumentRetriever:
    """DocumentRetriever over the dynamic user-document collection only."""

    def __init__(
        self,
        *,
        path: Path | None = None,
        collection: str | None = None,
        embedder: EmbeddingModel | None = None,
        settings: Settings | None = None,
        store: VectorStore | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        default_root = self.settings.document_storage_root / "vectors"
        self.path = Path(path) if path is not None else default_root
        self.collection = collection or self.settings.document_dynamic_collection
        self._embedder = embedder
        self._store: VectorStore | None = store

    @property
    def embedder(self) -> EmbeddingModel:
        if self._embedder is None:
            self._embedder = build_embedding_model(self.settings.embedding_model)
        return self._embedder

    @property
    def store(self) -> VectorStore:
        if self._store is None:
            self._store = VectorStore(self.path, self.collection)
        return self._store

    def close(self) -> None:
        if self._store is not None:
            self._store.close()
            self._store = None

    def search_sync(self, query: QueryRequest, top_k: int = 5) -> list[RankedHit]:
        bounded_top_k = validate_top_k(top_k, self.settings.rag_max_top_k)
        query_filter, _ignored = build_query_filter(query)
        vector = self.embedder.encode([query.query], as_query=True)[0]
        pool = min(max(bounded_top_k * self.settings.rag_candidate_multiplier, 40), 200)
        raw_hits = self.store.search(vector, pool, query_filter)
        return rank_hits(
            raw_hits,
            top_k=bounded_top_k,
            max_per_section=self.settings.rag_max_per_section,
            query=query.query,
            lexical_weight=self.settings.rag_lexical_weight,
            lexical_content_weight=self.settings.rag_lexical_content_weight,
            lexical_heading_weight=self.settings.rag_lexical_heading_weight,
            lexical_phrase_weight=self.settings.rag_lexical_phrase_weight,
        )

    async def retrieve(self, query: QueryRequest, top_k: int = 10) -> list[Evidence]:
        ranked = await asyncio.to_thread(self.search_sync, query, top_k)
        return [self.to_evidence(hit) for hit in ranked]

    def to_evidence(self, ranked: RankedHit) -> Evidence:
        payload = ranked.hit.payload
        heading_path = [str(item) for item in (payload.get("heading_path") or [])]
        document_title = str(payload.get("title") or payload.get("filename") or "").strip()
        heading = heading_path[-1] if heading_path else ""
        title = f"{document_title} — {heading}" if heading and document_title else (heading or document_title)
        title = title.strip()[:300]
        chunk_id = str(payload.get("chunk_id") or ranked.hit.chunk_id)
        metadata: dict[str, Any] = {
            "chunk_id": chunk_id,
            "document_id": payload.get("document_id"),
            "filename": payload.get("filename"),
            "title": payload.get("title"),
            "document_type": payload.get("document_type"),
            "source_type": payload.get("source_type"),
            "heading_path": heading_path,
            "page_start": payload.get("page_start"),
            "page_end": payload.get("page_end"),
            "token_count": payload.get("token_count"),
            "content_hash": payload.get("content_hash"),
            "corpus": DYNAMIC_CORPUS,
            "retrieval_rank": ranked.rank,
            "vector_score_raw": float(ranked.score),
            "lexical_score": float(ranked.lexical_score),
            "rerank_score": float(ranked.rerank_score) if ranked.rerank_score is not None else None,
            "embedding_model": payload.get("embedding_model"),
            "ingestion_version": payload.get("ingestion_version"),
        }
        provenance = EvidenceProvenance(
            source_kind=SourceKind.DOCUMENT,
            source_dataset=DYNAMIC_SOURCE_DATASET,
            source_id=chunk_id,
            source_file=str(payload.get("filename") or "") or None,
            document_id=str(payload.get("document_id") or "") or None,
            chunk_id=chunk_id,
            page_start=int(payload["page_start"]) if payload.get("page_start") is not None else None,
            page_end=int(payload["page_end"]) if payload.get("page_end") is not None else None,
        )
        raw_source = str(payload.get("source_type") or "")
        source_type = (
            EvidenceSourceType(raw_source)
            if raw_source
            else map_document_source_type(str(payload.get("document_type") or ""))
        )
        return Evidence(
            evidence_id=f"EVIDENCE-{chunk_id}",
            source_type=source_type,
            provenance=provenance,
            title=title or str(payload.get("chunk_id") or chunk_id),
            content=str(payload.get("text") or "").strip(),
            retrieval_score=float(ranked.score),
            metadata=metadata,
        )


class CompositeDocumentRetriever:
    """Static + dynamic composition behind the frozen DocumentRetriever protocol."""

    def __init__(self, static_retriever: Any, dynamic_retriever: Any) -> None:
        self._sources = (
            _StaticShim("static", static_retriever, static_retriever),
            _StaticShim("dynamic", dynamic_retriever, dynamic_retriever),
        )

    def close(self) -> None:
        for source in self._sources:
            close = getattr(source.searcher, "close", None)
            if callable(close):
                close()

    @staticmethod
    def _blended(ranked: RankedHit) -> float:
        return float(ranked.rerank_score) if ranked.rerank_score is not None else float(ranked.score)

    @staticmethod
    def _tie_key(ranked: RankedHit) -> tuple[str, int, str]:
        payload = ranked.hit.payload or {}
        try:
            page = int(payload.get("page_start") or 0)
        except (TypeError, ValueError):
            page = 0
        return (str(payload.get("document_id") or ""), page, ranked.hit.chunk_id)

    def _merged(self, query: QueryRequest, top_k: int) -> list[tuple[_StaticShim, RankedHit]]:
        pool: list[tuple[_StaticShim, RankedHit]] = []
        for source in self._sources:
            pool.extend((source, hit) for hit in source.searcher.search_sync(query, top_k))
        ordered = sorted(pool, key=lambda item: (-self._blended(item[1]), self._tie_key(item[1])))
        merged: list[tuple[_StaticShim, RankedHit]] = []
        seen: set[str] = set()
        for source, hit in ordered:
            if hit.hit.chunk_id in seen:
                continue
            seen.add(hit.hit.chunk_id)
            merged.append((source, RankedHit(hit=hit.hit, rank=len(merged) + 1, score=hit.score,
                                             section_key=hit.section_key, lexical_score=hit.lexical_score,
                                             rerank_score=hit.rerank_score)))
            if len(merged) >= top_k:
                break
        return merged

    def search_sync(self, query: QueryRequest, top_k: int = 5) -> list[RankedHit]:
        return [hit for _, hit in self._merged(query, top_k)]

    async def retrieve(self, query: QueryRequest, top_k: int = 10) -> list[Evidence]:
        merged = await asyncio.to_thread(self._merged, query, top_k)
        evidence: list[Evidence] = []
        for source, hit in merged:
            mapped = source.mapper.to_evidence(hit)
            # Preserve the composite rank in metadata without touching scores.
            mapped.metadata["retrieval_rank"] = hit.rank
            evidence.append(mapped)
        return evidence


def build_dynamic_retriever(
    settings: Settings | None = None,
    embedder: EmbeddingModel | None = None,
) -> DynamicDocumentRetriever:
    resolved = settings or get_settings()
    return DynamicDocumentRetriever(settings=resolved, embedder=embedder)


def build_composite_retriever(
    static_retriever: Any | None = None,
    dynamic_retriever: Any | None = None,
    settings: Settings | None = None,
    embedder: EmbeddingModel | None = None,
) -> CompositeDocumentRetriever:
    """Compose static + dynamic retrieval; dynamic collection may be empty."""

    from app.rag.retrieval import DocumentRetrieverImpl

    resolved = settings or get_settings()
    static = static_retriever or DocumentRetrieverImpl(settings=resolved, embedder=embedder)
    dynamic = dynamic_retriever or DynamicDocumentRetriever(settings=resolved, embedder=embedder or static.embedder)
    return CompositeDocumentRetriever(static, dynamic)
