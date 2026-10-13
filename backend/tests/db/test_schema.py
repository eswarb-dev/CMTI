from __future__ import annotations

import sqlite3
from pathlib import Path

from app.db.schema import (
    DATABASE_SCHEMA_VERSION,
    EXPECTED_SOURCE_COLUMNS,
    INDEX_NAMES,
    METADATA_TABLE,
    TABLE_ORDER,
    create_schema,
)


def test_schema_version_constant() -> None:
    assert DATABASE_SCHEMA_VERSION == "1"


def test_schema_creation_creates_all_tables_and_indexes(tmp_path: Path) -> None:
    db_path = tmp_path / "schema_only.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        create_schema(connection)
        connection.commit()
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert set(TABLE_ORDER).issubset(names)
        assert METADATA_TABLE in names
        indexes = {
            row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
        }
        for index_name in INDEX_NAMES:
            assert index_name in indexes
        fk_rows = connection.execute("PRAGMA foreign_key_list(production_orders)").fetchall()
        referenced = {row[2] for row in fk_rows}
        assert {"machines", "products"}.issubset(referenced)
    finally:
        connection.close()


def test_schema_matches_actual_parquet_columns(demo_source_dir: Path) -> None:
    for table, expected in EXPECTED_SOURCE_COLUMNS.items():
        schema = parquet_schema(demo_source_dir / f"{table}.parquet")
        assert set(schema) == set(expected), f"schema drift for {table}"


def parquet_schema(path: Path) -> list[str]:
    import pyarrow.parquet as parquet

    return list(parquet.read_schema(path).names)
