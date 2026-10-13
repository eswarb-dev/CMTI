from __future__ import annotations

from app.db.connection import DatabaseConnection
from app.repositories.machines import MachineRepository


async def test_cnc05_exists(database: DatabaseConnection) -> None:
    repository = MachineRepository(database)
    assert await repository.exists("CNC-05") is True
    record = await repository.get_by_id("CNC-05")
    assert record is not None
    assert record.machine_id == "CNC-05"
    assert record.source_dataset == "manufacturaiq_demo_factory"
    assert record.is_synthetic is True
    assert record.machine_name


async def test_list_all_returns_three_machines(database: DatabaseConnection) -> None:
    repository = MachineRepository(database)
    machines = await repository.list_all()
    assert [m.machine_id for m in machines] == ["CNC-01", "CNC-03", "CNC-05"]


async def test_unknown_machine_returns_none(database: DatabaseConnection) -> None:
    repository = MachineRepository(database)
    assert await repository.get_by_id("CNC-99") is None
    assert await repository.exists("CNC-99") is False


async def test_parameterized_lookup_is_injection_safe(database: DatabaseConnection) -> None:
    repository = MachineRepository(database)
    hostile = "CNC-05'; DROP TABLE machines;--"
    assert await repository.get_by_id(hostile) is None
    assert await repository.exists("CNC-05") is True
    assert len(await repository.list_all()) == 3
