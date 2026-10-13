from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from app.core.config import get_settings, resolve_sqlite_path

DEFAULT_DATABASE_FILENAME = "manufacturaiq.db"
DEFAULT_BUSY_TIMEOUT_MS = 5000
DEFAULT_JOURNAL_MODE = "WAL"

PRAGMA_FOREIGN_KEYS = "PRAGMA foreign_keys = ON"
PRAGMA_BUSY_TIMEOUT = f"PRAGMA busy_timeout = {DEFAULT_BUSY_TIMEOUT_MS}"
PRAGMA_JOURNAL_MODE_WAL = "PRAGMA journal_mode = WAL"


def resolve_database_path(database_url: str | None = None) -> Path:
    """Resolve the SQLite database file path from configuration."""

    settings = get_settings()
    if database_url is None:
        return settings.database_path
    return resolve_sqlite_path(database_url, default_path=settings.default_database_path)


class DatabaseConnection:
    """Small async connection manager for the operational SQLite database.

    Each connection enables ``foreign_keys``, sets ``row_factory`` and applies
    a busy timeout.  WAL journal mode is enabled for on-disk databases so
    concurrent readers do not block writers during development/runtime.
    """

    def __init__(
        self,
        database_path: str | Path | None = None,
        *,
        busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
        journal_mode: str | None = DEFAULT_JOURNAL_MODE,
    ) -> None:
        self.database_path = (
            Path(database_path) if database_path is not None else resolve_database_path()
        )
        self.busy_timeout_ms = busy_timeout_ms
        self.journal_mode = journal_mode

    @property
    def is_memory(self) -> bool:
        return str(self.database_path) in {":memory:", ""} or str(self.database_path).startswith(
            "file::memory:"
        )

    async def connect(self) -> aiosqlite.Connection:
        """Open a configured aiosqlite connection (caller closes it)."""

        if not self.is_memory:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = await aiosqlite.connect(str(self.database_path))
        connection.row_factory = sqlite3.Row
        await connection.execute(PRAGMA_FOREIGN_KEYS)
        await connection.execute(f"PRAGMA busy_timeout = {int(self.busy_timeout_ms)}")
        if self.journal_mode and not self.is_memory:
            await connection.execute(f"PRAGMA journal_mode = {self.journal_mode}")
        return connection

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[aiosqlite.Connection]:
        """Yield a connection that is always closed on exit."""

        connection = await self.connect()
        try:
            yield connection
        finally:
            await connection.close()

    async def fetch_all(self, sql: str, parameters: tuple | list = ()) -> list[sqlite3.Row]:
        async with self.connection() as connection:
            cursor = await connection.execute(sql, parameters)
            try:
                return list(await cursor.fetchall())
            finally:
                await cursor.close()

    async def fetch_one(self, sql: str, parameters: tuple | list = ()) -> sqlite3.Row | None:
        rows = await self.fetch_all(sql, parameters)
        return rows[0] if rows else None
