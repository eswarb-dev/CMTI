from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from ..contracts.enums import EvidenceSourceType, SourceKind
from ..contracts.evidence import Evidence, EvidenceProvenance
from ..contracts.query import QueryRequest
from ..core.config import Settings, get_settings
from .embeddings import EmbeddingModel, build_embedding_model
from .filters import build_query_filter, validate_top_k
from .models import map_document_source_type
from .scoring import RankedHit, rank_hits
from .vector_store import VectorStore

__all__ = [
    "ChunkIndex",
    "DocumentRetrieverImpl",
    "map_document_source_type",
    "DEFAULT_QUERY_TOP_K",
]

SOURCE_DATASET = "manufacturaiq_document_corpus"
DEFAULT_QUERY_TOP_K = 5
COMPARISON_CANDIDATES_PER_SIDE = 4


@dataclass(slots=True)
class ChunkIndex:
    """Lightweight in-memory neighbour lookup built from the chunk artifact."""

    order: list[str]
    position: dict[str, int]
    neighbours: dict[str, tuple[str | None, str, str | None, str]]

    @classmethod
    def empty(cls) -> "ChunkIndex":
        return cls(order=[], position={}, neighbours={})

    @classmethod
    def load(cls, path: Path) -> "ChunkIndex":
        if not path.exists():
            return cls.empty()
        table = pq.read_table(path, columns=["chunk_id", "document_id", "chunk_ordinal", "text"])
        rows = table.to_pylist()
        rows.sort(key=lambda row: (row["document_id"], row["chunk_ordinal"]))
        order = [row["chunk_id"] for row in rows]
        position = {chunk_id: index for index, chunk_id in enumerate(order)}
        neighbours: dict[str, tuple[str | None, str, str | None, str]] = {}
        for index, row in enumerate(rows):
            previous = rows[index - 1] if index > 0 and rows[index - 1]["document_id"] == row["document_id"] else None
            following = (
                rows[index + 1]
                if index + 1 < len(rows) and rows[index + 1]["document_id"] == row["document_id"]
                else None
            )
            neighbours[row["chunk_id"]] = (
                previous["chunk_id"] if previous else None,
                (previous["text"][:160] if previous else ""),
                following["chunk_id"] if following else None,
                (following["text"][:160] if following else ""),
            )
        return cls(order=order, position=position, neighbours=neighbours)


class DocumentRetrieverImpl:
    """STEP 04 ``DocumentRetriever`` backed by the local hierarchical RAG index."""

    def __init__(
        self,
        *,
        path: Path | None = None,
        collection: str | None = None,
        embedder: EmbeddingModel | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.path = Path(path) if path is not None else self.settings.vector_store_path
        self.collection = collection or self.settings.rag_collection_name
        self._embedder = embedder
        self._store: VectorStore | None = None
        self._chunk_index: ChunkIndex | None = None

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

    @property
    def chunk_index(self) -> ChunkIndex:
        if self._chunk_index is None:
            self._chunk_index = ChunkIndex.load(self.settings.document_chunks_path)
        return self._chunk_index

    def close(self) -> None:
        if self._store is not None:
            self._store.close()
            self._store = None

    def search_sync(self, query: QueryRequest, top_k: int = DEFAULT_QUERY_TOP_K) -> list[RankedHit]:
        bounded_top_k = validate_top_k(top_k, self.settings.rag_max_top_k)
        comparison = split_comparison_query(query.query)
        if comparison is not None:
            return self._comparison_search_sync(query, comparison, bounded_top_k)
        return self._single_search_sync(query, query.query, bounded_top_k)

    def _single_search_sync(
        self,
        query: QueryRequest,
        query_text: str,
        bounded_top_k: int,
        *,
        lexical_weight: float | None = None,
    ) -> list[RankedHit]:
        query_filter, _ignored = build_query_filter(query)
        vector = self.embedder.encode([query_text], as_query=True)[0]
        pool = min(
            max(bounded_top_k * self.settings.rag_candidate_multiplier, 40),
            200,
        )
        raw_hits = self.store.search(vector, pool, query_filter)
        return rank_hits(
            raw_hits,
            top_k=bounded_top_k,
            max_per_section=self.settings.rag_max_per_section,
            query=query_text,
            lexical_weight=self.settings.rag_lexical_weight if lexical_weight is None else lexical_weight,
            lexical_content_weight=self.settings.rag_lexical_content_weight,
            lexical_heading_weight=self.settings.rag_lexical_heading_weight,
            lexical_phrase_weight=self.settings.rag_lexical_phrase_weight,
        )

    def _comparison_search_sync(
        self,
        query: QueryRequest,
        comparison: tuple[str, str],
        bounded_top_k: int,
    ) -> list[RankedHit]:
        left, right = comparison
        per_side = max(COMPARISON_CANDIDATES_PER_SIDE, min(bounded_top_k, 6))
        lexical_weight = max(self.settings.rag_lexical_weight, self.settings.rag_comparison_lexical_weight)
        left_hits = self._single_search_sync(query, left, per_side, lexical_weight=lexical_weight)
        right_hits = self._single_search_sync(query, right, per_side, lexical_weight=lexical_weight)
        merged = merge_comparison_hits(left_hits, right_hits, bounded_top_k)
        return [
            RankedHit(
                hit=ranked.hit,
                rank=index + 1,
                score=ranked.score,
                section_key=ranked.section_key,
                lexical_score=ranked.lexical_score,
                rerank_score=ranked.rerank_score,
            )
            for index, ranked in enumerate(merged)
        ]

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
        previous_id, previous_preview, next_id, next_preview = self.chunk_index.neighbours.get(
            chunk_id, (None, "", None, "")
        )
        metadata: dict[str, Any] = {
            "chunk_id": chunk_id,
            "document_id": payload.get("document_id"),
            "filename": payload.get("filename"),
            "title": payload.get("title"),
            "document_type": payload.get("document_type"),
            "source_type": payload.get("source_type"),
            "manufacturer": payload.get("manufacturer"),
            "machine_family": payload.get("machine_family"),
            "model": payload.get("model"),
            "revision": payload.get("revision"),
            "publication_date": payload.get("publication_date"),
            "heading_path": heading_path,
            "chapter": payload.get("chapter"),
            "section": payload.get("section"),
            "subsection": payload.get("subsection"),
            "page_start": payload.get("page_start"),
            "page_end": payload.get("page_end"),
            "token_count": payload.get("token_count"),
            "content_hash": payload.get("content_hash"),
            "section_key": payload.get("section_key"),
            "section_ordinal": payload.get("section_ordinal"),
            "chunk_ordinal": payload.get("chunk_ordinal"),
            "retrieval_rank": ranked.rank,
            "vector_score_raw": float(ranked.score),
            "lexical_score": float(ranked.lexical_score),
            "rerank_score": float(ranked.rerank_score) if ranked.rerank_score is not None else None,
            "embedding_model": payload.get("embedding_model"),
            "ingestion_version": payload.get("ingestion_version"),
            "previous_chunk_id": previous_id,
            "previous_chunk_preview": previous_preview,
            "next_chunk_id": next_id,
            "next_chunk_preview": next_preview,
        }
        provenance = EvidenceProvenance(
            source_kind=SourceKind.DOCUMENT,
            source_dataset=SOURCE_DATASET,
            source_id=chunk_id,
            source_file=str(payload.get("filename") or "") or None,
            document_id=str(payload.get("document_id") or "") or None,
            chunk_id=chunk_id,
            page_start=int(payload["page_start"]) if payload.get("page_start") is not None else None,
            page_end=int(payload["page_end"]) if payload.get("page_end") is not None else None,
            chapter=str(payload["chapter"]) if payload.get("chapter") else None,
            section=str(payload["section"]) if payload.get("section") else None,
            subsection=str(payload["subsection"]) if payload.get("subsection") else None,
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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.rag.retrieval",
        description="Query the local ManufacturaIQ document RAG index.",
    )
    parser.add_argument("query", help="natural language retrieval query")
    parser.add_argument("--top-k", type=int, default=DEFAULT_QUERY_TOP_K, dest="top_k")
    parser.add_argument("--full", action="store_true", help="print full chunk text")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    query = QueryRequest(query_id="CLI", query=args.query)
    retriever = DocumentRetrieverImpl()
    try:
        evidences = asyncio.run(retriever.retrieve(query, args.top_k))
    finally:
        retriever.close()
    if args.as_json:
        print(
            json.dumps(
                [json.loads(evidence.model_dump_json()) for evidence in evidences],
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    if not evidences:
        print("no results")
        return 0
    for evidence in evidences:
        score = evidence.retrieval_score if evidence.retrieval_score is not None else 0.0
        pages = (
            f"p{evidence.provenance.page_start}-{evidence.provenance.page_end}"
            if evidence.provenance.page_start
            else "p?"
        )
        print(f"[{evidence.metadata.get('retrieval_rank')}] {score:.4f} {pages} {evidence.title}")
        if args.full:
            print(evidence.content)
        else:
            print(f"    {evidence.content[:300]}")
        print()
    return 0


def split_comparison_query(query: str) -> tuple[str, str] | None:
    text = " ".join(query.strip().rstrip("?.!").split())
    patterns = [
        r"^compare\s+(.+?)\s+with\s+(.+)$",
        r"^compare\s+(.+?)\s+and\s+(.+)$",
        r"^difference\s+between\s+(.+?)\s+and\s+(.+)$",
        r"^(.+?)\s+vs\.?\s+(.+)$",
        r"^(.+?)\s+versus\s+(.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        left = match.group(1).strip(" ,;:")
        right = match.group(2).strip(" ,;:")
        if left and right:
            return left, right
    return None


def _hit_sort_key(ranked: RankedHit) -> tuple[float, str]:
    score = ranked.rerank_score if ranked.rerank_score is not None else ranked.score
    return (-float(score), ranked.hit.chunk_id)


def merge_comparison_hits(
    left_hits: list[RankedHit],
    right_hits: list[RankedHit],
    top_k: int,
) -> list[RankedHit]:
    chosen: list[RankedHit] = []
    seen: set[str] = set()

    def add(hit: RankedHit | None) -> None:
        if hit is None or hit.hit.chunk_id in seen or len(chosen) >= top_k:
            return
        chosen.append(hit)
        seen.add(hit.hit.chunk_id)

    add(left_hits[0] if left_hits else None)
    add(right_hits[0] if right_hits else None)
    remainder = sorted(left_hits[1:] + right_hits[1:], key=_hit_sort_key)
    for hit in remainder:
        add(hit)
    return chosen[:top_k]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
