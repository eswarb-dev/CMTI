from __future__ import annotations

import json
import sys
from pathlib import Path

import polars as pl
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.data_pipeline.adapters.cnc_tool_wear import CNCToolWearAdapter
from scripts.data_pipeline.paths import DATASETS_ROOT, MANIFESTS_ROOT, NORMALIZED_ROOT, RAW_ROOT
from scripts.data_pipeline.provenance import sha256_file
from scripts.data_pipeline.run import run_adapters


@pytest.fixture(scope="session")
def normalized_outputs() -> dict[str, list[Path]]:
    run_adapters(None, validate_only=False)
    return {
        "predictive": [NORMALIZED_ROOT / "predictive_maintenance" / "machine_condition_observations.parquet"],
        "cnc": [
            NORMALIZED_ROOT / "cnc_tool_wear" / "experiment_metadata.parquet",
            NORMALIZED_ROOT / "cnc_tool_wear" / "experiment_samples.parquet",
        ],
        "steel": [NORMALIZED_ROOT / "steel_faults" / "quality_fault_records.parquet"],
        "industrial": [
            NORMALIZED_ROOT / "industrial_maintenance" / "maintenance_work_orders.parquet",
            NORMALIZED_ROOT / "industrial_maintenance" / "sensor_tag_catalog.parquet",
        ],
    }


def test_raw_dataset_paths_resolve() -> None:
    for name in ["predictive_maintenance", "cnc_tool_wear", "steel_faults", "industrial_maintenance"]:
        assert (RAW_ROOT / name).is_dir()


def test_expected_critical_columns_exist() -> None:
    assert "Failure Type" in pl.read_csv(RAW_ROOT / "predictive_maintenance" / "predictive_maintenance.csv", n_rows=0).columns
    assert "Machining_Process" in CNCToolWearAdapter().read_experiment_csv("experiment_12.csv").columns
    assert "Other_Faults" in pl.read_csv(RAW_ROOT / "steel_faults" / "faults.csv", n_rows=0).columns
    assert "ScheduledStartDate" in pl.read_csv(RAW_ROOT / "industrial_maintenance" / "maintenance.csv", n_rows=0).columns
    assert "Variable_type" in pl.read_csv(RAW_ROOT / "industrial_maintenance" / "sensor_tags.csv", n_rows=0).columns


def test_raw_hashes_match_existing_manifest() -> None:
    sources = {entry["source_id"]: entry for entry in json.loads((MANIFESTS_ROOT / "sources.json").read_text())}
    for entry in json.loads((MANIFESTS_ROOT / "files.json").read_text()):
        raw_path = Path(sources[entry["dataset_id"]]["raw_directory"]) / entry["relative_path"]
        assert sha256_file(raw_path) == entry["sha256"]


def test_predictive_maintenance_preserves_10000_records(normalized_outputs: dict[str, list[Path]]) -> None:
    frame = pl.read_parquet(normalized_outputs["predictive"][0])
    assert frame.height == 10000
    assert frame["udi"].n_unique() == 10000
    assert "product_id" in frame.columns


def test_cnc_experiment_ids_map_correctly() -> None:
    adapter = CNCToolWearAdapter()
    ids_from_files = {adapter.experiment_id(name) for name in adapter.experiment_files()}
    ids_from_train = set(pl.read_csv(RAW_ROOT / "cnc_tool_wear" / "train.csv")["No"].to_list())
    assert ids_from_files == ids_from_train == set(range(1, 19))


def test_cnc_row_sequence_and_train_metadata_preserved(normalized_outputs: dict[str, list[Path]]) -> None:
    metadata = pl.read_parquet(normalized_outputs["cnc"][0])
    samples = pl.read_parquet(normalized_outputs["cnc"][1])
    assert metadata.height == 18
    assert "passed_visual_inspection" in metadata.columns
    exp1 = samples.filter(pl.col("experiment_id") == 1).sort("sample_index")
    assert exp1["sample_index"].head(3).to_list() == [0, 1, 2]
    assert exp1["source_row_number"].head(3).to_list() == [2, 3, 4]


def test_steel_fault_class_derivation_is_deterministic(normalized_outputs: dict[str, list[Path]]) -> None:
    frame = pl.read_parquet(normalized_outputs["steel"][0])
    assert frame.height == 1941
    statuses = set(frame["fault_label_status"].unique().to_list())
    assert statuses <= {"single_active_label", "no_active_label", "multiple_active_labels"}
    single = frame.filter(pl.col("fault_label_status") == "single_active_label")
    assert single["fault_class"].null_count() == 0


def test_industrial_malformed_dates_are_retained(normalized_outputs: dict[str, list[Path]]) -> None:
    frame = pl.scan_parquet(normalized_outputs["industrial"][0]).filter(
        pl.col("scheduled_start_date_raw") == "2021-06-41"
    ).limit(1).collect()
    assert frame.height == 1
    assert frame["scheduled_start_date_raw"][0] == "2021-06-41"
    assert frame["scheduled_start_date"][0] is None
    assert frame["scheduled_start_date_valid"][0] is False


def test_sensor_tags_is_catalog_not_telemetry(normalized_outputs: dict[str, list[Path]]) -> None:
    frame = pl.scan_parquet(normalized_outputs["industrial"][1]).limit(5).collect()
    assert "tag_name" in frame.columns
    assert "source_domain" in frame.columns
    assert set(frame["source_domain"].to_list()) == {"equipment_metadata.sensor_tag_catalog"}
    assert "measurement_value" not in frame.columns
    assert "timestamp" not in frame.columns


def test_repeated_pipeline_execution_is_idempotent(normalized_outputs: dict[str, list[Path]]) -> None:
    before = {
        path: (pl.read_parquet(path).height, sha256_file(path))
        for paths in normalized_outputs.values()
        for path in paths
    }
    run_adapters(None, validate_only=False)
    after = {
        path: (pl.read_parquet(path).height, sha256_file(path))
        for paths in normalized_outputs.values()
        for path in paths
    }
    assert before == after


def test_provenance_exists_on_every_normalized_record(normalized_outputs: dict[str, list[Path]]) -> None:
    required = {
        "source_dataset",
        "source_file",
        "source_record_id",
        "source_row_number",
        "source_domain",
        "is_external_dataset",
    }
    for paths in normalized_outputs.values():
        for path in paths:
            frame = pl.read_parquet(path)
            assert required <= set(frame.columns)
            has_null = frame.select(
                pl.any_horizontal([pl.col(column).is_null() for column in required]).any()
            ).item()
            assert has_null is False
            assert bool(frame["is_external_dataset"].all())


def test_manifests_and_report_created(normalized_outputs: dict[str, list[Path]]) -> None:
    assert (MANIFESTS_ROOT / "transformations.json").is_file()
    assert (MANIFESTS_ROOT / "normalized_datasets.json").is_file()
    assert (DATASETS_ROOT / "reports" / "NORMALIZATION_REPORT.md").is_file()

