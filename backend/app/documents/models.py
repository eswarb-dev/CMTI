"""Registry record model for dynamic user documents."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DocumentStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


@dataclass(slots=True)
class DocumentRecord:
    """One registered user-supplied document (metadata only, never content)."""

    document_id: str
    original_filename: str
    stored_filename: str
    sha256: str
    mime_type: str
    file_size_bytes: int
    status: str
    page_count: int = 0
    chunk_count: int = 0
    created_at: str = ""
    updated_at: str = ""
    error_code: str | None = None
    error_message: str | None = None
    metadata_json: str = "{}"

    def metadata(self) -> dict[str, Any]:
        try:
            parsed = json.loads(self.metadata_json or "{}")
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @classmethod
    def with_metadata(cls, record: "DocumentRecord", metadata: dict[str, Any]) -> "DocumentRecord":
        merged = record.metadata()
        merged.update(metadata)
        import dataclasses

        return dataclasses.replace(record, metadata_json=json.dumps(merged, sort_keys=True))
