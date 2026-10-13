"""Private persistence-layer row models for the operational database.

These structures are INTERNAL to the persistence layer.  They are not shared
application contracts and must never be exported from ``app.contracts``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

_BOOL_FIELDS = frozenset(
    {
        "is_synthetic",
        "acknowledged",
    }
)


def parse_timestamp(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp keeping its original UTC offset."""

    if value is None or value == "":
        return None
    parsed = datetime.fromisoformat(value)
    return parsed


def as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return bool(int(value))


def _convert(name: str, value: object) -> object:
    if name in _BOOL_FIELDS:
        return as_bool(value)
    return value


def _row_mapping(row: sqlite3.Row) -> dict[str, object]:
    return {key: _convert(key, row[key]) for key in row.keys()}


@dataclass(slots=True)
class MachineRecord:
    machine_id: str
    machine_name: str | None
    machine_type: str | None
    asset_group: str | None
    installation_date: str | None
    status: str | None
    location: str | None
    criticality: str | None
    is_synthetic: bool
    source_dataset: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> MachineRecord:
        return cls(**_row_mapping(row))


@dataclass(slots=True)
class ProductRecord:
    product_id: str
    product_name: str | None
    material: str | None
    nominal_cycle_time_sec: int | None
    description: str | None
    is_synthetic: bool
    source_dataset: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> ProductRecord:
        return cls(**_row_mapping(row))


@dataclass(slots=True)
class ProductionRecord:
    production_id: str
    batch_id: str
    machine_id: str
    product_id: str
    planned_quantity: int | None
    actual_quantity: int | None
    accepted_quantity: int | None
    rejected_quantity: int | None
    reject_rate: float | None
    planned_start_time: datetime | None
    actual_start_time: datetime | None
    actual_end_time: datetime | None
    cycle_time_sec: int | None
    shift: str | None
    production_status: str | None
    is_synthetic: bool
    source_dataset: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> ProductionRecord:
        data = _row_mapping(row)
        for field in ("planned_start_time", "actual_start_time", "actual_end_time"):
            data[field] = parse_timestamp(data[field])  # type: ignore[arg-type]
        return cls(**data)


@dataclass(slots=True)
class MaintenanceRecord:
    maintenance_id: str
    machine_id: str
    created_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    maintenance_type: str | None
    symptom: str | None
    component: str | None
    failure_code: str | None
    inspection_findings: str | None
    action_taken: str | None
    planned_downtime_min: int | None
    actual_downtime_min: int | None
    status: str | None
    is_synthetic: bool
    source_dataset: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> MaintenanceRecord:
        data = _row_mapping(row)
        for field in ("created_at", "started_at", "completed_at"):
            data[field] = parse_timestamp(data[field])  # type: ignore[arg-type]
        return cls(**data)


@dataclass(slots=True)
class QualityRecord:
    inspection_id: str
    batch_id: str
    machine_id: str
    product_id: str
    timestamp: datetime | None
    parameter: str | None
    nominal_value: float | None
    lsl: float | None
    usl: float | None
    measured_value: float | None
    result: str | None
    defect_type: str | None
    inspection_method: str | None
    is_synthetic: bool
    source_dataset: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> QualityRecord:
        data = _row_mapping(row)
        data["timestamp"] = parse_timestamp(data["timestamp"])  # type: ignore[arg-type]
        return cls(**data)


@dataclass(slots=True)
class AlarmRecord:
    alarm_id: str
    machine_id: str
    timestamp: datetime | None
    alarm_code: str | None
    severity: str | None
    category: str | None
    description: str | None
    acknowledged: bool
    acknowledged_at: datetime | None
    related_batch_id: str | None
    is_synthetic: bool
    source_dataset: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> AlarmRecord:
        data = _row_mapping(row)
        data["timestamp"] = parse_timestamp(data["timestamp"])  # type: ignore[arg-type]
        data["acknowledged_at"] = parse_timestamp(data["acknowledged_at"])  # type: ignore[arg-type]
        return cls(**data)


@dataclass(slots=True)
class TelemetryRecord:
    telemetry_id: str
    machine_id: str
    timestamp: datetime | None
    rpm: float | None
    vibration_mm_s: float | None
    temperature_c: float | None
    current_a: float | None
    load_pct: float | None
    spindle_power_kw: float | None
    is_synthetic: bool
    source_dataset: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> TelemetryRecord:
        data = _row_mapping(row)
        data["timestamp"] = parse_timestamp(data["timestamp"])  # type: ignore[arg-type]
        return cls(**data)


@dataclass(slots=True)
class DatabaseMetadataRecord:
    schema_version: str
    dataset_source: str | None
    generator_version: str | None
    imported_at: str | None
    source_manifest_hash: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> DatabaseMetadataRecord:
        return cls(
            schema_version=row["schema_version"],
            dataset_source=row["dataset_source"],
            generator_version=row["generator_version"],
            imported_at=row["imported_at"],
            source_manifest_hash=row["source_manifest_hash"],
        )
