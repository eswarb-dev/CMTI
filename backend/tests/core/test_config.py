from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import DEFAULT_GEMINI_MODEL, Settings
from app.core.logging import redact_mapping


def hermetic_settings(monkeypatch, **overrides) -> Settings:
    """Construct Settings isolated from developer-local .env and env keys."""

    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    return Settings(_env_file=None, **overrides)


def test_config_loads_without_api_credentials(monkeypatch) -> None:
    settings = hermetic_settings(monkeypatch)
    assert settings.typesafe_api_key is None
    assert settings.gemini_api_key is None
    assert settings.dataset_root == settings.project_root / "datasets"


def test_config_loads_test_environment_overrides(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("QDRANT_PATH", "D:/tmp/qdrant")
    settings = Settings(_env_file=None)
    assert settings.app_env == "test"
    assert settings.log_level == "DEBUG"
    assert settings.vector_store_path == Path("D:/tmp/qdrant")


def test_logging_redacts_secret_like_fields() -> None:
    redacted = redact_mapping({"api_key": "secret", "normal": "ok", "password": "truth"})
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["password"] == "[REDACTED]"
    assert redacted["normal"] == "ok"


def test_gemini_model_absent_resolves_canonical_default(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    settings = hermetic_settings(monkeypatch)
    assert settings.gemini_model == DEFAULT_GEMINI_MODEL


def test_gemini_model_empty_string_resolves_canonical_default(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_MODEL", "")
    settings = hermetic_settings(monkeypatch)
    assert settings.gemini_model == DEFAULT_GEMINI_MODEL


def test_gemini_model_whitespace_only_resolves_canonical_default(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_MODEL", "   ")
    settings = hermetic_settings(monkeypatch)
    assert settings.gemini_model == DEFAULT_GEMINI_MODEL


@pytest.mark.parametrize("model", ["gemini-2.5-pro", "custom-model-1"])
def test_gemini_model_explicit_value_preserved(monkeypatch, model: str) -> None:
    monkeypatch.setenv("GEMINI_MODEL", model)
    settings = hermetic_settings(monkeypatch)
    assert settings.gemini_model == model


def test_credential_absence_test_ignores_local_env_file(monkeypatch, tmp_path) -> None:
    """A developer-local .env with keys must not leak into the hermetic test."""

    dotenv = tmp_path / ".env"
    dotenv.write_text("TYPESAFE_API_KEY=local-dev-key\nGEMINI_API_KEY=local-dev-key\n", encoding="utf-8")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    settings = Settings(_env_file=None)
    assert settings.typesafe_api_key is None
    assert settings.gemini_api_key is None

