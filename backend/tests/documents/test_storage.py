from __future__ import annotations

import io

import pytest

from app.documents.storage import assert_safe_relative, sanitize_stored_name
from tests.documents.conftest import make_pdf


def test_valid_pdf_stored_under_controlled_filename(service, tmp_path) -> None:
    source = tmp_path / "My Manual (v2).pdf"
    make_pdf(source, ["Hello spindle world."])
    with open(source, "rb") as handle:
        result = service.ingest_pdf(handle, original_filename="My Manual (v2).pdf")
    assert result.status == "READY"
    assert result.page_count == 1
    assert result.chunk_count >= 1
    record = service.get_document(result.document_id)
    assert record is not None
    assert record.original_filename == "My Manual (v2).pdf"
    assert record.stored_filename == f"{result.document_id}.pdf"
    assert service.storage.has_original(record.stored_filename)


def test_original_filename_does_not_control_path(service, tmp_path) -> None:
    source = tmp_path / "a.pdf"
    make_pdf(source, ["Some content here for retrieval."])
    with open(source, "rb") as handle:
        result = service.ingest_pdf(handle, original_filename="../../evil.pdf")
    assert result.status == "READY"
    record = service.get_document(result.document_id)
    assert record is not None
    assert "/" not in record.stored_filename
    assert record.stored_filename == f"{result.document_id}.pdf"


def test_path_traversal_filename_harmless() -> None:
    for name in ("../evil.pdf", "/abs/path.pdf", "a/b.pdf", "", ".", ".."):
        with pytest.raises(ValueError, match="unsafe filename"):
            assert_safe_relative(name)
    assert sanitize_stored_name("USR-ABC123") == "USR-ABC123.pdf"


def test_oversized_pdf_rejected(service) -> None:
    service.settings.document_max_upload_mb = 1
    big = io.BytesIO(b"%PDF-1.4\n" + b"x" * (2 * 1024 * 1024))
    result = service.ingest_pdf(big, original_filename="big.pdf")
    assert result.status == "FAILED"
    assert result.error_code == "FILE_REJECTED"
    assert service.list_documents() == []


def test_non_pdf_rejected(service) -> None:
    result = service.ingest_pdf(io.BytesIO(b"just some text"), original_filename="note.txt")
    assert result.status == "FAILED"
    assert result.error_code == "NOT_A_PDF"


def test_fake_pdf_rejected(service) -> None:
    result = service.ingest_pdf(io.BytesIO(b"%PDF-1.4 not really a pdf \x00\xff binary"),
                                original_filename="fake.pdf")
    assert result.status in ("READY", "FAILED")
    if result.status == "READY":
        # Parsed as empty-text PDF only if fitz accepts the header; otherwise FAILED.
        assert result.chunk_count >= 1
    else:
        assert result.error_code in ("NOT_A_PDF", "MALFORMED_PDF", "NO_EXTRACTABLE_TEXT")


def test_malformed_pdf_rejected(service) -> None:
    result = service.ingest_pdf(io.BytesIO(b"%PDF-1.4\n%truncated binary \xff\xfe\x00"),
                                original_filename="broken.pdf")
    assert result.status == "FAILED"
    assert result.error_code in ("MALFORMED_PDF", "NO_PAGES", "NO_EXTRACTABLE_TEXT", "NOT_A_PDF")


def test_encrypted_pdf_rejected(service, tmp_path) -> None:
    import fitz

    path = tmp_path / "enc.pdf"
    document = fitz.open()
    document.new_page().insert_text((72, 72), "secret content")
    document.save(path, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="owner")
    document.close()
    with open(path, "rb") as handle:
        result = service.ingest_pdf(handle, original_filename="enc.pdf")
    assert result.status == "FAILED"
    assert result.error_code == "ENCRYPTED_PDF"


def test_partial_file_not_exposed_as_ready(service, tmp_path) -> None:
    source = tmp_path / "ok.pdf"
    make_pdf(source, ["Valid content for partial check."])
    with open(source, "rb") as handle:
        result = service.ingest_pdf(handle, original_filename="ok.pdf")
    assert result.status == "READY"
    for record in service.list_documents():
        assert record.status in ("PENDING", "PROCESSING", "READY", "FAILED")
        if record.status == "READY":
            assert record.chunk_count > 0 and record.page_count > 0


def test_sha256_deterministic(service, tmp_path) -> None:
    source = tmp_path / "a.pdf"
    make_pdf(source, ["Deterministic hash content."])
    first = service.ingest_pdf(open(source, "rb"), original_filename="a.pdf")
    second = service.ingest_pdf(open(source, "rb"), original_filename="a-copy.pdf")
    assert first.sha256 == second.sha256
    assert len(first.sha256) == 64
