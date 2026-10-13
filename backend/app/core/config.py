from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


#: Canonical default Gemini model. Blank/whitespace ``GEMINI_MODEL`` values
#: are normalized to this single default (see ``_default_blank_gemini_model``).
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"


class Settings(BaseSettings):
    """Application configuration with optional future provider settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    app_env: str = "development"
    log_level: str = "INFO"
    cors_allowed_origins: list[str] = ["http://localhost:5173"]
    database_url: str | None = None
    qdrant_path: str | None = None
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_warmup_enabled: bool = True
    query_embedding_cache_size: int = 128
    rag_collection_name: str = "manufacturaiq_documents"
    rag_chunk_target_tokens: int = 448
    rag_chunk_overlap_tokens: int = 80
    rag_chunk_max_tokens: int = 500
    rag_chunk_min_tokens: int = 120
    rag_max_top_k: int = 50
    rag_candidate_multiplier: int = 4
    rag_max_per_section: int = 3
    rag_header_lines: int = 3
    # Lexical rerank blend (STEP 06A): ordering uses
    # ``(1 - rag_lexical_weight) * vector + rag_lexical_weight * lexical``.
    # ``Evidence.retrieval_score`` always stays the raw vector score; the
    # lexical and combined components are exposed via ``Evidence.metadata``.
    # Default 0.1: the smallest blend that promotes genuine technical sections
    # (e.g. Siemens tool-management lists) without disturbing vector order.
    rag_lexical_weight: float = 0.1
    rag_lexical_content_weight: float = 0.5
    rag_lexical_heading_weight: float = 0.3
    rag_lexical_phrase_weight: float = 0.2
    rag_comparison_lexical_weight: float = 0.25
    # STEP 07: default evidence budget for DocumentAgent. The retriever owns
    # clamping to its own maximum (rag_max_top_k); the agent never asks for
    # the full index by default.
    document_agent_top_k: int = 8
    # STEP 08: bounded evidence budgets for MaintenanceAgent. Repository
    # methods own their own clamping; these are the agent's request sizes.
    maintenance_agent_maintenance_limit: int = 8
    maintenance_agent_alarm_limit: int = 10
    # Prototype telemetry retrieval window (NOT an industrial threshold):
    # 168 hours = 7 days of machine telemetry per summary.
    maintenance_agent_telemetry_lookback_hours: int = 168
    maintenance_agent_alarm_summary_limit: int = 5
    # STEP 09: bounded evidence budgets for QualityAgent.
    quality_agent_inspection_limit: int = 12
    quality_agent_failure_limit: int = 8
    # STEP 10: bounded evidence budgets for ProductionAgent.
    production_agent_order_limit: int = 12
    typesafe_api_key: str | None = None
    typesafe_model: str | None = None
    gemini_api_key: str | None = None
    gemini_model: str = DEFAULT_GEMINI_MODEL
    gemini_fallback_model: str = "gemini-3.5-flash-lite"
    gemini_model_fallback_enabled: bool = True
    gemini_enabled: bool = True
    gemini_thinking_level: str = "low"
    gemini_timeout_seconds: float = 10.0
    gemini_primary_timeout_seconds: float = 6.0
    gemini_request_timeout_seconds: float = 10.0
    gemini_total_budget_seconds: float = 15.0
    gemini_retry_backoff_seconds: float = 0.5
    gemini_max_output_tokens: int = 3072
    gemini_max_retries: int = 1
    gemini_max_attempts: int = 2
    query_total_timeout_seconds: float = 20.0
    jev_routing_threshold: float | None = None
    jev_evidence_threshold: float | None = None
    jev_review_threshold: float | None = None
    jev_model: str = "jev-latest"
    jev_route_threshold: float = 0.50
    jev_timeout_seconds: float = 10.0
    jev_max_retries: int = 1
    jev_enabled: bool = True
    jev_review_threshold: float = 0.50
    jev_review_enabled: bool = True
    # STEP 19B1: dynamic user-document ingestion (separate from frozen corpus).
    document_upload_enabled: bool = True
    document_storage_path: str | None = None
    document_max_upload_mb: int = 50
    document_dynamic_collection: str = "manufacturaiq_dynamic_documents"
    document_ingest_batch_size: int = 32
    auth_jwt_secret: str | None = None
    auth_access_token_minutes: int = 480

    project_root: Path = Field(default_factory=lambda: Path(__file__).resolve().parents[3])

    @field_validator("gemini_model", mode="before")
    @classmethod
    def _default_blank_gemini_model(cls, value: object) -> object:
        """Normalize blank/whitespace GEMINI_MODEL to the canonical default.

        An empty ``GEMINI_MODEL=`` line in a local ``.env`` must not override
        the default with an unusable empty model identifier.
        """

        if value is None:
            return DEFAULT_GEMINI_MODEL
        if isinstance(value, str) and not value.strip():
            return DEFAULT_GEMINI_MODEL
        return value

    @field_validator("document_max_upload_mb", "document_ingest_batch_size")
    @classmethod
    def _positive_document_limits(cls, value: int, info) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{info.field_name} must be a positive integer")
        return value

    @field_validator("document_dynamic_collection")
    @classmethod
    def _non_blank_dynamic_collection(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("document_dynamic_collection must not be blank")
        return value.strip()

    @property
    def document_storage_root(self) -> Path:
        """Resolve the dynamic document storage root (never the frozen corpus)."""

        if self.document_storage_path and self.document_storage_path.strip():
            return Path(self.document_storage_path.strip()).expanduser()
        return self.project_root / "data" / "documents"

    @property
    def dataset_root(self) -> Path:
        return self.project_root / "datasets"

    @property
    def demo_factory_root(self) -> Path:
        return self.dataset_root / "normalized" / "demo_factory"

    @property
    def default_database_path(self) -> Path:
        return self.project_root / "backend" / "data" / "manufacturaiq.db"

    @property
    def database_path(self) -> Path:
        """Resolve the operational SQLite path from DATABASE_URL.

        Supports a plain filesystem path, ``sqlite:///relative/path.db``,
        ``sqlite:////absolute/path.db`` and ``sqlite://absolute/path.db``.
        An empty or missing ``DATABASE_URL`` falls back to
        ``backend/data/manufacturaiq.db`` below the project root.
        """

        return resolve_sqlite_path(self.database_url, default_path=self.default_database_path)

    @property
    def auth_database_path(self) -> Path:
        return self.project_root / "backend" / "data" / "auth.db"

    @property
    def external_data_root(self) -> Path:
        return self.dataset_root / "normalized" / "external"

    @property
    def document_manifest_path(self) -> Path:
        return self.dataset_root / "manifests" / "documents.json"

    @property
    def document_pages_path(self) -> Path:
        return self.dataset_root / "staged" / "documents" / "pages" / "document_pages.parquet"

    @property
    def document_metadata_path(self) -> Path:
        return self.dataset_root / "staged" / "documents" / "metadata" / "document_metadata.parquet"

    @property
    def document_headings_path(self) -> Path:
        return self.dataset_root / "staged" / "documents" / "metadata" / "candidate_headings.parquet"

    @property
    def vector_store_path(self) -> Path:
        return Path(self.qdrant_path) if self.qdrant_path else self.project_root / "vector_store"

    @property
    def document_chunks_path(self) -> Path:
        return self.dataset_root / "normalized" / "documents" / "document_chunks.parquet"

    @property
    def rag_build_report_path(self) -> Path:
        return self.dataset_root / "reports" / "RAG_BUILD_REPORT.md"


def resolve_sqlite_path(database_url: str | None, *, default_path: Path) -> Path:
    """Convert a configured DATABASE_URL value into a local SQLite file path."""

    if database_url is None:
        return default_path
    value = database_url.strip()
    if not value:
        return default_path
    if value.startswith("sqlite:///"):
        raw = value[len("sqlite:///") :]
    elif value.startswith("sqlite://"):
        raw = value[len("sqlite://") :]
    elif value.startswith("sqlite:"):
        raw = value[len("sqlite:") :]
    else:
        raw = value
    if not raw:
        return default_path
    return Path(raw).expanduser()


@lru_cache
def get_settings() -> Settings:
    """Return cached settings for application modules."""

    return Settings()

