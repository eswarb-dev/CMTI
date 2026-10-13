from __future__ import annotations

from datetime import datetime

from app.db.connection import DatabaseConnection
from app.repositories.production import ProductionRepository


async def test_cnc05_production_history(database: DatabaseConnection) -> None:
    repository = ProductionRepository(database)
    records = await repository.list_by_machine("CNC-05", limit=500)
    assert records, "CNC-05 should have production history"
    assert all(record.machine_id == "CNC-05" for record in records)
    timestamps = [record.actual_start_time for record in records]
    assert timestamps == sorted(timestamps, reverse=True), "newest first ordering"
    for record in records:
        assert record.accepted_quantity + record.rejected_quantity == record.actual_quantity


async def test_time_range_filtering(database: DatabaseConnection) -> None:
    repository = ProductionRepository(database)
    start = datetime.fromisoformat("2026-09-01T00:00:00+05:30")
    end = datetime.fromisoformat("2026-09-05T00:00:00+05:30")
    records = await repository.list_by_machine("CNC-05", start_time=start, end_time=end)
    assert records
    for record in records:
        assert start <= record.actual_start_time <= end


async def test_limit_bounds_results(database: DatabaseConnection) -> None:
    repository = ProductionRepository(database)
    records = await repository.list_by_machine("CNC-05", limit=5)
    assert len(records) == 5


async def test_lookup_by_batch_id(database: DatabaseConnection) -> None:
    repository = ProductionRepository(database)
    records = await repository.list_by_machine("CNC-05", limit=1)
    record = records[0]
    by_batch = await repository.get_by_batch_id(record.batch_id)
    assert by_batch is not None
    assert by_batch.production_id == record.production_id
    by_id = await repository.get_by_production_id(record.production_id)
    assert by_id is not None
    assert by_id.batch_id == record.batch_id
    assert by_batch.planned_start_time.tzinfo is not None


async def test_list_by_product_and_machine_product(database: DatabaseConnection) -> None:
    repository = ProductionRepository(database)
    product_records = await repository.list_by_product("SHAFT-A", limit=20)
    assert product_records
    assert all(record.product_id == "SHAFT-A" for record in product_records)
    combined = await repository.list_by_machine_and_product(
        "CNC-05", product_records[0].product_id, limit=20
    )
    assert combined
    for record in combined:
        assert record.machine_id == "CNC-05"
        assert record.product_id == product_records[0].product_id


async def test_summarize_rejections_is_deterministic(database: DatabaseConnection) -> None:
    repository = ProductionRepository(database)
    summary = await repository.summarize_rejections(machine_id="CNC-05")
    records = await repository.list_by_machine("CNC-05", limit=1000)
    assert summary.order_count == len(records)
    assert summary.total_actual_quantity == sum(r.actual_quantity for r in records)
    assert summary.total_accepted_quantity == sum(r.accepted_quantity for r in records)
    assert summary.total_rejected_quantity == sum(r.rejected_quantity for r in records)
    expected_rate = summary.total_rejected_quantity / summary.total_actual_quantity
    assert abs(summary.reject_rate - expected_rate) < 1e-9
    assert summary.to_dict()["order_count"] == summary.order_count


async def test_summarize_rejections_zero_denominator_is_null(database: DatabaseConnection) -> None:
    repository = ProductionRepository(database)
    summary = await repository.summarize_rejections(machine_id="NO-SUCH-MACHINE")
    assert summary.order_count == 0
    assert summary.total_actual_quantity == 0
    assert summary.reject_rate is None


async def test_summarize_rejections_respects_filters(database: DatabaseConnection) -> None:
    repository = ProductionRepository(database)
    overall = await repository.summarize_rejections()
    product = await repository.summarize_rejections(product_id="SHAFT-A")
    assert overall.order_count == 180
    assert 0 < product.order_count < overall.order_count
    assert product.total_rejected_quantity <= overall.total_rejected_quantity
