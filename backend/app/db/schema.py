from __future__ import annotations

import sqlite3

DATABASE_SCHEMA_VERSION = "1"

METADATA_TABLE = "database_metadata"

TABLE_MACHINES = "machines"
TABLE_PRODUCTS = "products"
TABLE_PRODUCTION_ORDERS = "production_orders"
TABLE_MAINTENANCE_LOGS = "maintenance_logs"
TABLE_QUALITY_INSPECTIONS = "quality_inspections"
TABLE_MACHINE_ALARMS = "machine_alarms"
TABLE_TELEMETRY = "telemetry"

#: Import/creation order.  Every table only references tables before it.
TABLE_ORDER: tuple[str, ...] = (
    TABLE_MACHINES,
    TABLE_PRODUCTS,
    TABLE_PRODUCTION_ORDERS,
    TABLE_MAINTENANCE_LOGS,
    TABLE_QUALITY_INSPECTIONS,
    TABLE_MACHINE_ALARMS,
    TABLE_TELEMETRY,
)

DATA_TABLES: tuple[str, ...] = TABLE_ORDER

#: Columns expected from the source Parquet files, in schema order.
EXPECTED_SOURCE_COLUMNS: dict[str, tuple[str, ...]] = {
    TABLE_MACHINES: (
        "machine_id",
        "machine_name",
        "machine_type",
        "asset_group",
        "installation_date",
        "status",
        "location",
        "criticality",
        "is_synthetic",
        "source_dataset",
    ),
    TABLE_PRODUCTS: (
        "product_id",
        "product_name",
        "material",
        "nominal_cycle_time_sec",
        "description",
        "is_synthetic",
        "source_dataset",
    ),
    TABLE_PRODUCTION_ORDERS: (
        "production_id",
        "batch_id",
        "machine_id",
        "product_id",
        "planned_quantity",
        "actual_quantity",
        "accepted_quantity",
        "rejected_quantity",
        "reject_rate",
        "planned_start_time",
        "actual_start_time",
        "actual_end_time",
        "cycle_time_sec",
        "shift",
        "production_status",
        "is_synthetic",
        "source_dataset",
    ),
    TABLE_MAINTENANCE_LOGS: (
        "maintenance_id",
        "machine_id",
        "created_at",
        "started_at",
        "completed_at",
        "maintenance_type",
        "symptom",
        "component",
        "failure_code",
        "inspection_findings",
        "action_taken",
        "planned_downtime_min",
        "actual_downtime_min",
        "status",
        "is_synthetic",
        "source_dataset",
    ),
    TABLE_QUALITY_INSPECTIONS: (
        "inspection_id",
        "batch_id",
        "machine_id",
        "product_id",
        "timestamp",
        "parameter",
        "nominal_value",
        "lsl",
        "usl",
        "measured_value",
        "result",
        "defect_type",
        "inspection_method",
        "is_synthetic",
        "source_dataset",
    ),
    TABLE_MACHINE_ALARMS: (
        "alarm_id",
        "machine_id",
        "timestamp",
        "alarm_code",
        "severity",
        "category",
        "description",
        "acknowledged",
        "acknowledged_at",
        "related_batch_id",
        "is_synthetic",
        "source_dataset",
    ),
    TABLE_TELEMETRY: (
        "telemetry_id",
        "machine_id",
        "timestamp",
        "rpm",
        "vibration_mm_s",
        "temperature_c",
        "current_a",
        "load_pct",
        "spindle_power_kw",
        "is_synthetic",
        "source_dataset",
    ),
}

PRIMARY_KEYS: dict[str, str] = {
    TABLE_MACHINES: "machine_id",
    TABLE_PRODUCTS: "product_id",
    TABLE_PRODUCTION_ORDERS: "production_id",
    TABLE_MAINTENANCE_LOGS: "maintenance_id",
    TABLE_QUALITY_INSPECTIONS: "inspection_id",
    TABLE_MACHINE_ALARMS: "alarm_id",
    TABLE_TELEMETRY: "telemetry_id",
}

_CREATE_TABLE_STATEMENTS: dict[str, str] = {
    TABLE_MACHINES: """
        CREATE TABLE machines (
            machine_id TEXT PRIMARY KEY,
            machine_name TEXT,
            machine_type TEXT,
            asset_group TEXT,
            installation_date TEXT,
            status TEXT,
            location TEXT,
            criticality TEXT,
            is_synthetic INTEGER NOT NULL,
            source_dataset TEXT NOT NULL
        )
    """,
    TABLE_PRODUCTS: """
        CREATE TABLE products (
            product_id TEXT PRIMARY KEY,
            product_name TEXT,
            material TEXT,
            nominal_cycle_time_sec INTEGER,
            description TEXT,
            is_synthetic INTEGER NOT NULL,
            source_dataset TEXT NOT NULL
        )
    """,
    TABLE_PRODUCTION_ORDERS: """
        CREATE TABLE production_orders (
            production_id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL,
            machine_id TEXT NOT NULL REFERENCES machines(machine_id),
            product_id TEXT NOT NULL REFERENCES products(product_id),
            planned_quantity INTEGER,
            actual_quantity INTEGER,
            accepted_quantity INTEGER,
            rejected_quantity INTEGER,
            reject_rate REAL,
            planned_start_time TEXT,
            actual_start_time TEXT,
            actual_end_time TEXT,
            cycle_time_sec INTEGER,
            shift TEXT,
            production_status TEXT,
            is_synthetic INTEGER NOT NULL,
            source_dataset TEXT NOT NULL
        )
    """,
    TABLE_MAINTENANCE_LOGS: """
        CREATE TABLE maintenance_logs (
            maintenance_id TEXT PRIMARY KEY,
            machine_id TEXT NOT NULL REFERENCES machines(machine_id),
            created_at TEXT,
            started_at TEXT,
            completed_at TEXT,
            maintenance_type TEXT,
            symptom TEXT,
            component TEXT,
            failure_code TEXT,
            inspection_findings TEXT,
            action_taken TEXT,
            planned_downtime_min INTEGER,
            actual_downtime_min INTEGER,
            status TEXT,
            is_synthetic INTEGER NOT NULL,
            source_dataset TEXT NOT NULL
        )
    """,
    TABLE_QUALITY_INSPECTIONS: """
        CREATE TABLE quality_inspections (
            inspection_id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL REFERENCES production_orders(batch_id),
            machine_id TEXT NOT NULL REFERENCES machines(machine_id),
            product_id TEXT NOT NULL REFERENCES products(product_id),
            timestamp TEXT,
            parameter TEXT,
            nominal_value REAL,
            lsl REAL,
            usl REAL,
            measured_value REAL,
            result TEXT,
            defect_type TEXT,
            inspection_method TEXT,
            is_synthetic INTEGER NOT NULL,
            source_dataset TEXT NOT NULL
        )
    """,
    TABLE_MACHINE_ALARMS: """
        CREATE TABLE machine_alarms (
            alarm_id TEXT PRIMARY KEY,
            machine_id TEXT NOT NULL REFERENCES machines(machine_id),
            timestamp TEXT,
            alarm_code TEXT,
            severity TEXT,
            category TEXT,
            description TEXT,
            acknowledged INTEGER,
            acknowledged_at TEXT,
            related_batch_id TEXT REFERENCES production_orders(batch_id),
            is_synthetic INTEGER NOT NULL,
            source_dataset TEXT NOT NULL
        )
    """,
    TABLE_TELEMETRY: """
        CREATE TABLE telemetry (
            telemetry_id TEXT PRIMARY KEY,
            machine_id TEXT NOT NULL REFERENCES machines(machine_id),
            timestamp TEXT,
            rpm REAL,
            vibration_mm_s REAL,
            temperature_c REAL,
            current_a REAL,
            load_pct REAL,
            spindle_power_kw REAL,
            is_synthetic INTEGER NOT NULL,
            source_dataset TEXT NOT NULL
        )
    """,
    METADATA_TABLE: """
        CREATE TABLE database_metadata (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            schema_version TEXT NOT NULL,
            dataset_source TEXT,
            generator_version TEXT,
            imported_at TEXT,
            source_manifest_hash TEXT
        )
    """,
}

_INDEX_STATEMENTS: tuple[str, ...] = (
    "CREATE UNIQUE INDEX idx_production_orders_batch_id ON production_orders(batch_id)",
    "CREATE INDEX idx_production_orders_machine_id ON production_orders(machine_id)",
    "CREATE INDEX idx_production_orders_product_id ON production_orders(product_id)",
    "CREATE INDEX idx_production_orders_actual_start_time ON production_orders(actual_start_time)",
    "CREATE INDEX idx_quality_inspections_machine_id ON quality_inspections(machine_id)",
    "CREATE INDEX idx_quality_inspections_product_id ON quality_inspections(product_id)",
    "CREATE INDEX idx_quality_inspections_batch_id ON quality_inspections(batch_id)",
    "CREATE INDEX idx_quality_inspections_timestamp ON quality_inspections(timestamp)",
    "CREATE INDEX idx_quality_inspections_machine_timestamp "
    "ON quality_inspections(machine_id, timestamp)",
    "CREATE INDEX idx_maintenance_logs_machine_id ON maintenance_logs(machine_id)",
    "CREATE INDEX idx_maintenance_logs_created_at ON maintenance_logs(created_at)",
    "CREATE INDEX idx_maintenance_logs_failure_code ON maintenance_logs(failure_code)",
    "CREATE INDEX idx_maintenance_logs_machine_created "
    "ON maintenance_logs(machine_id, created_at)",
    "CREATE INDEX idx_machine_alarms_machine_id ON machine_alarms(machine_id)",
    "CREATE INDEX idx_machine_alarms_timestamp ON machine_alarms(timestamp)",
    "CREATE INDEX idx_machine_alarms_alarm_code ON machine_alarms(alarm_code)",
    "CREATE INDEX idx_machine_alarms_machine_timestamp "
    "ON machine_alarms(machine_id, timestamp)",
    "CREATE INDEX idx_telemetry_machine_id ON telemetry(machine_id)",
    "CREATE INDEX idx_telemetry_timestamp ON telemetry(timestamp)",
    "CREATE INDEX idx_telemetry_machine_timestamp ON telemetry(machine_id, timestamp)",
)

INDEX_NAMES: tuple[str, ...] = tuple(
    statement.split()[statement.split().index("INDEX") + 1]
    for statement in _INDEX_STATEMENTS
)


def create_schema(connection: sqlite3.Connection) -> None:
    """Create all tables and indexes on a standard sqlite3 connection."""

    for statement in _CREATE_TABLE_STATEMENTS.values():
        connection.execute(statement)
    for statement in _INDEX_STATEMENTS:
        connection.execute(statement)


def table_names() -> tuple[str, ...]:
    """Data tables in FK-safe import order (metadata table excluded)."""

    return TABLE_ORDER


def all_table_names() -> tuple[str, ...]:
    return (*TABLE_ORDER, METADATA_TABLE)
