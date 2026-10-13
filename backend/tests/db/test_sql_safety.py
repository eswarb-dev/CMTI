from __future__ import annotations

import pytest

from app.core.exceptions import SqlSafetyError
from app.db.sql_safety import is_readonly_query, validate_readonly_query

ACCEPTED_QUERIES = [
    "SELECT * FROM machines",
    "SELECT machine_id FROM machines WHERE machine_id = ?",
    "WITH x AS (SELECT 1) SELECT * FROM machines",
    "WITH recent AS (SELECT * FROM telemetry ORDER BY timestamp DESC LIMIT 10) "
    "SELECT machine_id FROM recent",
    "select count(*) from production_orders where actual_start_time >= ?",
    "SELECT * FROM machines WHERE machine_name = 'DROP TABLE machines'",
    "SELECT CASE WHEN criticality = 'HIGH' THEN 1 ELSE 0 END FROM machines",
    "  SELECT machine_id FROM machines;  ",
]

REJECTED_QUERIES = [
    "SELECT * FROM machines; DROP TABLE machines",
    "SELECT * FROM machines; SELECT 1",
    "DELETE FROM machines",
    "UPDATE machines SET status = 'DOWN'",
    "INSERT INTO machines (machine_id) VALUES ('X')",
    "DROP TABLE machines",
    "ALTER TABLE machines ADD COLUMN hack TEXT",
    "CREATE TABLE hack (a INT)",
    "REPLACE INTO machines VALUES ('X')",
    "ATTACH DATABASE 'evil.db' AS evil",
    "DETACH DATABASE evil",
    "VACUUM",
    "REINDEX",
    "ANALYZE",
    "PRAGMA writable_schema = 1",
    "PRAGMA foreign_keys = OFF",
    "BEGIN",
    "COMMIT",
    "ROLLBACK",
    "WITH x AS (SELECT 1) DELETE FROM machines",
    "SELECT * FROM machines -- comment",
    "SELECT * FROM machines /* comment */",
    "",
    "   ",
]


@pytest.mark.parametrize("query", ACCEPTED_QUERIES)
def test_readonly_queries_are_accepted(query: str) -> None:
    assert validate_readonly_query(query) == query.strip()
    assert is_readonly_query(query) is True


@pytest.mark.parametrize("query", REJECTED_QUERIES)
def test_unsafe_queries_are_rejected(query: str) -> None:
    with pytest.raises(SqlSafetyError):
        validate_readonly_query(query)
    assert is_readonly_query(query) is False


def test_rejection_of_multiple_statements_with_semicolon() -> None:
    with pytest.raises(SqlSafetyError):
        validate_readonly_query("SELECT 1; DROP TABLE machines")
    with pytest.raises(SqlSafetyError):
        validate_readonly_query("SELECT 1; SELECT 2;")


def test_single_statement_with_trailing_semicolon_is_accepted() -> None:
    assert validate_readonly_query("SELECT 1;") == "SELECT 1;"


def test_comment_smuggling_is_rejected() -> None:
    with pytest.raises(SqlSafetyError):
        validate_readonly_query("SELECT * FROM machines WHERE 1 = 1 -- ; DROP TABLE machines")
    with pytest.raises(SqlSafetyError):
        validate_readonly_query("SELECT * FROM machines;--\nDROP TABLE machines")


def test_non_string_input_is_rejected() -> None:
    with pytest.raises(SqlSafetyError):
        validate_readonly_query(None)  # type: ignore[arg-type]


def test_no_generic_sql_executor_exists() -> None:
    from pathlib import Path

    app_root = Path(__file__).resolve().parents[2] / "app"
    offenders: list[str] = []
    for path in app_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "def execute_sql" in text:
            offenders.append(str(path))
    assert offenders == []
