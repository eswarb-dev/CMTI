from __future__ import annotations

import pytest

from app.core.exceptions import RepositoryError
from app.repositories.external import EXTERNAL_DATASETS, ExternalDatasetRepository

SUPPORTED_DATASETS = {
    "predictive_maintenance",
    "cnc_tool_wear",
    "steel_faults",
    "industrial_maintenance",
}


async def test_supported_dataset_ids_are_listed() -> None:
    assert set(EXTERNAL_DATASETS) == SUPPORTED_DATASETS
    repository = ExternalDatasetRepository()
    datasets = await repository.list_datasets()
    assert {info.dataset_id for info in datasets} == SUPPORTED_DATASETS
    for info in datasets:
        assert info.artifacts
        for artifact in info.artifacts:
            assert artifact.rows > 0
            assert artifact.columns > 0


async def test_dataset_metadata_is_whitelisted() -> None:
    repository = ExternalDatasetRepository()
    info = await repository.get_dataset_metadata("predictive_maintenance")
    assert info.dataset_id == "predictive_maintenance"
    assert [a.artifact_name for a in info.artifacts] == ["machine_condition_observations"]
    assert info.artifacts[0].rows == 10000
    with pytest.raises(RepositoryError):
        await repository.get_dataset_metadata("demo_factory")
    with pytest.raises(RepositoryError):
        await repository.get_dataset_metadata("unknown_dataset")


async def test_schema_and_samples_are_read_only() -> None:
    repository = ExternalDatasetRepository()
    schema = await repository.get_schema("steel_faults", "quality_fault_records")
    assert schema
    assert any(field["name"] == "fault_class" for field in schema)
    samples = await repository.sample_records("steel_faults", "quality_fault_records", 3)
    assert len(samples) == 3
    assert all(isinstance(sample, dict) for sample in samples)
    bounded = await repository.sample_records(
        "steel_faults", "quality_fault_records", 10_000
    )
    assert len(bounded) == 100, "sample limit must be clamped"


async def test_artifact_whitelist_blocks_unknown_artifacts() -> None:
    repository = ExternalDatasetRepository()
    with pytest.raises(RepositoryError):
        await repository.get_schema("predictive_maintenance", "not_an_artifact")
    with pytest.raises(RepositoryError):
        await repository.sample_records("cnc_tool_wear", "machine_condition_observations", 1)


async def test_path_traversal_is_blocked() -> None:
    repository = ExternalDatasetRepository()
    hostile_names = [
        "../../../raw/documents/secret",
        "..\\..\\normalized\\demo_factory\\machines",
        "subdir/file",
    ]
    for hostile in hostile_names:
        with pytest.raises(RepositoryError):
            await repository.sample_records("predictive_maintenance", hostile, 1)
        with pytest.raises(RepositoryError):
            await repository.get_schema("predictive_maintenance", hostile)


async def test_external_repository_does_not_touch_sqlite() -> None:
    repository = ExternalDatasetRepository()
    assert not hasattr(repository, "_database")
    assert repository.root.name == "external"
