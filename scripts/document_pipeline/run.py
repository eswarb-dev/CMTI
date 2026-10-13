from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import polars as pl

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.document_pipeline.config import (
    DIAGNOSTICS_DIR,
    MANIFEST_PATH,
    METADATA_DIR,
    PAGES_DIR,
    REPORT_PATH,
    STAGED_DOCUMENT_ROOT,
)
from scripts.document_pipeline.discovery import discover_documents, ensure_directories
from scripts.document_pipeline.extractor import extract_document
from scripts.document_pipeline.metadata import metadata_from_text, refine_document_type
from scripts.document_pipeline.provenance import sha256_file
from scripts.document_pipeline.validators import validate_corpus


PAGE_SCHEMA = {
    "document_id": pl.String,
    "filename": pl.String,
    "page_number": pl.Int64,
    "text": pl.String,
    "character_count": pl.Int64,
    "word_count": pl.Int64,
    "has_text": pl.Boolean,
    "text_quality": pl.String,
    "possible_scanned_page": pl.Boolean,
    "extraction_method": pl.String,
    "source_relative_path": pl.String,
    "has_images": pl.Boolean,
    "image_count": pl.Int64,
    "possible_table": pl.Boolean,
    "possible_figure": pl.Boolean,
    "likely_header": pl.String,
    "likely_footer": pl.String,
}

HEADING_SCHEMA = {
    "document_id": pl.String,
    "page_number": pl.Int64,
    "heading_text": pl.String,
    "heading_level_guess": pl.Int64,
    "detection_method": pl.String,
    "confidence_rule": pl.String,
}

METADATA_SCHEMA = {
    "document_id": pl.String,
    "filename": pl.String,
    "document_type": pl.String,
    "manufacturer": pl.String,
    "machine_family": pl.String,
    "model": pl.String,
    "title": pl.String,
    "revision": pl.String,
    "publication_date": pl.String,
    "page_count": pl.Int64,
    "sha256": pl.String,
    "source_relative_path": pl.String,
}


def ensure_staged_dirs(staged_root: Path | str | None = None) -> None:
    if staged_root is not None:
        root = Path(staged_root)
        for path in [root / "pages", root / "metadata", root / "diagnostics"]:
            path.mkdir(parents=True, exist_ok=True)
        return
    for path in [PAGES_DIR, METADATA_DIR, DIAGNOSTICS_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def resolve_output_paths(
    staged_root: Path | str | None = None,
    manifest_path: Path | str | None = None,
    report_path: Path | str | None = None,
) -> dict[str, Path]:
    """Resolve output locations, defaulting to the canonical STEP 03 paths.

    Tests pass a temporary ``staged_root``/``manifest_path``/``report_path``
    so extraction never touches canonical project artifacts.
    """

    staged = Path(staged_root) if staged_root is not None else STAGED_DOCUMENT_ROOT
    manifest = Path(manifest_path) if manifest_path is not None else MANIFEST_PATH
    report = Path(report_path) if report_path is not None else REPORT_PATH
    return {
        "pages_dir": PAGES_DIR if staged_root is None else staged / "pages",
        "metadata_dir": METADATA_DIR if staged_root is None else staged / "metadata",
        "manifest_path": manifest,
        "report_path": report,
    }


def require_pdf_backend(documents: list[dict[str, Any]]) -> None:
    """Fail explicitly when PDFs must be extracted but PyMuPDF is missing.

    The pipeline must never silently write a partial/empty canonical corpus.
    """

    if any(Path(document["filename"]).suffix.lower() == ".pdf" for document in documents):
        try:
            import fitz  # type: ignore  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "PyMuPDF (fitz) is required for PDF extraction but is not installed; "
                "refusing to write a partial document corpus."
            ) from exc


def write_parquet(path: Path, rows: list[dict[str, Any]], schema: dict[str, pl.DataType]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pl.DataFrame(rows, schema=schema) if rows else pl.DataFrame(schema=schema)
    if path.exists():
        path.unlink()
    frame.write_parquet(path)


def manifest_entry(document: dict[str, Any], metadata: dict[str, Any], page_count: int, status: str, warnings: list[str]) -> dict[str, Any]:
    return {
        "document_id": document["document_id"],
        "filename": document["filename"],
        "relative_path": document["relative_path"],
        "document_type": document["document_type"],
        "manufacturer": metadata.get("manufacturer"),
        "machine_family": metadata.get("machine_family"),
        "model": metadata.get("model"),
        "title": metadata.get("title"),
        "revision": metadata.get("revision"),
        "publication_date": metadata.get("publication_date"),
        "language": "en",
        "page_count": page_count,
        "file_size_bytes": document["file_size_bytes"],
        "sha256": document["sha256"],
        "source_type": "technical_document",
        "is_external_document": True,
        "is_synthetic": False,
        "extraction_status": status,
        "warnings": warnings,
    }


def inspect() -> list[dict[str, Any]]:
    ensure_directories()
    return discover_documents()


def extract(
    raw_root: Path | str | None = None,
    staged_root: Path | str | None = None,
    manifest_path: Path | str | None = None,
    report_path: Path | str | None = None,
) -> dict[str, Any]:
    outputs = resolve_output_paths(staged_root, manifest_path, report_path)
    pages_dir = outputs["pages_dir"]
    metadata_dir = outputs["metadata_dir"]
    manifest_target = outputs["manifest_path"]
    ensure_directories(raw_root)
    ensure_staged_dirs(staged_root)
    documents = discover_documents(raw_root)
    pages: list[dict[str, Any]] = []
    headings: list[dict[str, Any]] = []
    metadata_rows: list[dict[str, Any]] = []
    manifest: list[dict[str, Any]] = []
    seen_hashes: dict[str, str] = {}
    duplicate_groups: dict[str, list[str]] = defaultdict(list)

    if not documents:
        write_parquet(pages_dir / "document_pages.parquet", [], PAGE_SCHEMA)
        write_parquet(metadata_dir / "candidate_headings.parquet", [], HEADING_SCHEMA)
        write_parquet(metadata_dir / "document_metadata.parquet", [], METADATA_SCHEMA)
        manifest_target.parent.mkdir(parents=True, exist_ok=True)
        manifest_target.write_text("[]", encoding="utf-8")
        write_report([], [], [], [], report_path=outputs["report_path"])
        return {"status": "DOCUMENT CORPUS EMPTY", "documents": 0}

    require_pdf_backend(documents)

    for document in documents:
        warnings: list[str] = []
        first_text = None
        if document["sha256"] in seen_hashes:
            duplicate_groups[document["sha256"]].append(document["relative_path"])
            metadata = metadata_from_text(document["path"], None)
            manifest.append(manifest_entry(document, metadata, 0, "duplicate_skipped", ["Exact duplicate of another source document; extraction not duplicated."]))
            continue
        seen_hashes[document["sha256"]] = document["relative_path"]
        duplicate_groups[document["sha256"]].append(document["relative_path"])
        try:
            doc_pages, doc_headings, extraction_meta = extract_document(document)
            first_text = doc_pages[0]["text"] if doc_pages else None
            status = "extracted"
            pages.extend(doc_pages)
            headings.extend(doc_headings)
        except Exception as exc:
            doc_pages = []
            extraction_meta = {"page_count": 0, "pdf_metadata": {}}
            status = "failed"
            warnings.append(str(exc))
        metadata = metadata_from_text(document["path"], first_text, extraction_meta.get("pdf_metadata", {}))
        pdf_meta = extraction_meta.get("pdf_metadata", {})
        title = pdf_meta.get("title") or metadata.get("title")
        metadata["title"] = title
        document_type = refine_document_type(document["document_type"], first_text, pdf_meta)
        document["document_type"] = document_type
        manifest.append(manifest_entry(document, metadata, extraction_meta["page_count"], status, warnings))
        metadata_rows.append(
            {
                "document_id": document["document_id"],
                "filename": document["filename"],
                "document_type": document["document_type"],
                "manufacturer": metadata.get("manufacturer"),
                "machine_family": metadata.get("machine_family"),
                "model": metadata.get("model"),
                "title": metadata.get("title"),
                "revision": metadata.get("revision"),
                "publication_date": metadata.get("publication_date"),
                "page_count": extraction_meta["page_count"],
                "sha256": document["sha256"],
                "source_relative_path": document["relative_path"],
            }
        )
        if sha256_file(document["path"]) != document["sha256"]:
            raise RuntimeError(f"Source document changed during extraction: {document['relative_path']}")

    write_parquet(pages_dir / "document_pages.parquet", pages, PAGE_SCHEMA)
    write_parquet(metadata_dir / "candidate_headings.parquet", headings, HEADING_SCHEMA)
    write_parquet(metadata_dir / "document_metadata.parquet", metadata_rows, METADATA_SCHEMA)
    manifest_target.parent.mkdir(parents=True, exist_ok=True)
    manifest_target.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    duplicates = [paths for paths in duplicate_groups.values() if len(paths) > 1]
    write_report(manifest, pages, headings, duplicates, report_path=outputs["report_path"])
    return {"status": "extracted", "documents": len(manifest), "pages": len(pages)}


def write_report(manifest: list[dict[str, Any]], pages: list[dict[str, Any]], headings: list[dict[str, Any]], duplicates: list[list[str]], report_path: Path | str | None = None) -> None:
    target = Path(report_path) if report_path is not None else REPORT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    by_type = Counter(item["document_type"] for item in manifest)
    manufacturers = sorted({item["manufacturer"] for item in manifest if item.get("manufacturer")})
    families = sorted({item["machine_family"] for item in manifest if item.get("machine_family")})
    qualities = Counter(page["text_quality"] for page in pages)
    source_size = sum(item["file_size_bytes"] for item in manifest)
    ocr_candidates = [f"{page['document_id']} p.{page['page_number']}" for page in pages if page["possible_scanned_page"]]
    lines = [
        "# Document Corpus Report",
        "",
        "## Corpus Summary",
        "",
        f"documents discovered: {len(manifest)}",
        f"documents by type: {dict(by_type)}",
        f"manufacturers: {manufacturers}",
        f"machine families: {families}",
        f"total pages: {len(pages)}",
        f"total words: {sum(page['word_count'] for page in pages)}",
        f"source size: {source_size} bytes",
        "",
        "## Extraction Summary",
        "",
        f"good pages: {qualities.get('GOOD', 0)}",
        f"sparse pages: {qualities.get('SPARSE', 0)}",
        f"empty pages: {qualities.get('EMPTY', 0)}",
        f"possible scanned pages: {qualities.get('POSSIBLE_SCAN', 0)}",
        f"pages with images: {sum(1 for page in pages if page['has_images'])}",
        f"candidate headings: {len(headings)}",
        "",
        "## Documents",
        "",
    ]
    if not manifest:
        lines.extend(["DOCUMENT CORPUS EMPTY", ""])
    for item in manifest:
        doc_pages = [page for page in pages if page["document_id"] == item["document_id"]]
        doc_headings = [heading for heading in headings if heading["document_id"] == item["document_id"]]
        doc_quality = Counter(page["text_quality"] for page in doc_pages)
        representative_headings = [heading["heading_text"] for heading in doc_headings[:12]]
        metadata_gaps = [
            field
            for field in ["manufacturer", "machine_family", "model", "revision", "publication_date"]
            if item.get(field) is None
        ]
        lines.extend(
            [
                f"### {item['document_id']}",
                f"- filename: {item['filename']}",
                f"- type: {item['document_type']}",
                f"- manufacturer: {item['manufacturer']}",
                f"- machine family: {item['machine_family']}",
                f"- model: {item['model']}",
                f"- revision: {item['revision']}",
                f"- publication date: {item['publication_date']}",
                f"- pages: {item['page_count']}",
                f"- text extraction status: {item['extraction_status']}",
                f"- quality counts: {dict(doc_quality)}",
                f"- pages with images: {sum(1 for page in doc_pages if page['has_images'])}",
                f"- candidate headings: {len(doc_headings)}",
                f"- representative headings: {representative_headings}",
                f"- metadata gaps: {metadata_gaps}",
                f"- warnings: {item['warnings']}",
                "",
            ]
        )
    lines.extend(
        [
            "## Extraction Quality By Document",
            "",
        ]
    )
    for item in manifest:
        doc_pages = [page for page in pages if page["document_id"] == item["document_id"]]
        lines.append(f"- {item['filename']}: {dict(Counter(page['text_quality'] for page in doc_pages))}")
    lines.extend(["", "## Candidate Headings", ""])
    for item in manifest:
        doc_headings = [heading for heading in headings if heading["document_id"] == item["document_id"]]
        lines.append(f"- {item['filename']}: {len(doc_headings)} headings; examples: {[heading['heading_text'] for heading in doc_headings[:8]]}")
    metadata_gap_rows = {
        item["filename"]: [
            field
            for field in ["manufacturer", "machine_family", "model", "revision", "publication_date"]
            if item.get(field) is None
        ]
        for item in manifest
    }
    lines.extend(["", "## Duplicate Detection", "", f"exact duplicate files: {duplicates}", "", "## OCR Candidates", "", *[f"- {candidate}" for candidate in ocr_candidates], ""])
    lines.extend(["## Metadata Gaps", "", f"{metadata_gap_rows}", "", "## Warnings", "", "- OCR was not run in STEP 03; possible scanned pages are flagged only.", ""])
    lines.extend(["## RAG Readiness", "", f"documents considered usable: {sum(1 for item in manifest if item['extraction_status'] == 'extracted')}", f"documents needing review: {sum(1 for item in manifest if item['warnings'] or item['extraction_status'] != 'extracted')}", "known extraction issues: OCR not run in STEP 03; possible scanned pages are flagged only.", ""])
    target.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="STEP 03 technical document corpus preparation")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--inspect", action="store_true")
    group.add_argument("--extract", action="store_true")
    group.add_argument("--validate", action="store_true")
    group.add_argument("--all", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.inspect:
        docs = inspect()
        print(json.dumps({"documents": len(docs), "paths": [doc["relative_path"] for doc in docs]}, indent=2))
    elif args.extract:
        print(json.dumps(extract(), indent=2))
    elif args.validate:
        print(json.dumps(validate_corpus(), indent=2))
    elif args.all:
        result = extract()
        validation = validate_corpus()
        print(json.dumps({"extraction": result, "validation": validation}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

