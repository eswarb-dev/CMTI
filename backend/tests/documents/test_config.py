from __future__ import annotations

import pytest

from app.core.config import Settings


def _hermetic(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_document_defaults(tmp_path) -> None:
    settings = _hermetic(document_storage_path=str(tmp_path / "docstore"))
    assert settings.document_upload_enabled is True
    assert settings.document_max_upload_mb == 50
    assert settings.document_dynamic_collection == "manufacturaiq_dynamic_documents"
    assert settings.document_ingest_batch_size == 32
    assert settings.document_storage_root == tmp_path / "docstore"


def test_default_storage_root_under_project() -> None:
    settings = _hermetic()
    assert settings.document_storage_root == settings.project_root / "data" / "documents"


def test_blank_storage_path_falls_back() -> None:
    settings = _hermetic(document_storage_path="   ")
    assert settings.document_storage_root == settings.project_root / "data" / "documents"


def test_invalid_limits_rejected() -> None:
    with pytest.raises(Exception):
        _hermetic(document_max_upload_mb=0)
    with pytest.raises(Exception):
        _hermetic(document_ingest_batch_size=-1)
    with pytest.raises(Exception):
        _hermetic(document_dynamic_collection="  ")


def test_environment_overrides(monkeypatch) -> None:
    monkeypatch.setenv("DOCUMENT_MAX_UPLOAD_MB", "25")
    monkeypatch.setenv("DOCUMENT_DYNAMIC_COLLECTION", "custom_dynamic")
    monkeypatch.setenv("DOCUMENT_UPLOAD_ENABLED", "false")
    settings = _hermetic()
    assert settings.document_max_upload_mb == 25
    assert settings.document_dynamic_collection == "custom_dynamic"
    assert settings.document_upload_enabled is False


def test_no_secret_dependency(monkeypatch) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    settings = _hermetic(document_storage_path="/tmp/docstore")
    assert settings.document_dynamic_collection
    assert settings.document_storage_root is not None
