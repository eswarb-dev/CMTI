"""Hierarchical document retrieval (STEP 06).

Modules:
    models       - internal dataclasses shared across the RAG pipeline
    hierarchy    - deterministic heading detection and section reconstruction
    chunking     - section-aware, token-bounded chunking with stable ids
    embeddings   - local sentence-transformers encoder wrapper
    vector_store - local Qdrant collection helpers with atomic rebuilds
    ingestion    - canonical ``python -m app.rag.ingestion`` entry point
    retrieval    - ``DocumentRetriever`` implementation and search CLI
    filters      - user-context metadata filtering and top_k validation
    scoring      - hierarchy-aware re-ranking of raw vector hits
    validation   - ``python -m app.rag.validation`` checks and metrics
"""

from .models import INGESTION_VERSION, SOURCE_DATASET, ChunkRecord, DocumentNode, SectionNode

__all__ = [
    "ChunkRecord",
    "DocumentNode",
    "INGESTION_VERSION",
    "SOURCE_DATASET",
    "SectionNode",
]
