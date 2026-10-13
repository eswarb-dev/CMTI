from __future__ import annotations

from pathlib import Path

from .config import RAW_DIRECTORIES, RAW_DOCUMENT_ROOT, SUPPORTED_EXTENSIONS
from .metadata import classify_document
from .provenance import document_id_for_hash, sha256_file


def ensure_directories(raw_root: Path | None = None) -> None:
    if raw_root is not None:
        Path(raw_root).mkdir(parents=True, exist_ok=True)
        return
    for path in RAW_DIRECTORIES:
        path.mkdir(parents=True, exist_ok=True)


def discover_documents(raw_root: Path | None = None) -> list[dict]:
    root = Path(raw_root) if raw_root is not None else RAW_DOCUMENT_ROOT
    ensure_directories(raw_root)
    documents = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        sha = sha256_file(path)
        documents.append(
            {
                "path": path,
                "document_id": document_id_for_hash(sha),
                "filename": path.name,
                "relative_path": str(path.relative_to(root)).replace("\\", "/"),
                "document_type": classify_document(path),
                "file_size_bytes": path.stat().st_size,
                "sha256": sha,
            }
        )
    return documents

