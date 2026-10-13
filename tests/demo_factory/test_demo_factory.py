from __future__ import annotations

import json
import sys
from pathlib import Path

import polars as pl
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.demo_factory.config import CASES_PATH, MANIFEST_PATH, OUTPUT_ROOT, SOURCE_DATASET
from scripts.demo_factory.generator import TABLES, generate, sha256_file
from scripts.demo_factory.validators import compute_case_metrics, validate


@pytest.fixture(scope="session")
def demo_data() -> tuple[dict[str, pl.DataFrame], list[dict]]:
    generate()
    validate()
    frames = {name: pl.read_parquet(OUTPUT_ROOT / f"{name}.parquet") for name in TABLES}
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    return frames, cases


def test_deterministic_regeneration(demo_data: tuple[dict[str, pl.DataFrame], list[dict]]) -> None:
    first = {name: sha256_file(OUTPUT_ROOT / f"{name}.parquet") for name in TABLES}
    first_cases = CASES_PATH.read_text(encoding="utf-8")
    first_manifest = MANIFEST_PATH.read_text(encoding="utf-8")
    generate()
    second = {name: sha256_file(OUTPUT_ROOT / f"{name}.parquet") for name in TABLES}
    assert first == second
    assert first_cases == CASES_PATH.read_text(encoding="utf-8")
    assert first_manifest == MANIFEST_PATH.read_text(encoding="utf-8")


def test_foreign_keys_and_unique_ids(demo_data: tuple[dict[str, pl.DataFrame], list[dict]]) -> None:
    frames, _ = demo_data
    machines = set(frames["machines"]["machine_id"].to_list())
    products = set(frames["products"]["product_id"].to_list())
    batches = set(frames["production_orders"]["batch_id"].to_list())
    for table, key in [
        ("machines", "machine_id"),
        ("products", "product_id"),
        ("production_orders", "production_id"),
        ("quality_inspections", "inspection_id"),
        ("maintenance_logs", "maintenance_id"),
        ("machine_alarms", "alarm_id"),
        ("telemetry", "telemetry_id"),
    ]:
        assert frames[table][key].n_unique() == frames[table].height
    assert set(frames["production_orders"]["machine_id"].to_list()) <= machines
    assert set(frames["production_orders"]["product_id"].to_list()) <= products
    assert set(frames["quality_inspections"]["batch_id"].to_list()) <= batches
    assert set(frames["telemetry"]["machine_id"].to_list()) <= machines


def test_quality_pass_fail_and_production_quantities(demo_data: tuple[dict[str, pl.DataFrame], list[dict]]) -> None:
    frames, _ = demo_data
    qi = frames["quality_inspections"]
    expected = qi.with_columns(
        pl.when((pl.col("lsl") <= pl.col("measured_value")) & (pl.col("measured_value") <= pl.col("usl")))
        .then(pl.lit("PASS"))
        .otherwise(pl.lit("FAIL"))
        .alias("expected")
    )
    assert bool((expected["result"] == expected["expected"]).all())
    prod = frames["production_orders"]
    assert bool(((prod["accepted_quantity"] + prod["rejected_quantity"]) == prod["actual_quantity"]).all())
    assert bool((prod["planned_quantity"] >= 0).all())
    assert bool((prod["actual_quantity"] >= 0).all())


def test_telemetry_bounds_and_timeline_integrity(demo_data: tuple[dict[str, pl.DataFrame], list[dict]]) -> None:
    frames, _ = demo_data
    tel = frames["telemetry"]
    assert bool((tel["rpm"] >= 0).all())
    assert bool((tel["vibration_mm_s"] >= 0).all())
    assert bool(((tel["temperature_c"] >= 15) & (tel["temperature_c"] <= 95)).all())
    assert bool(((tel["load_pct"] >= 0) & (tel["load_pct"] <= 100)).all())
    assert bool((tel["spindle_power_kw"] >= 0).all())
    for row in frames["maintenance_logs"].iter_rows(named=True):
        assert row["created_at"] <= row["started_at"] <= row["completed_at"]
    for row in frames["production_orders"].iter_rows(named=True):
        assert row["actual_start_time"] <= row["actual_end_time"]


def test_scenario_presence_and_trends(demo_data: tuple[dict[str, pl.DataFrame], list[dict]]) -> None:
    frames, cases = demo_data
    assert {case["case_id"] for case in cases} == {"CASE-001", "CASE-002", "CASE-003", "CASE-004", "CASE-005"}
    metrics = compute_case_metrics(frames, cases)
    assert metrics["CASE-001"]["scenario_vibration_mean"] > metrics["CASE-001"]["baseline_vibration_mean"] * 1.5
    assert metrics["CASE-001"]["diameter_after_mean"] > metrics["CASE-001"]["diameter_before_mean"]
    assert metrics["CASE-001"]["reject_rate_after"] > metrics["CASE-001"]["reject_rate_before"] * 2
    assert metrics["CASE-003"]["scenario_temperature_mean"] > metrics["CASE-003"]["baseline_temperature_mean"] + 5
    assert metrics["CASE-004"]["reject_rate_after"] > metrics["CASE-004"]["reject_rate_before"] * 2
    assert metrics["CASE-005"]["recurring_alarm_count"] >= 3


def test_ground_truth_separation_and_synthetic_provenance(demo_data: tuple[dict[str, pl.DataFrame], list[dict]]) -> None:
    frames, cases = demo_data
    assert all(case["hidden_simulated_cause"] for case in cases)
    for table, frame in frames.items():
        assert "hidden_simulated_cause" not in frame.columns
        assert "source_record_id" not in frame.columns
        assert bool(frame["is_synthetic"].all())
        assert set(frame["source_dataset"].unique().to_list()) == {SOURCE_DATASET}
        assert not any(str(value).startswith("kaggle_") for value in frame["source_dataset"].unique().to_list())


def test_validator_passes(demo_data: tuple[dict[str, pl.DataFrame], list[dict]]) -> None:
    assert validate()["status"] == "passed"

