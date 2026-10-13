"""Dynamic user-document ingestion (STEP 19B1, backend foundation only).

Separate from the frozen STEP 03/06 static corpus: uploads live under the
configured document storage root with their own registry database and Qdrant
collection. No public API endpoints exist yet (STEP 19B2).
"""

from app.documents.ingestion import (
    DeleteResult,
    DocumentIngestionService,
    DocumentResources,
    IngestResult,
    build_document_ingestion_service,
    build_document_resources,
)
from app.documents.models import DocumentRecord, DocumentStatus
from app.documents.registry import DocumentRegistry
from app.documents.retrieval import CompositeDocumentRetriever, DynamicDocumentRetriever
from app.documents.storage import DocumentStorage

__all__ = [
    "CompositeDocumentRetriever",
    "DeleteResult",
    "DocumentIngestionService",
    "DocumentRecord",
    "DocumentRegistry",
    "DocumentResources",
    "DocumentStatus",
    "DocumentStorage",
    "DynamicDocumentRetriever",
    "IngestResult",
    "build_document_ingestion_service",
    "build_document_resources",
]
