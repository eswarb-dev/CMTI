from __future__ import annotations

import hashlib
import shutil
import sqlite3
from pathlib import Path

import pyarrow.parquet as parquet
import pytest

from app.core.exceptions import DatabaseInitializationError
from app.db.initializer import initialize_database
from app.db.schema import (
    DATABASE_SCHEMA_VERSION,
    EXPECTED_SOURCE_COLUMNS,
    INDEX_NAMES,
    METADATA_TABLE,
    TABLE_ORDER,
)


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path))
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _content_digest(path: Path) -> str:
    """Hash every row (metadata excluded timestamp) for determinism checks."""

    connection = _connect(path)
    try:
        digest = hashlib.sha256()
        for table in TABLE_ORDER:
            rows = connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
            digest.update(table.encode())
            digest.update(repr(rows).encode())
        metadata = connection.execute(
            f"""
            SELECT schema_version, dataset_source, generator_version, source_manifest_hash
            FROM {METADATA_TABLE} WHERE id = 1
            """
        ).fetchone()
        digest.update(repr(metadata).encode())
        return digest.hexdigest()
    finally:
        connection.close()


def test_initializer_imports_all_demo_tables(
    initialized_database: Path, source_row_counts: dict[str, int]
) -> None:
    connection = _connect(initialized_database)
    try:
        for table in TABLE_ORDER:
            row = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            assert row[0] == source_row_counts[table], table
    finally:
        connection.close()


def test_imported_row_counts_match_source_parquet(
    initialized_database: Path, source_row_counts: dict[str, int]
) -> None:
    expected = {
        "machines": 3,
        "products": 3,
        "production_orders": 180,
        "quality_inspections": 900,
        "telemetry": 38379,
        "maintenance_logs": 75,
        "machine_alarms": 51,
    }
    for table, count in expected.items():
        assert source_row_counts[table] == count, f"source dataset changed for {table}"
    connection = _connect(initialized_database)
    try:
        for table, count in expected.items():
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == count
    finally:
        connection.close()


def test_foreign_key_check_is_clean(initialized_database: Path) -> None:
    connection = _connect(initialized_database)
    try:
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        assert violations == []
    finally:
        connection.close()


def test_database_metadata_exists(initialized_database: Path) -> None:
    connection = _connect(initialized_database)
    try:
        row = connection.execute(
            f"SELECT schema_version, dataset_source, generator_version, imported_at, "
            f"source_manifest_hash FROM {METADATA_TABLE} WHERE id = 1"
        ).fetchone()
        assert row is not None
        assert row[0] == DATABASE_SCHEMA_VERSION
        assert row[1] == "manufacturaiq_demo_factory"
        assert row[2] == "demo_factory.step02.v1"
        assert row[3]
        assert row[4] and len(row[4]) == 64
    finally:
        connection.close()


def test_only_demo_factory_data_is_present(initialized_database: Path) -> None:
    connection = _connect(initialized_database)
    try:
        for table in TABLE_ORDER:
            sources = {
                row[0]
                for row in connection.execute(f"SELECT DISTINCT source_dataset FROM {table}")
            }
            assert sources == {"manufacturaiq_demo_factory"}, (table, sources)
        machine_ids = {
            row[0] for row in connection.execute("SELECT machine_id FROM machines")
        }
        assert machine_ids == {"CNC-01", "CNC-03", "CNC-05"}
    finally:
        connection.close()


def test_indexes_exist(initialized_database: Path) -> None:
    connection = _connect(initialized_database)
    try:
        present = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
        }
        for index_name in INDEX_NAMES:
            assert index_name in present
    finally:
        connection.close()


def test_initialization_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first.db"
    second = tmp_path / "second.db"
    initialize_database(first)
    initialize_database(second)
    assert _content_digest(first) == _content_digest(second)


def test_failed_initialization_preserves_valid_database(tmp_path: Path) -> None:
    target = tmp_path / "manufacturaiq.db"
    initialize_database(target)
    before = target.read_bytes()
    digest_before = _content_digest(target)

    missing_source = tmp_path / "missing_source"
    with pytest.raises(DatabaseInitializationError):
        initialize_database(target, missing_source)
    assert target.read_bytes() == before

    broken_source = tmp_path / "broken_source"
    _build_broken_quality_source(broken_source)
    with pytest.raises(DatabaseInitializationError):
        initialize_database(target, broken_source)
    assert target.read_bytes() == before
    assert _content_digest(target) == digest_before
    assert not Path(f"{target}.tmp").exists()


def test_external_dataset_directory_is_refused(tmp_path: Path) -> None:
    from app.core.config import get_settings

    target = tmp_path / "manufacturaiq.db"
    external_root = Path(get_settings().external_data_root)
    with pytest.raises(DatabaseInitializationError):
        initialize_database(target, external_root)
    assert not target.exists()


def test_schema_drift_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "manufacturaiq.db"
    source = tmp_path / "drifted"
    source.mkdir()
    for table in TABLE_ORDER:
        table_path = Path(get_settings_demo_dir()) / f"{table}.parquet"
        shutil.copy(table_path, source / f"{table}.parquet")
    machines = parquet.read_table(source / "machines.parquet").drop_columns(["criticality"])
    parquet.write_table(machines, source / "machines.parquet")
    with pytest.raises(DatabaseInitializationError):
        initialize_database(target, source)
    assert not target.exists()


def get_settings_demo_dir() -> Path:
    from app.core.config import get_settings

    return Path(get_settings().demo_factory_root)


def _build_broken_quality_source(destination: Path) -> None:
    """Copy the demo factory but break one quality PASS/FAIL invariant."""

    from app.core.config import get_settings

    demo_dir = Path(get_settings().demo_factory_root)
    destination.mkdir(parents=True)
    for table in TABLE_ORDER:
        shutil.copy(demo_dir / f"{table}.parquet", destination / f"{table}.parquet")
    quality = parquet.read_table(destination / "quality_inspections.parquet")
    index = 0
    row = quality.slice(index, 1).to_pylist()[0]
    assert row["result"] == "PASS"
    row["measured_value"] = float(row["usl"]) + 1000.0
    broken = quality.slice(1).to_pylist()
    broken.insert(0, row)
    columns = list(quality.column_names)
    import pyarrow as pa

    parquet.write_table(pa.Table.from_pylist(broken, schema=quality.schema), destination / "quality_inspections.parquet")
    assert EXPECTED_SOURCE_COLUMNS["quality_inspections"] == tuple(columns)
