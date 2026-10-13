from __future__ import annotations

from pathlib import Path
from typing import Any

from .diagnostics import classify_page_quality, repeated_header_footer
from .headings import candidate_headings


def extract_pdf(document: dict[str, Any]) -> tuple[list[dict], list[dict], dict[str, Any]]:
    try:
        import fitz  # type: ignore
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required for PDF extraction but is not installed.") from exc

    path: Path = document["path"]
    pages: list[dict] = []
    headings: list[dict] = []
    with fitz.open(path) as pdf:
        metadata = dict(pdf.metadata or {})
        for index, page in enumerate(pdf, start=1):
            text = page.get_text("text") or ""
            words = text.split()
            images = page.get_images(full=True)
            quality, possible_scan = classify_page_quality(len(text), len(words), len(images))
            blocks = page.get_text("blocks") or []
            possible_table = sum(1 for line in text.splitlines() if "\t" in line or "  " in line) >= 3
            record = {
                "document_id": document["document_id"],
                "filename": document["filename"],
                "page_number": index,
                "text": text,
                "character_count": len(text),
                "word_count": len(words),
                "has_text": bool(text.strip()),
                "text_quality": quality,
                "possible_scanned_page": possible_scan,
                "extraction_method": "PyMuPDF_NATIVE_TEXT",
                "source_relative_path": document["relative_path"],
                "has_images": len(images) > 0,
                "image_count": len(images),
                "possible_table": possible_table,
                "possible_figure": len(images) > 0 or len(blocks) > 8,
                "likely_header": None,
                "likely_footer": None,
            }
            pages.append(record)
            headings.extend(candidate_headings(document["document_id"], index, text))
    headers, footers = repeated_header_footer(pages)
    for page in pages:
        page["likely_header"] = headers.get(page["page_number"])
        page["likely_footer"] = footers.get(page["page_number"])
    return pages, headings, {"page_count": len(pages), "pdf_metadata": metadata}


def extract_text_document(document: dict[str, Any]) -> tuple[list[dict], list[dict], dict[str, Any]]:
    path: Path = document["path"]
    text = path.read_text(encoding="utf-8", errors="replace")
    words = text.split()
    quality, possible_scan = classify_page_quality(len(text), len(words), 0)
    page = {
        "document_id": document["document_id"],
        "filename": document["filename"],
        "page_number": 1,
        "text": text,
        "character_count": len(text),
        "word_count": len(words),
        "has_text": bool(text.strip()),
        "text_quality": quality,
        "possible_scanned_page": possible_scan,
        "extraction_method": "PLAIN_TEXT",
        "source_relative_path": document["relative_path"],
        "has_images": False,
        "image_count": 0,
        "possible_table": False,
        "possible_figure": False,
        "likely_header": None,
        "likely_footer": None,
    }
    return [page], candidate_headings(document["document_id"], 1, text), {"page_count": 1, "pdf_metadata": {}}


def extract_document(document: dict[str, Any]) -> tuple[list[dict], list[dict], dict[str, Any]]:
    suffix = Path(document["filename"]).suffix.lower()
    if suffix == ".pdf":
        return extract_pdf(document)
    if suffix in {".txt", ".md"}:
        return extract_text_document(document)
    raise RuntimeError(f"Unsupported extraction format for STEP 03: {suffix}")

