"""Read-only repository for the machines table."""

from __future__ import annotations

from app.db.models import MachineRecord
from app.repositories.base import BaseRepository

_TABLE = "machines"


class MachineRepository(BaseRepository):
    """Async access to machine master data."""

    async def get_by_id(self, machine_id: str) -> MachineRecord | None:
        row = await self._fetch_one(
            f"SELECT * FROM {_TABLE} WHERE machine_id = ?", (machine_id,)
        )
        return MachineRecord.from_row(row) if row else None

    async def list_all(self) -> list[MachineRecord]:
        """Return all machines ordered by ``machine_id`` ascending."""

        rows = await self._fetch_all(f"SELECT * FROM {_TABLE} ORDER BY machine_id ASC")
        return [MachineRecord.from_row(row) for row in rows]

    async def exists(self, machine_id: str) -> bool:
        row = await self._fetch_one(
            f"SELECT 1 FROM {_TABLE} WHERE machine_id = ?", (machine_id,)
        )
        return row is not None
