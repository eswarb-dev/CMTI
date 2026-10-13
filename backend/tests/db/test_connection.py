from __future__ import annotations

from pathlib import Path

import pytest

from app.db.connection import DatabaseConnection, resolve_database_path


def test_resolve_database_path_defaults_to_backend_data(tmp_path: Path, monkeypatch) -> None:
    from app.core.config import Settings

    settings = Settings(database_url=None)
    assert settings.database_path == settings.project_root / "backend" / "data" / "manufacturaiq.db"
    assert resolve_database_path("") == settings.default_database_path
    assert resolve_database_path(None) == settings.default_database_path
    custom = resolve_database_path(f"sqlite:///{tmp_path / 'custom.db'}")
    assert custom == tmp_path / "custom.db"


def test_resolve_sqlite_url_forms(tmp_path: Path) -> None:
    from app.core.config import resolve_sqlite_path

    default = tmp_path / "default.db"
    assert resolve_sqlite_path("sqlite:///relative.db", default_path=default) == Path("relative.db")
    assert resolve_sqlite_path(str(tmp_path / "plain.db"), default_path=default) == tmp_path / "plain.db"
    assert resolve_sqlite_path("   ", default_path=default) == default


async def test_connection_enables_foreign_keys_and_row_factory(
    initialized_database: Path,
) -> None:
    database = DatabaseConnection(initialized_database)
    async with database.connection() as connection:
        cursor = await connection.execute("PRAGMA foreign_keys")
        row = await cursor.fetchone()
        assert row[0] == 1
        assert connection.row_factory is not None
        cursor = await connection.execute("SELECT machine_id FROM machines ORDER BY machine_id")
        rows = await cursor.fetchall()
        assert rows[0][0] == "CNC-01"


async def test_connection_closes_cleanly(initialized_database: Path) -> None:
    database = DatabaseConnection(initialized_database)
    async with database.connection() as connection:
        assert connection is not None
    rows = await database.fetch_all("SELECT COUNT(*) AS c FROM machines")
    assert rows[0]["c"] == 3
