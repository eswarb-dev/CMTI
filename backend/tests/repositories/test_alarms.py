from __future__ import annotations

from datetime import datetime

from app.db.connection import DatabaseConnection
from app.repositories.alarms import AlarmRepository


async def test_list_by_machine_and_ordering(database: DatabaseConnection) -> None:
    repository = AlarmRepository(database)
    records = await repository.list_by_machine("CNC-05", limit=100)
    assert records
    for record in records:
        assert record.machine_id == "CNC-05"
        assert record.acknowledged in (True, False)
    timestamps = [record.timestamp for record in records]
    assert timestamps == sorted(timestamps, reverse=True), "newest first ordering"


async def test_recurring_alarm_queries(database: DatabaseConnection) -> None:
    repository = AlarmRepository(database)
    count = await repository.count_occurrences("CNC-05", "ALM-VIB-01")
    assert count >= 2, "ALM-VIB-01 should recur on CNC-05"
    records = await repository.list_by_code("ALM-VIB-01", limit=500)
    assert records
    assert all(record.alarm_code == "ALM-VIB-01" for record in records)
    for_machine = [record for record in records if record.machine_id == "CNC-05"]
    assert len(for_machine) == count
    machine_records = await repository.list_by_machine("CNC-05", limit=500)
    assert len([r for r in machine_records if r.alarm_code == "ALM-VIB-01"]) == count


async def test_count_occurrences_time_range(database: DatabaseConnection) -> None:
    repository = AlarmRepository(database)
    start = datetime.fromisoformat("2026-09-01T00:00:00+05:30")
    end = datetime.fromisoformat("2026-10-20T00:00:00+05:30")
    in_range = await repository.count_occurrences(
        "CNC-05", "ALM-VIB-01", start_time=start, end_time=end
    )
    overall = await repository.count_occurrences("CNC-05", "ALM-VIB-01")
    assert in_range == overall
    empty = await repository.count_occurrences(
        "CNC-05", "ALM-VIB-01", start_time=start, end_time=start
    )
    assert empty == 0


async def test_recent_for_machine_and_lookups(database: DatabaseConnection) -> None:
    repository = AlarmRepository(database)
    recent = await repository.recent_for_machine("CNC-05", limit=2)
    assert len(recent) == 2
    fetched = await repository.get_by_id(recent[0].alarm_id)
    assert fetched is not None
    assert fetched.alarm_id == recent[0].alarm_id
    assert await repository.get_by_id("ALM-NOPE") is None
    assert await repository.list_by_machine("CNC-99") == []


async def test_time_range_filtering(database: DatabaseConnection) -> None:
    repository = AlarmRepository(database)
    start = datetime.fromisoformat("2026-09-01T00:00:00+05:30")
    end = datetime.fromisoformat("2026-09-03T00:00:00+05:30")
    window = await repository.list_by_machine_and_time_range(
        "CNC-05", start_time=start, end_time=end, limit=100
    )
    for record in window:
        assert start <= record.timestamp <= end
