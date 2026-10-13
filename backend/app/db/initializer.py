"""Deterministic import of the normalized demo factory into SQLite.

Canonical command (from ``backend``)::

    python -m app.db.initializer

The initializer builds a temporary database, validates it fully, and only then
atomically replaces the target file.  A failed run never clobbers an existing
valid database.  Only ``datasets/normalized/demo_factory`` may be imported;
external normalized datasets stay outside the operational database.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.core.config import get_settings
from app.core.exceptions import DatabaseInitializationError
from app.db.connection import PRAGMA_BUSY_TIMEOUT, PRAGMA_FOREIGN_KEYS, resolve_database_path
from app.db.schema import (
    DATABASE_SCHEMA_VERSION,
    DATA_TABLES,
    EXPECTED_SOURCE_COLUMNS,
    METADATA_TABLE,
    TABLE_ORDER,
    create_schema,
)
from app.db.validation import ValidationReport, validate_connection

logger = logging.getLogger("manufacturaiq.db.initializer")

TEMP_SUFFIX = ".tmp"

_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(slots=True)
class InitializationReport:
    """Outcome of a successful database initialization run."""

    database_path: str
    source_dir: str
    row_counts: dict[str, int] = field(default_factory=dict)
    source_row_counts: dict[str, int] = field(default_factory=dict)
    imported_at: str = ""
    dataset_source: str | None = None
    generator_version: str | None = None
    source_manifest_hash: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "database_path": self.database_path,
            "source_dir": self.source_dir,
            "row_counts": dict(self.row_counts),
            "source_row_counts": dict(self.source_row_counts),
            "imported_at": self.imported_at,
            "dataset_source": self.dataset_source,
            "generator_version": self.generator_version,
            "source_manifest_hash": self.source_manifest_hash,
            "schema_version": DATABASE_SCHEMA_VERSION,
        }


def _read_parquet_rows(path: Path) -> tuple[list[str], list[dict[str, object]]]:
    import pyarrow.parquet as parquet

    table = parquet.read_table(path)
    columns = list(table.column_names)
    return columns, table.to_pylist()


def load_source_tables(
    source_dir: Path,
) -> tuple[dict[str, list[dict[str, object]]], dict[str, int]]:
    """Read and schema-check every demo factory Parquet file."""

    tables: dict[str, list[dict[str, object]]] = {}
    row_counts: dict[str, int] = {}
    for name in TABLE_ORDER:
        path = source_dir / f"{name}.parquet"
        if not path.exists():
            raise DatabaseInitializationError(f"required demo factory file missing: {path}")
        columns, rows = _read_parquet_rows(path)
        expected = list(EXPECTED_SOURCE_COLUMNS[name])
        if set(columns) != set(expected):
            raise DatabaseInitializationError(
                f"schema drift in {path.name}: expected columns {sorted(expected)}, "
                f"found {sorted(columns)}"
            )
        for column in columns:
            if not _IDENTIFIER_PATTERN.fullmatch(column):
                raise DatabaseInitializationError(
                    f"unsafe column name {column!r} in {path.name}"
                )
        tables[name] = rows
        row_counts[name] = len(rows)
    return tables, row_counts


def _manifest_info(settings) -> tuple[str | None, str | None, str | None]:
    """Return (generator_version, dataset schema_version, manifest sha256)."""

    manifest_path = settings.dataset_root / "manifests" / "demo_factory.json"
    if not manifest_path.exists():
        return None, None, None
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None, digest
    return (
        manifest.get("generator_version"),
        manifest.get("schema_version"),
        digest,
    )


def _assert_source_boundary(source_dir: Path, settings) -> None:
    """Refuse sources outside the approved demo factory (e.g. external data)."""

    resolved = source_dir.resolve()
    external_root = settings.external_data_root.resolve()
    if external_root == resolved or external_root in resolved.parents:
        raise DatabaseInitializationError(
            f"refusing to import external dataset directory into the operational "
            f"database: {resolved}"
        )


def _sidecar_paths(path: Path) -> list[Path]:
    return [Path(f"{path}-wal"), Path(f"{path}-shm")]


def _cleanup(path: Path) -> None:
    for candidate in [path, *_sidecar_paths(path)]:
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass


def initialize_database(
    database_path: str | Path | None = None,
    source_dir: str | Path | None = None,
) -> InitializationReport:
    """Import the demo factory into SQLite and atomically publish the result."""

    settings = get_settings()
    target = Path(database_path) if database_path is not None else resolve_database_path()
    source = Path(source_dir) if source_dir is not None else Path(settings.demo_factory_root)

    if not source.is_dir():
        raise DatabaseInitializationError(f"demo factory source directory missing: {source}")
    _assert_source_boundary(source, settings)

    logger.info("validating demo factory files in %s", source)
    tables, source_row_counts = load_source_tables(source)

    dataset_values: set[str] = set()
    for rows in tables.values():
        for row in rows:
            value = row.get("source_dataset")
            if isinstance(value, str):
                dataset_values.add(value)
    dataset_source = sorted(dataset_values)[0] if len(dataset_values) == 1 else None
    generator_version, _, manifest_hash = _manifest_info(settings)
    imported_at = datetime.now().astimezone().isoformat(timespec="seconds")

    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_name(target.name + TEMP_SUFFIX)
    _cleanup(temp_path)

    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(str(temp_path))
        connection.execute(PRAGMA_FOREIGN_KEYS)
        connection.execute(PRAGMA_BUSY_TIMEOUT)
        connection.execute("PRAGMA journal_mode = WAL")
        create_schema(connection)

        for name in TABLE_ORDER:
            rows = tables[name]
            if not rows:
                continue
            columns = list(rows[0].keys())
            placeholders = ", ".join("?" for _ in columns)
            column_list = ", ".join(columns)
            connection.executemany(
                f"INSERT INTO {name} ({column_list}) VALUES ({placeholders})",
                [tuple(row.get(column) for column in columns) for row in rows],
            )
            logger.info("imported %s rows into %s", len(rows), name)

        connection.execute(
            f"""
            INSERT INTO {METADATA_TABLE} (
                id, schema_version, dataset_source, generator_version,
                imported_at, source_manifest_hash
            ) VALUES (1, ?, ?, ?, ?, ?)
            """,
            (DATABASE_SCHEMA_VERSION, dataset_source, generator_version, imported_at, manifest_hash),
        )
        connection.commit()

        report: ValidationReport = validate_connection(
            connection, temp_path, source_row_counts
        )
        if not report.is_valid:
            details = (
                report.invariant_failures
                + report.foreign_key_violations
                + report.missing_indexes
            )
            raise DatabaseInitializationError(
                "initialization validation failed: "
                + "; ".join(details or ["row counts do not match the source dataset"])
            )
    except DatabaseInitializationError:
        if connection is not None:
            connection.close()
            connection = None
        _cleanup(temp_path)
        logger.error("initialization failed; existing database preserved")
        raise
    except Exception as exc:  # noqa: BLE001 - re-raised as a domain error
        if connection is not None:
            connection.close()
            connection = None
        _cleanup(temp_path)
        logger.error("initialization failed: %s", exc)
        raise DatabaseInitializationError(str(exc)) from exc
    finally:
        if connection is not None:
            connection.close()

    for sidecar in _sidecar_paths(temp_path):
        if sidecar.exists():
            sidecar.unlink()
    os.replace(temp_path, target)

    result = InitializationReport(
        database_path=str(target),
        source_dir=str(source),
        row_counts=dict(source_row_counts),
        source_row_counts=dict(source_row_counts),
        imported_at=imported_at,
        dataset_source=dataset_source,
        generator_version=generator_version,
        source_manifest_hash=manifest_hash,
    )
    logger.info(
        "database initialized at %s (%s rows total)",
        target,
        sum(source_row_counts.values()),
    )
    return result


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(
        description="Initialize the ManufacturaIQ operational SQLite database"
    )
    parser.add_argument("--database", default=None, help="Target SQLite database path")
    parser.add_argument(
        "--source", default=None, help="Demo factory source directory (default: normalized/demo_factory)"
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON summary")
    args = parser.parse_args(argv)

    try:
        report = initialize_database(args.database, args.source)
    except DatabaseInitializationError as exc:
        logger.error("%s", exc)
        print(f"FAIL: {exc}")
        return 1
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"initialized: {report.database_path}")
        for table, count in report.row_counts.items():
            print(f"  {table:<22} {count}")
        print(f"schema version: {DATABASE_SCHEMA_VERSION}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
