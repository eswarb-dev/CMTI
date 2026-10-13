from __future__ import annotations

from datetime import datetime

from app.db.connection import DatabaseConnection
from app.repositories.telemetry import METRIC_COLUMNS, TelemetryRepository


START = "2026-09-01T08:00:00+05:30"
END = "2026-09-01T12:00:00+05:30"


async def test_cnc05_time_range_telemetry(database: DatabaseConnection) -> None:
    repository = TelemetryRepository(database)
    rows = await repository.list_by_machine_and_time_range(
        "CNC-05", start_time=START, end_time=END, limit=1000
    )
    assert rows, "CNC-05 should have telemetry in the window"
    timestamps = [row.timestamp for row in rows]
    assert timestamps == sorted(timestamps), "ascending chronological ordering"
    for row in rows:
        assert row.machine_id == "CNC-05"
        assert row.rpm is not None
        assert row.is_synthetic is True
    start = datetime.fromisoformat(START)
    end = datetime.fromisoformat(END)
    for row in rows:
        assert start <= row.timestamp <= end


async def test_default_limit_is_bounded(database: DatabaseConnection) -> None:
    repository = TelemetryRepository(database)
    rows = await repository.list_by_machine_and_time_range("CNC-05", limit=10)
    assert len(rows) == 10


async def test_latest_for_machine(database: DatabaseConnection) -> None:
    repository = TelemetryRepository(database)
    latest = await repository.latest_for_machine("CNC-05")
    assert latest is not None
    assert latest.machine_id == "CNC-05"
    earlier = await repository.list_by_machine_and_time_range("CNC-05", limit=1)
    assert latest.timestamp >= earlier[0].timestamp
    assert await repository.latest_for_machine("CNC-99") is None


async def test_get_by_id(database: DatabaseConnection) -> None:
    repository = TelemetryRepository(database)
    latest = await repository.latest_for_machine("CNC-05")
    fetched = await repository.get_by_id(latest.telemetry_id)
    assert fetched is not None
    assert fetched.telemetry_id == latest.telemetry_id
    assert fetched.timestamp.tzinfo is not None
    assert await repository.get_by_id("TEL-NOPE") is None


async def test_summarize_metrics(database: DatabaseConnection) -> None:
    repository = TelemetryRepository(database)
    summary = await repository.summarize("CNC-05", START, END)
    assert summary.sample_count > 0
    assert set(summary.metrics) == set(METRIC_COLUMNS)
    for name, stats in summary.metrics.items():
        assert stats.count <= summary.sample_count
        if stats.count:
            assert stats.min <= stats.mean <= stats.max
            assert stats.first is not None
            assert stats.last is not None
    assert summary.machine_id == "CNC-05"
    assert summary.start_time is not None
    window_rows = await repository.list_by_machine_and_time_range(
        "CNC-05", start_time=START, end_time=END, limit=1000
    )
    assert summary.sample_count == len(window_rows)
    assert summary.metrics["rpm"].first == window_rows[0].rpm
    assert summary.metrics["rpm"].last == window_rows[-1].rpm


async def test_summarize_empty_window(database: DatabaseConnection) -> None:
    repository = TelemetryRepository(database)
    summary = await repository.summarize("CNC-99", START, END)
    assert summary.sample_count == 0
    for stats in summary.metrics.values():
        assert stats.count == 0
        assert stats.mean is None
