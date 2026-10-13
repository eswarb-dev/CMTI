"""Shared helpers for operational database repositories."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime

from app.db.connection import DatabaseConnection

DEFAULT_LIMIT = 100
MAX_LIMIT = 5000


class BaseRepository:
    """Internal base class: owns the connection handle and SQL helpers.

    All caller-supplied values are bound as SQL parameters; column and table
    names are always compile-time constants from this codebase.
    """

    def __init__(self, database: DatabaseConnection | None = None) -> None:
        self._database = database if database is not None else DatabaseConnection()

    @property
    def database(self) -> DatabaseConnection:
        return self._database

    async def _fetch_all(self, sql: str, parameters: tuple = ()) -> list[sqlite3.Row]:
        return await self._database.fetch_all(sql, parameters)

    async def _fetch_one(self, sql: str, parameters: tuple = ()) -> sqlite3.Row | None:
        return await self._database.fetch_one(sql, parameters)

    @staticmethod
    def _bounded_limit(limit: int | None, default: int = DEFAULT_LIMIT, maximum: int = MAX_LIMIT) -> int:
        if limit is None:
            return default
        if limit < 1:
            return 1
        return min(int(limit), maximum)

    @staticmethod
    def _timestamp_text(value: datetime | date | str | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, datetime):
            return value.isoformat()
        return value.isoformat()

    @staticmethod
    def _time_range(
        column: str,
        start_time: datetime | date | str | None,
        end_time: datetime | date | str | None,
        parameters: list[object],
    ) -> str:
        """Append parameterized time-range predicates for ``column``."""

        clause = ""
        if start_time is not None:
            clause += f" AND {column} >= ?"
            parameters.append(BaseRepository._timestamp_text(start_time))
        if end_time is not None:
            clause += f" AND {column} <= ?"
            parameters.append(BaseRepository._timestamp_text(end_time))
        return clause

    @staticmethod
    def _optional_filter(column: str, value: object, parameters: list[object]) -> str:
        if value is None:
            return ""
        parameters.append(value)
        return f" AND {column} = ?"
