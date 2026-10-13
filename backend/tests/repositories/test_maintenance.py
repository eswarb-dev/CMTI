from __future__ import annotations

from datetime import datetime

from app.db.connection import DatabaseConnection
from app.repositories.maintenance import MaintenanceRepository


async def test_cnc05_maintenance_history(database: DatabaseConnection) -> None:
    repository = MaintenanceRepository(database)
    records = await repository.list_by_machine("CNC-05", limit=100)
    assert records, "CNC-05 should have maintenance history"
    for record in records:
        assert record.machine_id == "CNC-05"
        assert record.maintenance_id
        assert record.is_synthetic is True
        if record.created_at and record.started_at and record.completed_at:
            assert record.created_at <= record.started_at <= record.completed_at


async def test_get_by_id_and_ordering(database: DatabaseConnection) -> None:
    repository = MaintenanceRepository(database)
    records = await repository.list_by_machine("CNC-05", limit=100)
    fetched = await repository.get_by_id(records[0].maintenance_id)
    assert fetched is not None
    assert fetched.maintenance_id == records[0].maintenance_id
    created = [record.created_at for record in records]
    assert created == sorted(created, reverse=True), "newest first ordering"


async def test_recent_for_machine_is_bounded(database: DatabaseConnection) -> None:
    repository = MaintenanceRepository(database)
    recent = await repository.recent_for_machine("CNC-05", limit=3)
    assert len(recent) == 3
    all_records = await repository.list_by_machine("CNC-05", limit=100)
    assert [r.maintenance_id for r in recent] == [
        r.maintenance_id for r in all_records[:3]
    ]


async def test_time_range_and_failure_code(database: DatabaseConnection) -> None:
    repository = MaintenanceRepository(database)
    start = datetime.fromisoformat("2026-09-01T00:00:00+05:30")
    end = datetime.fromisoformat("2026-10-20T00:00:00+05:30")
    window = await repository.list_by_machine_and_time_range(
        "CNC-05", start_time=start, end_time=end, limit=100
    )
    assert window
    for record in window:
        assert start <= record.created_at <= end

    coded = await repository.list_by_failure_code("FC-NONE")
    assert isinstance(coded, list)
    known = [r for r in (await repository.list_by_machine("CNC-05", limit=100)) if r.failure_code]
    if known:
        by_code = await repository.list_by_failure_code(known[0].failure_code, limit=100)
        assert by_code
        assert all(r.failure_code == known[0].failure_code for r in by_code)


async def test_unknown_machine_returns_empty(database: DatabaseConnection) -> None:
    repository = MaintenanceRepository(database)
    assert await repository.list_by_machine("CNC-99") == []
    assert await repository.get_by_id("MNT-NOPE") is None
