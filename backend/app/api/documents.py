"""Dynamic user-document management endpoints (STEP 19B2).

Thin HTTP layer over ``DocumentIngestionService``: validation, indexing,
and deletion semantics live in the service. Static corpus (``DOC-*``) is
never manageable here; only dynamic (``USR-*``) identifiers are accepted.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, status

from app.api.dependencies import get_document_service
from app.api.schemas import (
    DocumentDeleteResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentUploadResponse,
)
from app.documents.models import DocumentRecord

logger = logging.getLogger(__name__)

router = APIRouter()

_DYNAMIC_ID = re.compile(r"^USR-[0-9A-F]{12}$")

_ERROR_STATUS: dict[str, int] = {
    "NOT_A_PDF": status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    "FILE_REJECTED": status.HTTP_413_CONTENT_TOO_LARGE,
    "UPLOAD_DISABLED": status.HTTP_503_SERVICE_UNAVAILABLE,
}


def _to_response(record: DocumentRecord) -> DocumentResponse:
    return DocumentResponse(
        document_id=record.document_id,
        original_filename=record.original_filename,
        mime_type=record.mime_type,
        file_size_bytes=record.file_size_bytes,
        status=record.status,  # type: ignore[arg-type]
        page_count=record.page_count,
        chunk_count=record.chunk_count,
        created_at=record.created_at,
        updated_at=record.updated_at,
        error_code=record.error_code,
        error_message=record.error_message,
    )


def _require_valid_id(document_id: str) -> None:
    if not _DYNAMIC_ID.match(document_id or ""):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "unknown document"},
        )


def _require_service(service: Any | None) -> Any:
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "document upload is disabled"},
        )
    return service


@router.post("/api/documents", response_model=DocumentUploadResponse,
             status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile,
    service: Annotated[Any | None, Depends(get_document_service)],
    response: Response,
) -> DocumentUploadResponse:
    """Ingest one PDF into the dynamic knowledge base (synchronous)."""

    active = _require_service(service)
    filename = (file.filename or "").strip() or "upload.pdf"
    try:
        result = await asyncio.to_thread(
            active.ingest_pdf, file.file,
            original_filename=filename[:255],
            declared_mime=file.content_type,
        )
    except Exception:
        logger.exception("document upload failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "internal server error"},
        ) from None
    finally:
        try:
            await file.close()
        except Exception:
            pass

    if result.status == "READY":
        record = active.get_document(result.document_id)
        if record is None:  # pragma: no cover - defensive
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                                detail={"error": "internal server error"})
        if result.duplicate:
            response.status_code = status.HTTP_200_OK
        return DocumentUploadResponse(**_to_response(record).model_dump(),
                                      duplicate=result.duplicate)
    if result.duplicate:
        # Duplicate of a non-READY record: report existing state, never READY.
        record = active.get_document(result.document_id)
        if record is None:  # pragma: no cover - defensive
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                                detail={"error": "internal server error"})
        response.status_code = status.HTTP_200_OK
        return DocumentUploadResponse(**_to_response(record).model_dump(), duplicate=True)
    mapped = _ERROR_STATUS.get(result.error_code or "", status.HTTP_422_UNPROCESSABLE_CONTENT)
    raise HTTPException(status_code=mapped,
                        detail={"error": result.error_message or "document rejected",
                                "error_code": result.error_code})


@router.get("/api/documents", response_model=DocumentListResponse)
async def list_documents(
    service: Annotated[Any | None, Depends(get_document_service)],
) -> DocumentListResponse:
    """List dynamic user documents in deterministic registry order."""

    active = _require_service(service)
    records = await asyncio.to_thread(active.list_documents)
    documents = [_to_response(record) for record in records]
    return DocumentListResponse(documents=documents, count=len(documents))


@router.get("/api/documents/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: str,
    service: Annotated[Any | None, Depends(get_document_service)],
) -> DocumentResponse:
    """Return one dynamic registry record (USR-* only)."""

    _require_valid_id(document_id)
    active = _require_service(service)
    record = await asyncio.to_thread(active.get_document, document_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail={"error": "unknown document"})
    return _to_response(record)


@router.delete("/api/documents/{document_id}", response_model=DocumentDeleteResponse)
async def delete_document(
    document_id: str,
    service: Annotated[Any | None, Depends(get_document_service)],
) -> DocumentDeleteResponse:
    """Delete a dynamic document: vectors → file → registry row."""

    _require_valid_id(document_id)
    active = _require_service(service)
    outcome = await asyncio.to_thread(active.delete_document, document_id)
    if not outcome.deleted:
        if outcome.error_code == "NOT_FOUND":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail={"error": "unknown document"})
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail={"error": outcome.error_message or "deletion failed",
                                    "error_code": outcome.error_code})
    return DocumentDeleteResponse(document_id=document_id, deleted=True)
