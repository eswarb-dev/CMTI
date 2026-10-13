from __future__ import annotations

from pathlib import Path

from app.auth.repository import LocalAuthRepository
from app.core.config import Settings
from scripts.create_local_user import create_local_user


def test_create_local_user_core_logic(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setattr(
        "scripts.create_local_user.get_settings",
        lambda: Settings(project_root=tmp_path, auth_jwt_secret="test-secret"),
    )
    result = create_local_user(
        username="eswar",
        display_name="Eswar Balu",
        role="Manufacturing Engineer",
        password="private-pass",
        confirm_password="private-pass",
    )
    assert result == 0
    assert "private-pass" not in capsys.readouterr().out
    repo = LocalAuthRepository(tmp_path / "backend" / "data" / "auth.db")
    repo.initialize()
    assert repo.get_user_by_username("ESWAR") is not None
    repo.close()


def test_create_local_user_duplicate_and_confirmation_mismatch(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setattr(
        "scripts.create_local_user.get_settings",
        lambda: Settings(project_root=tmp_path, auth_jwt_secret="test-secret"),
    )
    assert create_local_user(
        username="eswar",
        display_name="Eswar Balu",
        role="Admin",
        password="private-pass",
        confirm_password="different",
    ) == 2
    assert "private-pass" not in capsys.readouterr().err
    assert create_local_user(
        username="eswar",
        display_name="Eswar Balu",
        role="Admin",
        password="private-pass",
        confirm_password="private-pass",
    ) == 0
    assert create_local_user(
        username="ESWAR",
        display_name="Eswar Balu",
        role="Admin",
        password="other-pass",
        confirm_password="other-pass",
    ) == 3
    assert "other-pass" not in capsys.readouterr().err
