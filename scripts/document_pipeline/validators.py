from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import polars as pl

from .config import MANIFEST_PATH, METADATA_DIR, PAGES_DIR, RAW_DOCUMENT_ROOT
from .discovery import ensure_directories
from .provenance import sha256_file


def _load_manifest(manifest_path: Path) -> list[dict[str, Any]]:
    if not manifest_path.exists():
        raise FileNotFoundError(manifest_path)
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def validate_corpus(
    raw_root: Path | str | None = None,
    staged_root: Path | str | None = None,
    manifest_path: Path | str | None = None,
) -> dict[str, Any]:
    """Validate staged artifacts, defaulting to the canonical STEP 03 paths.

    Tests pass temporary roots so validation never depends on (or implies
    mutation of) canonical project artifacts.
    """

    manifest_target = Path(manifest_path) if manifest_path is not None else MANIFEST_PATH
    staged = Path(staged_root) if staged_root is not None else None
    pages_dir = PAGES_DIR if staged is None else staged / "pages"
    metadata_dir = METADATA_DIR if staged is None else staged / "metadata"
    raw = Path(raw_root) if raw_root is not None else RAW_DOCUMENT_ROOT
    ensure_directories(raw_root)
    manifest = _load_manifest(manifest_target)
    pages_path = pages_dir / "document_pages.parquet"
    metadata_path = metadata_dir / "document_metadata.parquet"
    headings_path = metadata_dir / "candidate_headings.parquet"
    for path in [pages_path, metadata_path, headings_path]:
        if not path.is_file():
            raise FileNotFoundError(path)
        pl.read_parquet(path)

    pages = pl.read_parquet(pages_path)
    metadata = pl.read_parquet(metadata_path)
    document_ids = [item["document_id"] for item in manifest]
    duplicates = [doc_id for doc_id, count in Counter(document_ids).items() if count > 1]
    if duplicates:
        raise ValueError(f"Duplicate document IDs in manifest: {duplicates}")

    for item in manifest:
        source = raw / item["relative_path"]
        if not source.is_file():
            raise FileNotFoundError(source)
        if sha256_file(source) != item["sha256"]:
            raise ValueError(f"Source hash mismatch: {item['relative_path']}")
        if item["extraction_status"] == "extracted":
            doc_pages = pages.filter(pl.col("document_id") == item["document_id"])
            if doc_pages.height != item["page_count"]:
                raise ValueError(f"Page count mismatch for {item['document_id']}")
            numbers = doc_pages.sort("page_number")["page_number"].to_list()
            if numbers != list(range(1, item["page_count"] + 1)):
                raise ValueError(f"Non-sequential page numbers for {item['document_id']}")
            required = ["document_id", "filename", "source_relative_path", "page_number"]
            for column in required:
                if doc_pages[column].null_count() > 0:
                    raise ValueError(f"Missing page provenance for {item['document_id']}")
            doc_meta = metadata.filter(pl.col("document_id") == item["document_id"])
            if doc_meta.height != 1:
                raise ValueError(f"Missing document metadata for {item['document_id']}")

    return {
        "status": "passed",
        "documents": len(manifest),
        "pages": pages.height,
        "metadata_rows": metadata.height,
        "candidate_headings": pl.read_parquet(headings_path).height,
    }

