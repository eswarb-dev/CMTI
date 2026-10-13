"""Repository layer for the operational database.

Repositories return typed internal records only.  They never create evidence,
call models, or invoke agents — that belongs to future services.
"""

from __future__ import annotations

from app.db.connection import DatabaseConnection
from app.repositories.alarms import AlarmRepository
from app.repositories.external import ExternalDatasetRepository
from app.repositories.machines import MachineRepository
from app.repositories.maintenance import MaintenanceRepository
from app.repositories.products import ProductRepository
from app.repositories.production import ProductionRepository
from app.repositories.quality import QualityRepository
from app.repositories.telemetry import TelemetryRepository

__all__ = [
    "AlarmRepository",
    "ExternalDatasetRepository",
    "MachineRepository",
    "MaintenanceRepository",
    "ProductRepository",
    "ProductionRepository",
    "QualityRepository",
    "TelemetryRepository",
    "DatabaseConnection",
]
