from __future__ import annotations

from datetime import datetime

from app.db.connection import DatabaseConnection
from app.repositories.quality import QualityRepository


async def test_shaft_a_cnc05_inspections(database: DatabaseConnection) -> None:
    repository = QualityRepository(database)
    records = await repository.list_by_machine("CNC-05", limit=500)
    assert records
    shaft_records = [r for r in records if r.product_id == "SHAFT-A"]
    assert shaft_records, "CNC-05 should inspect SHAFT-A"
    for record in shaft_records:
        assert record.machine_id == "CNC-05"
        assert record.timestamp is not None
        assert record.timestamp.tzinfo is not None


async def test_list_by_product_and_batch(database: DatabaseConnection) -> None:
    repository = QualityRepository(database)
    shaft = await repository.list_by_product("SHAFT-A", limit=50)
    assert shaft
    assert all(record.product_id == "SHAFT-A" for record in shaft)
    batch_id = shaft[0].batch_id
    by_batch = await repository.list_by_batch(batch_id, limit=100)
    assert by_batch
    assert all(record.batch_id == batch_id for record in by_batch)
    fetched = await repository.get_by_id(shaft[0].inspection_id)
    assert fetched is not None
    assert fetched.inspection_id == shaft[0].inspection_id


async def test_time_range_and_failures(database: DatabaseConnection) -> None:
    repository = QualityRepository(database)
    start = datetime.fromisoformat("2026-09-01T00:00:00+05:30")
    end = datetime.fromisoformat("2026-09-10T00:00:00+05:30")
    window = await repository.list_by_machine_and_time_range(
        "CNC-05", start_time=start, end_time=end, limit=1000
    )
    assert window
    for record in window:
        assert start <= record.timestamp <= end
    failures = await repository.list_failures(machine_id="CNC-05", limit=100)
    assert failures
    for record in failures:
        assert record.result == "FAIL"
        assert not (record.lsl <= record.measured_value <= record.usl)


async def test_summarize_results_groups_by_parameter(database: DatabaseConnection) -> None:
    repository = QualityRepository(database)
    summary = await repository.summarize_results(machine_id="CNC-05", product_id="SHAFT-A")
    assert summary.inspection_count > 0
    assert summary.inspection_count == summary.pass_count + summary.fail_count
    assert summary.failure_rate == summary.fail_count / summary.inspection_count
    assert summary.parameters, "parameters must be grouped"
    assert len(summary.parameters) > 1, "demo factory uses several parameters"
    assert summary.min_measurement is None, "no cross-parameter mean"
    assert summary.mean_measurement is None
    total = sum(p.inspection_count for p in summary.parameters)
    assert total == summary.inspection_count
    for parameter in summary.parameters:
        assert parameter.inspection_count == parameter.pass_count + parameter.fail_count
        assert parameter.min_measurement <= parameter.mean_measurement <= parameter.max_measurement


async def test_summarize_single_parameter_populates_stats(database: DatabaseConnection) -> None:
    repository = QualityRepository(database)
    summary = await repository.summarize_results(
        machine_id="CNC-05", product_id="SHAFT-A", parameter="diameter_mm"
    )
    assert len(summary.parameters) == 1
    assert summary.min_measurement is not None
    assert summary.max_measurement is not None
    assert summary.mean_measurement is not None
    assert summary.min_measurement <= summary.mean_measurement <= summary.max_measurement


async def test_summarize_results_empty_filter(database: DatabaseConnection) -> None:
    repository = QualityRepository(database)
    summary = await repository.summarize_results(machine_id="NO-SUCH-MACHINE")
    assert summary.inspection_count == 0
    assert summary.failure_rate is None
    assert summary.parameters == []
