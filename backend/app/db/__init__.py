"""Operational SQLite database package (STEP 05).

``initializer`` and ``validation`` submodules are imported lazily so that
``python -m app.db.initializer`` and ``python -m app.db.validation`` do not
double-import them through this package.
"""

from typing import Any

from app.db.connection import DatabaseConnection, resolve_database_path
from app.db.schema import DATABASE_SCHEMA_VERSION, TABLE_ORDER, create_schema
from app.db.sql_safety import is_readonly_query, validate_readonly_query

__all__ = [
    "DATABASE_SCHEMA_VERSION",
    "DatabaseConnection",
    "InitializationReport",
    "TABLE_ORDER",
    "ValidationReport",
    "create_schema",
    "initialize_database",
    "is_readonly_query",
    "resolve_database_path",
    "validate_database",
    "validate_readonly_query",
]

_LAZY_EXPORTS: dict[str, str] = {
    "InitializationReport": "app.db.initializer",
    "initialize_database": "app.db.initializer",
    "ValidationReport": "app.db.validation",
    "validate_database": "app.db.validation",
}


def __getattr__(name: str) -> Any:
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
