"""PDF validation: declared type AND actual signature/parseability."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PDF_MAGIC = b"%PDF-"

ERROR_NOT_PDF = "NOT_A_PDF"
ERROR_MALFORMED = "MALFORMED_PDF"
ERROR_ENCRYPTED = "ENCRYPTED_PDF"
ERROR_NO_PAGES = "NO_PAGES"
ERROR_NO_TEXT = "NO_EXTRACTABLE_TEXT"


@dataclass(slots=True)
class PdfValidation:
    ok: bool
    error_code: str | None = None
    error_message: str | None = None
    page_count: int = 0


def validate_pdf(path: Path, *, declared_mime: str | None = None) -> PdfValidation:
    """Accept only genuinely parseable PDFs (never trust names/headers alone)."""

    try:
        with open(path, "rb") as handle:
            header = handle.read(8)
    except OSError as exc:
        return PdfValidation(ok=False, error_code=ERROR_MALFORMED,
                             error_message=f"cannot read upload: {exc}")
    if not header.startswith(PDF_MAGIC):
        return PdfValidation(ok=False, error_code=ERROR_NOT_PDF,
                             error_message="file signature is not PDF")
    try:
        import fitz
    except ImportError as exc:
        return PdfValidation(ok=False, error_code=ERROR_MALFORMED,
                             error_message=f"PDF parser unavailable: {exc}")
    try:
        with fitz.open(path) as document:
            if bool(getattr(document, "is_encrypted", False)) or bool(
                getattr(document, "needs_pass", False)
            ):
                return PdfValidation(ok=False, error_code=ERROR_ENCRYPTED,
                                     error_message="password-protected PDFs are not supported")
            page_count = int(document.page_count)
    except Exception as exc:
        return PdfValidation(ok=False, error_code=ERROR_MALFORMED,
                             error_message=f"PDF cannot be parsed: {type(exc).__name__}")
    if page_count < 1:
        return PdfValidation(ok=False, error_code=ERROR_NO_PAGES,
                             error_message="PDF contains no pages")
    _ = declared_mime  # declared type is informational only; signature governs
    return PdfValidation(ok=True, page_count=page_count)


def extract_pages(path: Path) -> list[tuple[int, str]]:
    """Extract (1-based page_number, text) mirroring the frozen corpus convention."""

    import fitz

    pages: list[tuple[int, str]] = []
    with fitz.open(path) as document:
        for index, page in enumerate(document, start=1):
            pages.append((index, page.get_text("text") or ""))
    return pages
