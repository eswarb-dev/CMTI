"""Synchronous dynamic PDF ingestion service (STEP 19B1 foundation)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from qdrant_client import models

from app.core.config import Settings, get_settings
from app.documents.models import DocumentRecord, DocumentStatus
from app.documents.registry import DocumentRegistry
from app.documents.storage import DocumentStorage, sanitize_stored_name
from app.documents.validation import (
    ERROR_NO_TEXT,
    extract_pages,
    validate_pdf,
)
from app.rag.chunking import (
    ChunkingConfig,
    HeuristicTokenCounter,
    TransformersTokenCounter,
    build_document_chunks,
)
from app.rag.embeddings import EmbeddingModel, build_embedding_model
from app.rag.models import DocumentNode, SectionNode
from app.rag.vector_store import VectorStore

DYNAMIC_SOURCE_DATASET = "manufacturaiq_dynamic_documents"
DYNAMIC_DOCUMENT_TYPE = "UPLOADED_PDF"


@dataclass(slots=True)
class IngestResult:
    document_id: str
    status: str
    sha256: str
    page_count: int = 0
    chunk_count: int = 0
    duplicate: bool = False
    error_code: str | None = None
    error_message: str | None = None


@dataclass(slots=True)
class DeleteResult:
    document_id: str
    deleted: bool
    error_code: str | None = None
    error_message: str | None = None


def _new_document_id() -> str:
    return f"USR-{uuid.uuid4().hex[:12].upper()}"


def _chunking_config(settings: Settings) -> ChunkingConfig:
    return ChunkingConfig(
        target_tokens=settings.rag_chunk_target_tokens,
        overlap_tokens=settings.rag_chunk_overlap_tokens,
        max_tokens=settings.rag_chunk_max_tokens,
        min_tokens=settings.rag_chunk_min_tokens,
    )


def _token_counter(settings: Settings):
    return TransformersTokenCounter.load(settings.embedding_model) or HeuristicTokenCounter()


class DocumentIngestionService:
    """Validate → store → extract → chunk → embed → index user PDFs."""

    def __init__(
        self,
        *,
        storage: DocumentStorage,
        registry: DocumentRegistry,
        embedder: EmbeddingModel,
        store: VectorStore,
        settings: Settings | None = None,
    ) -> None:
        self.storage = storage
        self.registry = registry
        self.embedder = embedder
        self.store = store
        self.settings = settings or get_settings()

    def close(self) -> None:
        self.store.close()
        self.registry.close()

    # -- read API (no FastAPI types) --

    def list_documents(self, *, status: str | None = None, limit: int = 200) -> list[DocumentRecord]:
        return self.registry.list_documents(status=status, limit=limit)

    def get_document(self, document_id: str) -> DocumentRecord | None:
        return self.registry.find_by_id(document_id)

    # -- ingestion --

    def ingest_pdf(
        self,
        stream: BinaryIO,
        *,
        original_filename: str,
        declared_mime: str | None = None,
    ) -> IngestResult:
        settings = self.settings
        if not settings.document_upload_enabled:
            return IngestResult(document_id="", status=DocumentStatus.FAILED.value,
                                sha256="", error_code="UPLOAD_DISABLED",
                                error_message="document upload is disabled")
        document_id = _new_document_id()
        stored_filename = sanitize_stored_name(document_id)
        max_bytes = settings.document_max_upload_mb * 1024 * 1024
        try:
            stored = self.storage.store_stream(stream, stored_filename=stored_filename,
                                               max_bytes=max_bytes)
        except ValueError as exc:
            return IngestResult(document_id=document_id, status=DocumentStatus.FAILED.value,
                                sha256="", error_code="FILE_REJECTED", error_message=str(exc))

        duplicate_of = self.registry.find_by_sha256(stored.sha256)
        if duplicate_of is not None:
            self.storage.remove_original(stored_filename)
            return IngestResult(document_id=duplicate_of.document_id,
                                status=duplicate_of.status, sha256=duplicate_of.sha256,
                                page_count=duplicate_of.page_count,
                                chunk_count=duplicate_of.chunk_count, duplicate=True)

        try:
            record = self.registry.register(DocumentRecord(
                document_id=document_id,
                original_filename=original_filename[:255],
                stored_filename=stored_filename,
                sha256=stored.sha256,
                mime_type=declared_mime or "application/pdf",
                file_size_bytes=stored.size_bytes,
                status=DocumentStatus.PENDING.value,
            ))
        except ValueError:
            # Lost a SHA-256 uniqueness race: return the winner.
            winner = self.registry.find_by_sha256(stored.sha256)
            self.storage.remove_original(stored_filename)
            if winner is None:  # pragma: no cover - defensive
                return IngestResult(document_id=document_id, status=DocumentStatus.FAILED.value,
                                    sha256=stored.sha256, error_code="REGISTRY_CONFLICT",
                                    error_message="duplicate registration conflict")
            return IngestResult(document_id=winner.document_id, status=winner.status,
                                sha256=winner.sha256, page_count=winner.page_count,
                                chunk_count=winner.chunk_count, duplicate=True)

        self.registry.mark_processing(document_id)
        try:
            return self._process(record, stored.path)
        except Exception as exc:
            self._cleanup_partial_vectors(document_id)
            self.registry.mark_failed(document_id, error_code="INGEST_FAILED",
                                      error_message=f"{type(exc).__name__}: {exc}")
            return IngestResult(document_id=document_id, status=DocumentStatus.FAILED.value,
                                sha256=stored.sha256, error_code="INGEST_FAILED",
                                error_message=f"{type(exc).__name__}: {exc}")

    def _process(self, record: DocumentRecord, stored_path: Path) -> IngestResult:
        settings = self.settings
        validation = validate_pdf(stored_path)
        if not validation.ok:
            self.registry.mark_failed(record.document_id, error_code=validation.error_code or "INVALID",
                                      error_message=validation.error_message or "PDF validation failed")
            return IngestResult(document_id=record.document_id, status=DocumentStatus.FAILED.value,
                                sha256=record.sha256, error_code=validation.error_code,
                                error_message=validation.error_message)

        pages = extract_pages(stored_path)
        if not any(text.strip() for _, text in pages):
            self.registry.mark_failed(record.document_id, error_code=ERROR_NO_TEXT,
                                      error_message="PDF contains no extractable text")
            return IngestResult(document_id=record.document_id, status=DocumentStatus.FAILED.value,
                                sha256=record.sha256, error_code=ERROR_NO_TEXT,
                                error_message="PDF contains no extractable text")

        chunks = self._chunk_pages(record, pages)
        if not chunks:
            self.registry.mark_failed(record.document_id, error_code=ERROR_NO_TEXT,
                                      error_message="PDF produced no chunks")
            return IngestResult(document_id=record.document_id, status=DocumentStatus.FAILED.value,
                                sha256=record.sha256, error_code=ERROR_NO_TEXT,
                                error_message="PDF produced no chunks")

        # Idempotent retry: clear this document's vectors, then deterministic re-upsert.
        self._cleanup_partial_vectors(record.document_id)
        self.store.ensure_collection(self.embedder.dimension)
        batch_size = max(1, settings.document_ingest_batch_size)
        chunk_ids: list[str] = []
        payloads: list[dict[str, Any]] = []
        for chunk in chunks:
            payload = chunk.to_payload()
            payload["corpus"] = "dynamic"
            payload["source_dataset"] = DYNAMIC_SOURCE_DATASET
            chunk_ids.append(chunk.chunk_id)
            payloads.append(payload)
        written = 0
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start:start + batch_size]
            vectors = self.embedder.encode([c.text for c in batch])
            self.store.upsert(
                [c.chunk_id for c in batch],
                [list(map(float, row)) for row in vectors],
                payloads[start:start + len(batch)],
                batch_size=batch_size,
            )
            written += len(batch)

        self.registry.mark_ready(record.document_id, page_count=len(pages), chunk_count=written)
        return IngestResult(document_id=record.document_id, status=DocumentStatus.READY.value,
                            sha256=record.sha256, page_count=len(pages), chunk_count=written)

    def _chunk_pages(self, record: DocumentRecord, pages: list[tuple[int, str]]):
        settings = self.settings
        title = Path(record.original_filename).stem[:200] or record.document_id
        document = DocumentNode(
            document_id=record.document_id,
            filename=record.original_filename,
            relative_path="",
            document_type=DYNAMIC_DOCUMENT_TYPE,
            title=title,
            sha256=record.sha256,
            page_count=len(pages),
        )
        sections = [
            SectionNode(
                document_id=record.document_id,
                section_ordinal=index,
                heading_path=[],
                page_start=page_number,
                page_end=page_number,
                text=text,
                page_spans=[(0, len(text), page_number)],
                heading_method="dynamic_page",
            )
            for index, (page_number, text) in enumerate(pages)
        ]
        return build_document_chunks(
            document,
            sections,
            _chunking_config(settings),
            _token_counter(settings),
            embedding_model=settings.embedding_model,
            ingestion_version="step19b1.v1",
        )

    def _cleanup_partial_vectors(self, document_id: str) -> None:
        try:
            if not self.store.collection_exists():
                return
            self.store.client.delete(
                collection_name=self.store.collection,
                points_selector=models.FilterSelector(
                    filter=models.Filter(must=[
                        models.FieldCondition(key="document_id",
                                              match=models.MatchValue(value=document_id))
                    ])
                ),
                wait=True,
            )
        except Exception:
            pass

    def vector_count_for(self, document_id: str) -> int:
        """Count dynamic vectors for one document (0 when collection missing)."""

        try:
            if not self.store.collection_exists():
                return 0
            return int(self.store.client.count(
                self.store.collection,
                count_filter=models.Filter(must=[
                    models.FieldCondition(key="document_id",
                                          match=models.MatchValue(value=document_id))
                ]),
                exact=True,
            ).count)
        except Exception:
            return 0

    def delete_document(self, document_id: str) -> DeleteResult:
        """Delete vectors → original file → registry row (compensating order).

        The registry row is removed last so a failed attempt stays retryable;
        a missing original file is treated as already cleaned.
        """

        record = self.registry.find_by_id(document_id)
        if record is None:
            return DeleteResult(document_id=document_id, deleted=False,
                                error_code="NOT_FOUND", error_message="unknown document")
        try:
            self._cleanup_partial_vectors(document_id)
            if self.vector_count_for(document_id) != 0:
                return DeleteResult(document_id=document_id, deleted=False,
                                    error_code="INDEX_CLEANUP_FAILED",
                                    error_message="dynamic vectors could not be removed")
        except Exception as exc:
            return DeleteResult(document_id=document_id, deleted=False,
                                error_code="INDEX_CLEANUP_FAILED",
                                error_message=f"{type(exc).__name__}")
        self.storage.remove_original(record.stored_filename)
        if self.storage.has_original(record.stored_filename):
            return DeleteResult(document_id=document_id, deleted=False,
                                error_code="FILE_CLEANUP_FAILED",
                                error_message="original file could not be removed")
        deleted = self.registry.delete_by_id(document_id)
        if not deleted:
            return DeleteResult(document_id=document_id, deleted=False,
                                error_code="REGISTRY_CLEANUP_FAILED",
                                error_message="registry entry could not be removed")
        return DeleteResult(document_id=document_id, deleted=True)

    def _delete_registry_row(self, document_id: str) -> bool:
        connection = self.registry._connection
        cursor = connection.execute(
            "DELETE FROM documents WHERE document_id = ?", (document_id,))
        connection.commit()
        return cursor.rowcount > 0


def build_document_ingestion_service(
    settings: Settings | None = None,
    embedder: EmbeddingModel | None = None,
) -> DocumentIngestionService:
    """Compose the ingestion service on the configured storage root."""

    from app.rag.embeddings import build_embedding_model as _build_embedder

    resolved = settings or get_settings()
    storage = DocumentStorage(resolved.document_storage_root)
    registry = DocumentRegistry(storage.registry_dir / "documents.db")
    embedder = embedder or _build_embedder(
        resolved.embedding_model,
        query_cache_size=resolved.query_embedding_cache_size,
    )
    store = VectorStore(storage.vectors, resolved.document_dynamic_collection)
    return DocumentIngestionService(storage=storage, registry=registry,
                                    embedder=embedder, store=store, settings=resolved)


class DocumentResources:
    """Application-owned dynamic document resources (single shared store).

    The ingestion service and the dynamic retriever MUST share one
    ``VectorStore`` per path per process (STEP 19B1 single-client rule).
    This holder builds both from the same instances.
    """

    def __init__(
        self,
        *,
        storage: DocumentStorage,
        registry: DocumentRegistry,
        embedder: EmbeddingModel,
        store: VectorStore,
        settings: Settings | None = None,
    ) -> None:
        self.storage = storage
        self.registry = registry
        self.embedder = embedder
        self.store = store
        self.settings = settings or get_settings()
        self._closed = False

    def build_service(self) -> DocumentIngestionService:
        return DocumentIngestionService(
            storage=self.storage, registry=self.registry, embedder=self.embedder,
            store=self.store, settings=self.settings,
        )

    def build_dynamic_retriever(self):
        from app.documents.retrieval import DynamicDocumentRetriever

        return DynamicDocumentRetriever(
            path=self.store.path, collection=self.store.collection,
            embedder=self.embedder, settings=self.settings, store=self.store,
        )

    def build_composite_retriever(self):
        from app.documents.retrieval import build_composite_retriever
        from app.rag.retrieval import DocumentRetrieverImpl

        static = DocumentRetrieverImpl(settings=self.settings, embedder=self.embedder)
        return build_composite_retriever(
            static_retriever=static,
            dynamic_retriever=self.build_dynamic_retriever(),
            settings=self.settings,
            embedder=self.embedder,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.store.close()
        self.registry.close()


def build_document_resources(
    settings: Settings | None = None,
    embedder: EmbeddingModel | None = None,
) -> DocumentResources:
    """Compose shared dynamic document resources on the configured root."""

    from app.rag.embeddings import build_embedding_model as _build_embedder

    resolved = settings or get_settings()
    storage = DocumentStorage(resolved.document_storage_root)
    registry = DocumentRegistry(storage.registry_dir / "documents.db")
    embedder = embedder or _build_embedder(
        resolved.embedding_model,
        query_cache_size=resolved.query_embedding_cache_size,
    )
    store = VectorStore(storage.vectors, resolved.document_dynamic_collection)
    return DocumentResources(storage=storage, registry=registry, embedder=embedder,
                             store=store, settings=resolved)
