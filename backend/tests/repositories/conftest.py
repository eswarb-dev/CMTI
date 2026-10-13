from __future__ import annotations

from pathlib import Path

import pytest

from app.db.connection import DatabaseConnection
from app.db.initializer import initialize_database


@pytest.fixture(scope="session")
def repository_database_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One shared, fully initialized operational database for repository tests."""

    path = tmp_path_factory.mktemp("repositories") / "manufacturaiq.db"
    initialize_database(path)
    return path


@pytest.fixture
def database(repository_database_path: Path) -> DatabaseConnection:
    return DatabaseConnection(repository_database_path)
