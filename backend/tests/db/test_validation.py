from __future__ import annotations

import sqlite3
from pathlib import Path

from app.db.schema import (
    DATABASE_SCHEMA_VERSION,
    INDEX_NAMES,
    METADATA_TABLE,
    TABLE_ORDER,
    create_schema,
)
from app.db.validation import (
    check_maintenance_time_invariant,
    check_production_invariant,
    check_quality_invariant,
    validate_database,
)


def test_validate_database_reports_valid(
    initialized_database: Path, source_row_counts: dict[str, int]
) -> None:
    report = validate_database(initialized_database, expected_row_counts=source_row_counts)
    assert report.is_valid, report.to_dict()
    assert report.schema_version == DATABASE_SCHEMA_VERSION
    assert report.foreign_key_violations == []
    assert report.missing_indexes == []
    assert report.invariant_failures == []
    assert report.row_count_matches
    for table in TABLE_ORDER:
        assert report.row_counts[table] == source_row_counts[table]
    text = report.format_text()
    assert "VALID" in text
    assert str(initialized_database) in text


def test_validation_fails_for_missing_database(tmp_path: Path) -> None:
    report = validate_database(tmp_path / "absent.db")
    assert not report.is_valid
    assert report.invariant_failures


def test_production_invariant_detector(tmp_path: Path) -> None:
    connection = sqlite3.connect(":memory:")
    try:
        create_schema(connection)
        connection.execute(
            "INSERT INTO machines (machine_id, is_synthetic, source_dataset) VALUES ('M1', 1, 'x')"
        )
        connection.execute(
            "INSERT INTO products (product_id, is_synthetic, source_dataset) VALUES ('P1', 1, 'x')"
        )
        connection.execute(
            """
            INSERT INTO production_orders (
                production_id, batch_id, machine_id, product_id,
                planned_quantity, actual_quantity, accepted_quantity, rejected_quantity,
                is_synthetic, source_dataset
            ) VALUES ('PROD-1', 'B-1', 'M1', 'P1', 10, 10, 9, 2, 1, 'x')
            """
        )
        failures = check_production_invariant(connection)
        assert failures and "PROD-1" in failures[0]
    finally:
        connection.close()


def test_quality_invariant_detector(tmp_path: Path) -> None:
    connection = sqlite3.connect(":memory:")
    try:
        create_schema(connection)
        connection.execute(
            "INSERT INTO machines (machine_id, is_synthetic, source_dataset) VALUES ('M1', 1, 'x')"
        )
        connection.execute(
            "INSERT INTO products (product_id, is_synthetic, source_dataset) VALUES ('P1', 1, 'x')"
        )
        connection.execute(
            """
            INSERT INTO production_orders (
                production_id, batch_id, machine_id, product_id,
                is_synthetic, source_dataset
            ) VALUES ('PROD-1', 'B-1', 'M1', 'P1', 1, 'x')
            """
        )
        connection.execute(
            """
            INSERT INTO quality_inspections (
                inspection_id, batch_id, machine_id, product_id, timestamp,
                lsl, usl, measured_value, result, is_synthetic, source_dataset
            ) VALUES ('QI-1', 'B-1', 'M1', 'P1', '2026-09-01T08:00:00+05:30',
                      1.0, 2.0, 1.5, 'FAIL', 1, 'x')
            """
        )
        failures = check_quality_invariant(connection)
        assert failures and "QI-1" in failures[0]
    finally:
        connection.close()


def test_maintenance_time_invariant_detector() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        create_schema(connection)
        connection.execute(
            "INSERT INTO machines (machine_id, is_synthetic, source_dataset) VALUES ('M1', 1, 'x')"
        )
        connection.execute(
            """
            INSERT INTO maintenance_logs (
                maintenance_id, machine_id, created_at, started_at, completed_at,
                is_synthetic, source_dataset
            ) VALUES (
                'MNT-1', 'M1',
                '2026-09-01T10:00:00+05:30',
                '2026-09-01T09:00:00+05:30',
                '2026-09-01T08:00:00+05:30',
                1, 'x')
            """
        )
        failures = check_maintenance_time_invariant(connection)
        assert failures and "MNT-1" in failures[0]
    finally:
        connection.close()


def test_all_expected_indexes_present(initialized_database: Path) -> None:
    report = validate_database(initialized_database)
    assert report.missing_indexes == []
    assert set(INDEX_NAMES) and set(report.missing_indexes).isdisjoint(set(INDEX_NAMES))


def test_metadata_table_queryable(initialized_database: Path) -> None:
    report = validate_database(initialized_database)
    assert report.schema_version == DATABASE_SCHEMA_VERSION
    assert METADATA_TABLE  # metadata table name is stable
