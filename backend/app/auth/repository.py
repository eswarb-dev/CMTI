from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from uuid import uuid4

from app.auth.models import AuthUser


class DuplicateUsernameError(ValueError):
    pass


class LocalAuthRepository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = threading.RLock()
        self._connection: sqlite3.Connection | None = None

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            conn = self._connect()
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    username_normalized TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                )
                """
            )
            conn.commit()

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def create_user(
        self,
        *,
        username: str,
        display_name: str,
        role: str,
        password_hash: str,
        is_active: bool = True,
    ) -> AuthUser:
        normalized = normalize_username(username)
        if not normalized:
            raise ValueError("username must not be empty")
        display = display_name.strip()
        if not display:
            raise ValueError("display name must not be empty")
        user_role = role.strip()
        if not user_role:
            raise ValueError("role must not be empty")

        user_id = str(uuid4())
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO users (
                        id, username, username_normalized, display_name, role,
                        password_hash, is_active
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        username.strip(),
                        normalized,
                        display,
                        user_role,
                        password_hash,
                        1 if is_active else 0,
                    ),
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                raise DuplicateUsernameError("username already exists") from exc
        user = self.get_user_by_id(user_id)
        if user is None:
            raise RuntimeError("created user could not be reloaded")
        return user

    def get_user_by_username(self, username: str) -> AuthUser | None:
        normalized = normalize_username(username)
        if not normalized:
            return None
        return self._fetch_one(
            "SELECT * FROM users WHERE username_normalized = ?",
            (normalized,),
        )

    def get_user_by_id(self, user_id: str) -> AuthUser | None:
        return self._fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))

    def set_user_active(self, username: str, is_active: bool) -> None:
        with self._lock:
            self._connect().execute(
                """
                UPDATE users
                SET is_active = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE username_normalized = ?
                """,
                (1 if is_active else 0, normalize_username(username)),
            )
            self._connect().commit()

    def _fetch_one(self, sql: str, params: tuple[object, ...]) -> AuthUser | None:
        with self._lock:
            row = self._connect().execute(sql, params).fetchone()
        return row_to_user(row) if row is not None else None

    def _connect(self) -> sqlite3.Connection:
        if self._connection is None:
            self._connection = sqlite3.connect(self.db_path, check_same_thread=False)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA journal_mode = WAL")
        return self._connection


def normalize_username(username: str) -> str:
    return username.strip().casefold()


def row_to_user(row: sqlite3.Row) -> AuthUser:
    return AuthUser(
        id=str(row["id"]),
        username=str(row["username"]),
        display_name=str(row["display_name"]),
        role=str(row["role"]),
        password_hash=str(row["password_hash"]),
        is_active=bool(row["is_active"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )
