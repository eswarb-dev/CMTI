"""Post-import validation and operational health report for SQLite database."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.core.exceptions import DatabaseValidationError
from app.db.connection import resolve_database_path
from app.db.schema import (
    DATABASE_SCHEMA_VERSION,
    DATA_TABLES,
    INDEX_NAMES,
    METADATA_TABLE,
)


@dataclass(slots=True)
class ValidationReport:
    """Structured outcome of a database validation pass."""

    database_path: str
    schema_version: str | None = None
    row_counts: dict[str, int] = field(default_factory=dict)
    expected_row_counts: dict[str, int] = field(default_factory=dict)
    foreign_key_violations: list[str] = field(default_factory=list)
    missing_indexes: list[str] = field(default_factory=list)
    invariant_failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def row_count_matches(self) -> bool:
        if not self.expected_row_counts:
            return True
        return all(
            self.row_counts.get(table) == expected
            for table, expected in self.expected_row_counts.items()
        )

    @property
    def is_valid(self) -> bool:
        return (
            bool(self.row_counts)
            and self.row_count_matches
            and not self.foreign_key_violations
            and not self.missing_indexes
            and not self.invariant_failures
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "database_path": self.database_path,
            "schema_version": self.schema_version,
            "row_counts": dict(self.row_counts),
            "expected_row_counts": dict(self.expected_row_counts),
            "row_counts_match": self.row_count_matches,
            "foreign_key_violations": list(self.foreign_key_violations),
            "missing_indexes": list(self.missing_indexes),
            "invariant_failures": list(self.invariant_failures),
            "warnings": list(self.warnings),
            "is_valid": self.is_valid,
        }

    def format_text(self) -> str:
        lines = [
            f"database path      : {self.database_path}",
            f"schema version     : {self.schema_version}",
            "row counts         :",
        ]
        for table in DATA_TABLES:
            expected = self.expected_row_counts.get(table)
            suffix = f" (expected {expected})" if expected is not None else ""
            lines.append(f"  {table:<22} {self.row_counts.get(table, 0)}{suffix}")
        lines.append(
            "row counts match   : " + ("PASS" if self.row_count_matches else "FAIL")
        )
        lines.append(
            "foreign keys       : "
            + ("PASS" if not self.foreign_key_violations else "FAIL")
        )
        lines.append(
            "indexes            : "
            + ("PASS" if not self.missing_indexes else f"FAIL {self.missing_indexes}")
        )
        lines.append(
            "invariants         : "
            + ("PASS" if not self.invariant_failures else "FAIL")
        )
        for failure in self.invariant_failures:
            lines.append(f"  ! {failure}")
        for warning in self.warnings:
            lines.append(f"  ? {warning}")
        lines.append("overall            : " + ("VALID" if self.is_valid else "INVALID"))
        return "\n".join(lines)


def read_schema_version(connection: sqlite3.Connection) -> str | None:
    try:
        row = connection.execute(
            f"SELECT schema_version FROM {METADATA_TABLE} WHERE id = 1"
        ).fetchone()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def count_rows(connection: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in DATA_TABLES:
        row = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        counts[table] = int(row[0])
    return counts


def foreign_key_violations(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute("PRAGMA foreign_key_check").fetchall()
    violations: list[str] = []
    for row in rows:
        table, rowid, parent, fkid = row[0], row[1], row[2], row[3]
        violations.append(f"{table}(rowid={rowid}) -> {parent} (fk #{fkid})")
    return violations


def missing_indexes(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index'"
    ).fetchall()
    present = {row[0] for row in rows}
    return [name for name in INDEX_NAMES if name not in present]


def check_production_invariant(connection: sqlite3.Connection) -> list[str]:
    """``accepted_quantity + rejected_quantity == actual_quantity``."""

    rows = connection.execute(
        """
        SELECT production_id, accepted_quantity, rejected_quantity, actual_quantity
        FROM production_orders
        WHERE accepted_quantity IS NOT NULL
          AND rejected_quantity IS NOT NULL
          AND actual_quantity IS NOT NULL
          AND accepted_quantity + rejected_quantity <> actual_quantity
        """
    ).fetchall()
    return [f"production_orders {row[0]}: accepted+rejected != actual" for row in rows]


def check_quality_invariant(connection: sqlite3.Connection) -> list[str]:
    """``result == PASS`` iff ``lsl <= measured_value <= usl``."""

    rows = connection.execute(
        """
        SELECT inspection_id, lsl, usl, measured_value, result
        FROM quality_inspections
        WHERE lsl IS NOT NULL
          AND usl IS NOT NULL
          AND measured_value IS NOT NULL
          AND result IS NOT NULL
        """
    ).fetchall()
    failures: list[str] = []
    for inspection_id, lsl, usl, measured, result in rows:
        within = lsl <= measured <= usl
        expected = "PASS" if within else "FAIL"
        if result.upper() != expected:
            failures.append(
                f"quality_inspections {inspection_id}: result={result} "
                f"but measurement is {'within' if within else 'outside'} [{lsl}, {usl}]"
            )
    return failures


def check_maintenance_time_invariant(connection: sqlite3.Connection) -> list[str]:
    """``created_at <= started_at <= completed_at`` when all are present."""

    rows = connection.execute(
        """
        SELECT maintenance_id, created_at, started_at, completed_at
        FROM maintenance_logs
        WHERE created_at IS NOT NULL
          AND started_at IS NOT NULL
          AND completed_at IS NOT NULL
        """
    ).fetchall()
    failures: list[str] = []
    for maintenance_id, created_at, started_at, completed_at in rows:
        if not (created_at <= started_at <= completed_at):
            failures.append(
                f"maintenance_logs {maintenance_id}: "
                f"created_at <= started_at <= completed_at violated"
            )
    return failures


def check_alarm_acknowledgement(connection: sqlite3.Connection) -> list[str]:
    """Report acknowledgement anomalies instead of repairing them."""

    anomalies: list[str] = []
    rows = connection.execute(
        """
        SELECT alarm_id FROM machine_alarms
        WHERE acknowledged = 0 AND acknowledged_at IS NOT NULL
        """
    ).fetchall()
    anomalies.extend(
        f"machine_alarms {row[0]}: not acknowledged but acknowledged_at is set"
        for row in rows
    )
    rows = connection.execute(
        """
        SELECT alarm_id FROM machine_alarms
        WHERE acknowledged = 1 AND acknowledged_at IS NULL
        """
    ).fetchall()
    anomalies.extend(
        f"machine_alarms {row[0]}: acknowledged but acknowledged_at is null"
        for row in rows
    )
    return anomalies


def validate_connection(
    connection: sqlite3.Connection,
    database_path: str | Path,
    expected_row_counts: dict[str, int] | None = None,
) -> ValidationReport:
    """Run all validations and return a structured report."""

    report = ValidationReport(
        database_path=str(database_path),
        schema_version=read_schema_version(connection),
        expected_row_counts=dict(expected_row_counts or {}),
    )
    report.row_counts = count_rows(connection)
    report.foreign_key_violations = foreign_key_violations(connection)
    report.missing_indexes = missing_indexes(connection)

    if report.schema_version != DATABASE_SCHEMA_VERSION:
        report.invariant_failures.append(
            f"schema version {report.schema_version!r} != {DATABASE_SCHEMA_VERSION!r}"
        )
    for expected_table, expected in (expected_row_counts or {}).items():
        actual = report.row_counts.get(expected_table)
        if actual != expected:
            report.invariant_failures.append(
                f"{expected_table}: expected {expected} rows, found {actual}"
            )
    report.invariant_failures.extend(check_production_invariant(connection))
    report.invariant_failures.extend(check_quality_invariant(connection))
    report.invariant_failures.extend(check_maintenance_time_invariant(connection))
    report.warnings.extend(check_alarm_acknowledgement(connection))
    return report


def validate_database(
    database_path: str | Path | None = None,
    expected_row_counts: dict[str, int] | None = None,
) -> ValidationReport:
    """Open the operational database and validate it."""

    path = Path(database_path) if database_path is not None else resolve_database_path()
    if not path.exists():
        report = ValidationReport(database_path=str(path))
        report.invariant_failures.append("database file does not exist")
        return report
    connection = sqlite3.connect(str(path))
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        return validate_connection(connection, path, expected_row_counts)
    finally:
        connection.close()


def ensure_valid(
    database_path: str | Path | None = None,
    expected_row_counts: dict[str, int] | None = None,
) -> ValidationReport:
    """Validate and raise :class:`DatabaseValidationError` when invalid."""

    report = validate_database(database_path, expected_row_counts)
    if not report.is_valid:
        raise DatabaseValidationError(
            f"database validation failed for {report.database_path}: "
            f"{report.invariant_failures or report.foreign_key_violations or report.missing_indexes}"
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the ManufacturaIQ operational database")
    parser.add_argument("--database", default=None, help="Path to the SQLite database file")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    args = parser.parse_args(argv)

    report = validate_database(args.database)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(report.format_text())
    return 0 if report.is_valid else 1


if __name__ == "__main__":
    sys.exit(main())
