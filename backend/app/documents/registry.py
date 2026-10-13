"""SQLite document registry (ingestion metadata only, parameterized SQL)."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.documents.models import DocumentRecord, DocumentStatus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    original_filename TEXT NOT NULL,
    stored_filename TEXT NOT NULL,
    sha256 TEXT NOT NULL UNIQUE,
    mime_type TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    status TEXT NOT NULL,
    page_count INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    error_code TEXT,
    error_message TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_documents_sha256 ON documents(sha256);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
"""

_COLUMNS = (
    "document_id", "original_filename", "stored_filename", "sha256",
    "mime_type", "file_size_bytes", "status", "page_count", "chunk_count",
    "created_at", "updated_at", "error_code", "error_message", "metadata_json",
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_record(row: sqlite3.Row) -> DocumentRecord:
    return DocumentRecord(**{name: row[name] for name in _COLUMNS})


class DocumentRegistry:
    """Idempotent registry for dynamic document ingestion state."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # The API layer runs ingestion in a worker thread; guard the single
        # connection with a lock instead of binding it to one thread.
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        with self._lock:
            self._connection.execute("PRAGMA journal_mode=WAL;")
            self._connection.executescript(_SCHEMA)
            self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def register(self, record: DocumentRecord) -> DocumentRecord:
        """Insert a PENDING document; SHA-256 uniqueness is enforced."""

        now = _utcnow()
        stored = DocumentRecord(
            document_id=record.document_id,
            original_filename=record.original_filename,
            stored_filename=record.stored_filename,
            sha256=record.sha256,
            mime_type=record.mime_type,
            file_size_bytes=record.file_size_bytes,
            status=DocumentStatus.PENDING.value,
            page_count=0,
            chunk_count=0,
            created_at=record.created_at or now,
            updated_at=now,
            error_code=None,
            error_message=None,
            metadata_json=record.metadata_json or "{}",
        )
        try:
            with self._lock:
                self._connection.execute(
                    "INSERT INTO documents "
                    "(document_id, original_filename, stored_filename, sha256, mime_type, "
                    "file_size_bytes, status, page_count, chunk_count, created_at, updated_at, "
                    "error_code, error_message, metadata_json) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (stored.document_id, stored.original_filename, stored.stored_filename,
                     stored.sha256, stored.mime_type, stored.file_size_bytes, stored.status,
                     stored.page_count, stored.chunk_count, stored.created_at, stored.updated_at,
                     stored.error_code, stored.error_message, stored.metadata_json),
                )
                self._connection.commit()
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"document already registered: {exc}") from exc
        return stored

    def find_by_id(self, document_id: str) -> DocumentRecord | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM documents WHERE document_id = ?", (document_id,)
            ).fetchone()
        return _row_to_record(row) if row is not None else None

    def find_by_sha256(self, sha256: str) -> DocumentRecord | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM documents WHERE sha256 = ?", (sha256,)
            ).fetchone()
        return _row_to_record(row) if row is not None else None

    def list_documents(self, *, status: str | None = None, limit: int = 200) -> list[DocumentRecord]:
        with self._lock:
            if status is not None:
                rows = self._connection.execute(
                    "SELECT * FROM documents WHERE status = ? ORDER BY created_at ASC, document_id ASC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = self._connection.execute(
                    "SELECT * FROM documents ORDER BY created_at ASC, document_id ASC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [_row_to_record(row) for row in rows]

    def update_status(self, document_id: str, status: str, **fields: Any) -> DocumentRecord | None:
        allowed = {"page_count", "chunk_count", "error_code", "error_message", "metadata_json"}
        assignments = ["status = ?", "updated_at = ?"]
        values: list[Any] = [status, _utcnow()]
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(f"refusing to update registry field: {key}")
            assignments.append(f"{key} = ?")
            values.append(value)
        values.append(document_id)
        with self._lock:
            cursor = self._connection.execute(
                f"UPDATE documents SET {', '.join(assignments)} WHERE document_id = ?",
                tuple(values),
            )
            self._connection.commit()
        if cursor.rowcount == 0:
            return None
        return self.find_by_id(document_id)

    def mark_processing(self, document_id: str) -> DocumentRecord | None:
        return self.update_status(document_id, DocumentStatus.PROCESSING.value,
                                  error_code=None, error_message=None)

    def mark_ready(self, document_id: str, *, page_count: int, chunk_count: int) -> DocumentRecord | None:
        return self.update_status(document_id, DocumentStatus.READY.value,
                                  page_count=page_count, chunk_count=chunk_count,
                                  error_code=None, error_message=None)

    def mark_failed(self, document_id: str, *, error_code: str, error_message: str) -> DocumentRecord | None:
        return self.update_status(document_id, DocumentStatus.FAILED.value,
                                  error_code=error_code,
                                  error_message=_sanitize_error(error_message))

    def delete_by_id(self, document_id: str) -> bool:
        """Remove a registry row; returns True when a row was removed."""

        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM documents WHERE document_id = ?", (document_id,))
            self._connection.commit()
            return cursor.rowcount > 0


def _sanitize_error(message: str) -> str:
    """Keep failure reasons short and free of secret-looking material."""

    text = " ".join(str(message or "").split())
    return text[:500]
