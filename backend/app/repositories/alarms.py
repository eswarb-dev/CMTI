"""Read-only repository for machine alarms."""

from __future__ import annotations

from datetime import date, datetime

from app.db.models import AlarmRecord
from app.repositories.base import DEFAULT_LIMIT, BaseRepository

_TABLE = "machine_alarms"


class AlarmRepository(BaseRepository):
    """Async access to machine alarm history.

    Time-filtered methods use ``timestamp`` and return records in DESCENDING
    order (most recent first) with ``alarm_id`` DESC as tie-breaker.
    """

    async def get_by_id(self, alarm_id: str) -> AlarmRecord | None:
        row = await self._fetch_one(
            f"SELECT * FROM {_TABLE} WHERE alarm_id = ?", (alarm_id,)
        )
        return AlarmRecord.from_row(row) if row else None

    async def list_by_machine(
        self,
        machine_id: str,
        start_time: datetime | date | str | None = None,
        end_time: datetime | date | str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> list[AlarmRecord]:
        parameters: list[object] = [machine_id]
        clause = self._time_range("timestamp", start_time, end_time, parameters)
        rows = await self._fetch_all(
            f"SELECT * FROM {_TABLE} WHERE machine_id = ?{clause} "
            "ORDER BY timestamp DESC, alarm_id DESC LIMIT ?",
            (*parameters, self._bounded_limit(limit)),
        )
        return [AlarmRecord.from_row(row) for row in rows]

    async def list_by_code(
        self, alarm_code: str, limit: int = DEFAULT_LIMIT
    ) -> list[AlarmRecord]:
        rows = await self._fetch_all(
            f"SELECT * FROM {_TABLE} WHERE alarm_code = ? "
            "ORDER BY timestamp DESC, alarm_id DESC LIMIT ?",
            (alarm_code, self._bounded_limit(limit)),
        )
        return [AlarmRecord.from_row(row) for row in rows]

    async def list_by_machine_and_time_range(
        self,
        machine_id: str,
        start_time: datetime | date | str | None = None,
        end_time: datetime | date | str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> list[AlarmRecord]:
        return await self.list_by_machine(machine_id, start_time, end_time, limit)

    async def recent_for_machine(
        self, machine_id: str, limit: int = 10
    ) -> list[AlarmRecord]:
        """Most recent alarms for a machine (newest first)."""

        return await self.list_by_machine(machine_id, limit=limit)

    async def count_occurrences(
        self,
        machine_id: str,
        alarm_code: str,
        start_time: datetime | date | str | None = None,
        end_time: datetime | date | str | None = None,
    ) -> int:
        """Count how often ``alarm_code`` occurred on ``machine_id``."""

        parameters: list[object] = [machine_id, alarm_code]
        clause = self._time_range("timestamp", start_time, end_time, parameters)
        row = await self._fetch_one(
            f"SELECT COUNT(*) AS occurrence_count FROM {_TABLE} "
            f"WHERE machine_id = ? AND alarm_code = ?{clause}",
            tuple(parameters),
        )
        return int(row["occurrence_count"]) if row else 0
