from __future__ import annotations

import inspect
import logging
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.dependencies import close_resource
from app.api.auth import router as auth_router
from app.api.documents import router as documents_router
from app.api.routes import router
from app.auth import LocalAuthRepository, LocalAuthService
from app.core.config import Settings, get_settings
from app.orchestration import build_manufacturaiq_orchestrator
from app.rag.embeddings import build_embedding_model

logger = logging.getLogger(__name__)

APP_VERSION = "0.1.0"


def create_app(
    orchestrator: Any | None = None,
    settings: Settings | None = None,
    orchestrator_factory: Callable[[], Any] = build_manufacturaiq_orchestrator,
    document_service: Any | None = None,
    document_resources: Any | None = None,
    auth_service: Any | None = None,
) -> FastAPI:
    """Create the FastAPI application without import-time heavy initialization."""

    resolved_settings = settings or get_settings()
    owns_orchestrator = orchestrator is None
    owns_documents = document_service is None and document_resources is None
    owns_auth = auth_service is None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.startup_complete = False
        app.state.orchestrator_owner = owns_orchestrator
        resources = document_resources
        service = document_service
        auth = auth_service
        auth_repository = None
        embedder = build_embedding_model(
            resolved_settings.embedding_model,
            query_cache_size=resolved_settings.query_embedding_cache_size,
        )
        app.state.embedding_model = embedder
        app.state.embedding_warmup_seconds = 0.0
        if owns_orchestrator and resolved_settings.embedding_warmup_enabled:
            warmup_started = time.perf_counter()
            await embedder.aencode(["manufacturing"], as_query=True)
            app.state.embedding_warmup_seconds = time.perf_counter() - warmup_started
            logger.info(
                "embedding warmup complete",
                extra={
                    "embedding_model": resolved_settings.embedding_model,
                    "warmup_seconds": round(app.state.embedding_warmup_seconds, 3),
                },
            )
        if auth is None:
            auth_repository = LocalAuthRepository(resolved_settings.auth_database_path)
            auth_repository.initialize()
            auth = LocalAuthService(
                auth_repository,
                jwt_secret=resolved_settings.auth_jwt_secret,
                access_token_minutes=resolved_settings.auth_access_token_minutes,
            )
        app.state.auth_service = auth
        app.state.auth_repository = auth_repository
        if resources is None and service is None and resolved_settings.document_upload_enabled:
            from app.documents.ingestion import build_document_resources

            resources = build_document_resources(resolved_settings, embedder=embedder)
        if service is None and resources is not None:
            service = resources.build_service()
        app.state.document_resources = resources
        app.state.document_service = service
        app.state.document_owner = owns_documents
        if orchestrator is not None:
            app.state.orchestrator = orchestrator
        else:
            try:
                accepts_resources = "document_resources" in inspect.signature(
                    orchestrator_factory).parameters
            except (TypeError, ValueError):
                accepts_resources = False
            if accepts_resources:
                try:
                    accepts_embedder = "embedding_model" in inspect.signature(
                        orchestrator_factory).parameters
                except (TypeError, ValueError):
                    accepts_embedder = False
                if accepts_embedder:
                    app.state.orchestrator = orchestrator_factory(
                        document_resources=resources,
                        embedding_model=embedder,
                    )
                else:
                    app.state.orchestrator = orchestrator_factory(document_resources=resources)
            else:
                app.state.orchestrator = orchestrator_factory()
        app.state.startup_complete = True
        try:
            yield
        finally:
            if app.state.orchestrator_owner:
                try:
                    await close_resource(app.state.orchestrator)
                except Exception:
                    logger.exception("orchestrator shutdown failed")
            if app.state.document_owner and app.state.document_resources is not None:
                try:
                    app.state.document_resources.close()
                except Exception:
                    logger.exception("document resources shutdown failed")
            if app.state.auth_owner and app.state.auth_repository is not None:
                try:
                    app.state.auth_repository.close()
                except Exception:
                    logger.exception("auth repository shutdown failed")

    app = FastAPI(
        title="ManufacturaIQ API",
        version=APP_VERSION,
        description="HTTP adapter for the ManufacturaIQ industrial AI workflow.",
        lifespan=lifespan,
    )

    app.state.settings = resolved_settings
    app.state.orchestrator = orchestrator
    app.state.document_resources = document_resources
    app.state.document_service = document_service
    app.state.document_owner = owns_documents
    app.state.auth_service = auth_service
    app.state.auth_repository = None
    app.state.auth_owner = owns_auth
    app.state.startup_complete = False

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept"],
    )
    app.include_router(router)
    app.include_router(auth_router)
    app.include_router(documents_router)
    return app


app = create_app()

