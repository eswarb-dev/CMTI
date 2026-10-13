"""Read-only repository for maintenance logs."""

from __future__ import annotations

from datetime import date, datetime

from app.db.models import MaintenanceRecord
from app.repositories.base import DEFAULT_LIMIT, BaseRepository

_TABLE = "maintenance_logs"


class MaintenanceRepository(BaseRepository):
    """Async access to maintenance history.

    Time-filtered methods use ``created_at`` and return records in DESCENDING
    order (most recent first) with ``maintenance_id`` DESC as tie-breaker.
    """

    async def get_by_id(self, maintenance_id: str) -> MaintenanceRecord | None:
        row = await self._fetch_one(
            f"SELECT * FROM {_TABLE} WHERE maintenance_id = ?", (maintenance_id,)
        )
        return MaintenanceRecord.from_row(row) if row else None

    async def list_by_machine(
        self, machine_id: str, limit: int = DEFAULT_LIMIT
    ) -> list[MaintenanceRecord]:
        rows = await self._fetch_all(
            f"SELECT * FROM {_TABLE} WHERE machine_id = ? "
            "ORDER BY created_at DESC, maintenance_id DESC LIMIT ?",
            (machine_id, self._bounded_limit(limit)),
        )
        return [MaintenanceRecord.from_row(row) for row in rows]

    async def list_by_failure_code(
        self, failure_code: str, limit: int = DEFAULT_LIMIT
    ) -> list[MaintenanceRecord]:
        rows = await self._fetch_all(
            f"SELECT * FROM {_TABLE} WHERE failure_code = ? "
            "ORDER BY created_at DESC, maintenance_id DESC LIMIT ?",
            (failure_code, self._bounded_limit(limit)),
        )
        return [MaintenanceRecord.from_row(row) for row in rows]

    async def list_by_machine_and_time_range(
        self,
        machine_id: str,
        start_time: datetime | date | str | None = None,
        end_time: datetime | date | str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> list[MaintenanceRecord]:
        parameters: list[object] = [machine_id]
        clause = self._time_range("created_at", start_time, end_time, parameters)
        rows = await self._fetch_all(
            f"SELECT * FROM {_TABLE} WHERE machine_id = ?{clause} "
            "ORDER BY created_at DESC, maintenance_id DESC LIMIT ?",
            (*parameters, self._bounded_limit(limit)),
        )
        return [MaintenanceRecord.from_row(row) for row in rows]

    async def recent_for_machine(
        self, machine_id: str, limit: int = 10
    ) -> list[MaintenanceRecord]:
        """Most recent maintenance records for a machine (newest first)."""

        return await self.list_by_machine(machine_id, limit=limit)
