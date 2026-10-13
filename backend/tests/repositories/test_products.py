from __future__ import annotations

from app.db.connection import DatabaseConnection
from app.repositories.products import ProductRepository


async def test_shaft_a_exists(database: DatabaseConnection) -> None:
    repository = ProductRepository(database)
    assert await repository.exists("SHAFT-A") is True
    record = await repository.get_by_id("SHAFT-A")
    assert record is not None
    assert record.product_id == "SHAFT-A"
    assert record.material
    assert record.nominal_cycle_time_sec
    assert record.is_synthetic is True


async def test_list_all_returns_three_products(database: DatabaseConnection) -> None:
    repository = ProductRepository(database)
    products = await repository.list_all()
    assert [p.product_id for p in products] == ["GEAR-B", "HOUSING-C", "SHAFT-A"]


async def test_unknown_product_returns_none(database: DatabaseConnection) -> None:
    repository = ProductRepository(database)
    assert await repository.get_by_id("NO-SUCH-PRODUCT") is None
    assert await repository.exists("NO-SUCH-PRODUCT") is False
