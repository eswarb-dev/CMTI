from __future__ import annotations

import pytest

from app.documents.models import DocumentRecord, DocumentStatus


def _record(**overrides) -> DocumentRecord:
    fields: dict = {
        "document_id": "USR-ABCDEF123456",
        "original_filename": "manual.pdf",
        "stored_filename": "USR-ABCDEF123456.pdf",
        "sha256": "a" * 64,
        "mime_type": "application/pdf",
        "file_size_bytes": 100,
        "status": DocumentStatus.PENDING.value,
    }
    fields.update(overrides)
    return DocumentRecord(**fields)


def test_registry_initializes_idempotently(storage) -> None:
    from app.documents.registry import DocumentRegistry

    first = DocumentRegistry(storage.registry_dir / "documents.db")
    first.register(_record())
    first.close()
    second = DocumentRegistry(storage.registry_dir / "documents.db")
    try:
        assert second.find_by_id("USR-ABCDEF123456") is not None
        assert len(second.list_documents()) == 1
    finally:
        second.close()


def test_document_id_unique(registry) -> None:
    registry.register(_record())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(_record())


def test_sha256_unique(registry) -> None:
    registry.register(_record())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(_record(document_id="USR-000000000002"))


def test_duplicate_sha_returns_existing_document(registry) -> None:
    stored = registry.register(_record())
    found = registry.find_by_sha256("a" * 64)
    assert found is not None
    assert found.document_id == stored.document_id


def test_status_transitions_valid(registry) -> None:
    registry.register(_record())
    assert registry.mark_processing("USR-ABCDEF123456").status == "PROCESSING"
    ready = registry.mark_ready("USR-ABCDEF123456", page_count=3, chunk_count=5)
    assert ready.status == "READY"
    assert ready.page_count == 3
    assert ready.chunk_count == 5
    failed = registry.mark_failed("USR-ABCDEF123456", error_code="X", error_message="boom")
    assert failed.status == "FAILED"
    assert failed.error_code == "X"


def test_failed_document_stores_sanitized_error(registry) -> None:
    registry.register(_record())
    failed = registry.mark_failed("USR-ABCDEF123456", error_code="MALFORMED_PDF",
                                  error_message="bad\n\nfile   with   spaces " + "y" * 600)
    assert failed.error_message is not None
    assert "\n" not in failed.error_message
    assert len(failed.error_message) <= 500


def test_list_deterministic(registry) -> None:
    registry.register(_record(document_id="USR-000000000001", sha256="a" * 64))
    registry.register(_record(document_id="USR-000000000002", sha256="b" * 64))
    listed = registry.list_documents()
    assert [r.document_id for r in listed] == ["USR-000000000001", "USR-000000000002"]
    assert [r.document_id for r in registry.list_documents(status="PENDING")] == [
        "USR-000000000001", "USR-000000000002"]
    # Same-timestamp tiebreak is stable on document_id.
    assert [r.document_id for r in registry.list_documents()] == sorted(
        r.document_id for r in listed)


def test_registry_contains_no_secrets(registry, tmp_path) -> None:
    registry.register(_record())
    content = (tmp_path / "storage" / "registry" / "documents.db").read_bytes()
    assert b"GEMINI_API_KEY" not in content
    assert b"TYPESAFE_API_KEY" not in content
