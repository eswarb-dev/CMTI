from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

from .config import CASES_PATH, END, MANIFEST_PATH, OUTPUT_ROOT, SOURCE_DATASET, START
from .generator import TABLES

TS_FMT = "%Y-%m-%dT%H:%M:%S%z"

def load_frames() -> dict[str, pl.DataFrame]:
    return {name: pl.read_parquet(OUTPUT_ROOT / f"{name}.parquet") for name in TABLES}


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def unique(frame: pl.DataFrame, column: str) -> None:
    assert_true(frame[column].n_unique() == frame.height, f"{column} values are not unique")


def compute_case_metrics(frames: dict[str, pl.DataFrame], cases: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    from datetime import timedelta

    telemetry = frames["telemetry"]
    quality = frames["quality_inspections"]
    production = frames["production_orders"]
    alarms = frames["machine_alarms"]
    metrics: dict[str, dict[str, Any]] = {}
    ts = lambda dt: dt.isoformat()

    baseline = telemetry.filter(
        (pl.col("machine_id") == "CNC-05")
        & (pl.col("timestamp") >= ts(START))
        & (pl.col("timestamp") < ts(START + timedelta(days=10)))
    )["vibration_mm_s"].mean()
    scenario = telemetry.filter(
        (pl.col("machine_id") == "CNC-05")
        & (pl.col("timestamp") >= ts(START + timedelta(days=16)))
        & (pl.col("timestamp") <= ts(START + timedelta(days=29)))
    )["vibration_mm_s"].mean()
    q_before = quality.filter(
        (pl.col("machine_id") == "CNC-05")
        & (pl.col("product_id") == "SHAFT-A")
        & (pl.col("parameter") == "diameter_mm")
        & (pl.col("timestamp") < ts(START + timedelta(days=21)))
    )["measured_value"].mean()
    q_after = quality.filter(
        (pl.col("machine_id") == "CNC-05")
        & (pl.col("product_id") == "SHAFT-A")
        & (pl.col("parameter") == "diameter_mm")
        & (pl.col("timestamp") >= ts(START + timedelta(days=26)))
        & (pl.col("timestamp") <= ts(START + timedelta(days=29, hours=23)))
    )["measured_value"].mean()
    prod_before = production.filter(
        (pl.col("machine_id") == "CNC-05")
        & (pl.col("product_id") == "SHAFT-A")
        & (pl.col("actual_start_time") < ts(START + timedelta(days=21)))
    )["reject_rate"].mean()
    prod_after = production.filter(
        (pl.col("machine_id") == "CNC-05")
        & (pl.col("product_id") == "SHAFT-A")
        & (pl.col("actual_start_time") >= ts(START + timedelta(days=27)))
        & (pl.col("actual_start_time") <= ts(START + timedelta(days=29, hours=23)))
    )["reject_rate"].mean()
    metrics["CASE-001"] = {
        "baseline_vibration_mean": round(float(baseline), 4),
        "scenario_vibration_mean": round(float(scenario), 4),
        "diameter_before_mean": round(float(q_before), 5),
        "diameter_after_mean": round(float(q_after), 5),
        "reject_rate_before": round(float(prod_before), 5),
        "reject_rate_after": round(float(prod_after), 5),
    }

    case2 = quality.filter(
        (pl.col("product_id") == "SHAFT-A")
        & (pl.col("timestamp") >= ts(START + timedelta(days=31)))
        & (pl.col("timestamp") <= ts(START + timedelta(days=36, hours=23)))
    )
    metrics["CASE-002"] = {"quality_failures": int(case2.filter(pl.col("result") == "FAIL").height)}

    temp_before = telemetry.filter(
        (pl.col("machine_id") == "CNC-03")
        & (pl.col("timestamp") >= ts(START))
        & (pl.col("timestamp") < ts(START + timedelta(days=9)))
    )["temperature_c"].mean()
    temp_after = telemetry.filter(
        (pl.col("machine_id") == "CNC-03")
        & (pl.col("timestamp") >= ts(START + timedelta(days=15)))
        & (pl.col("timestamp") <= ts(START + timedelta(days=18, hours=23)))
    )["temperature_c"].mean()
    metrics["CASE-003"] = {
        "baseline_temperature_mean": round(float(temp_before), 4),
        "scenario_temperature_mean": round(float(temp_after), 4),
    }

    r_before = production.filter(
        (pl.col("product_id") == "GEAR-B")
        & (pl.col("actual_start_time") < ts(START + timedelta(days=38)))
    )["reject_rate"].mean()
    r_after = production.filter(
        (pl.col("product_id") == "GEAR-B")
        & (pl.col("actual_start_time") >= ts(START + timedelta(days=38)))
        & (pl.col("actual_start_time") <= ts(START + timedelta(days=43, hours=23)))
    )["reject_rate"].mean()
    metrics["CASE-004"] = {"reject_rate_before": round(float(r_before), 5), "reject_rate_after": round(float(r_after), 5)}

    recur = alarms.filter((pl.col("machine_id") == "CNC-03") & (pl.col("alarm_code") == "ALM-SERVO-03"))
    metrics["CASE-005"] = {"recurring_alarm_count": recur.height, "alarm_code": "ALM-SERVO-03"}
    return metrics


def validate() -> dict[str, Any]:
    for name in TABLES:
        assert_true((OUTPUT_ROOT / f"{name}.parquet").is_file(), f"missing {name}.parquet")
    assert_true(CASES_PATH.is_file(), "missing demo_cases.json")
    assert_true(MANIFEST_PATH.is_file(), "missing demo_factory.json")

    frames = load_frames()
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    machines = set(frames["machines"]["machine_id"].to_list())
    products = set(frames["products"]["product_id"].to_list())
    batches = set(frames["production_orders"]["batch_id"].to_list())

    for name, frame in frames.items():
        assert_true(bool(frame["is_synthetic"].all()), f"{name} contains non-synthetic records")
        assert_true(set(frame["source_dataset"].unique().to_list()) == {SOURCE_DATASET}, f"{name} source_dataset mismatch")
        assert_true("source_record_id" not in frame.columns, f"{name} contains external source_record_id")

    unique(frames["machines"], "machine_id")
    unique(frames["products"], "product_id")
    unique(frames["production_orders"], "production_id")
    unique(frames["production_orders"], "batch_id")
    unique(frames["quality_inspections"], "inspection_id")
    unique(frames["maintenance_logs"], "maintenance_id")
    unique(frames["machine_alarms"], "alarm_id")
    unique(frames["telemetry"], "telemetry_id")

    prod = frames["production_orders"]
    assert_true(set(prod["machine_id"].to_list()) <= machines, "production machine FK failure")
    assert_true(set(prod["product_id"].to_list()) <= products, "production product FK failure")
    assert_true(bool(((prod["accepted_quantity"] + prod["rejected_quantity"]) == prod["actual_quantity"]).all()), "quantity invariant failed")
    assert_true(bool((prod["actual_quantity"] >= 0).all() and (prod["planned_quantity"] >= 0).all()), "negative production quantity")
    for row in prod.iter_rows(named=True):
        assert_true(parse_ts(row["actual_start_time"]) <= parse_ts(row["actual_end_time"]), "production start/end failure")
        assert_true(abs(row["reject_rate"] - row["rejected_quantity"] / row["actual_quantity"]) < 0.00001, "reject_rate mismatch")

    qi = frames["quality_inspections"]
    assert_true(set(qi["batch_id"].to_list()) <= batches, "quality batch FK failure")
    assert_true(set(qi["machine_id"].to_list()) <= machines, "quality machine FK failure")
    assert_true(set(qi["product_id"].to_list()) <= products, "quality product FK failure")
    prod_by_batch = {row["batch_id"]: row for row in prod.iter_rows(named=True)}
    for row in qi.iter_rows(named=True):
        expected = "PASS" if row["lsl"] <= row["measured_value"] <= row["usl"] else "FAIL"
        assert_true(row["result"] == expected, "quality PASS/FAIL mismatch")
        p = prod_by_batch[row["batch_id"]]
        assert_true(parse_ts(p["actual_start_time"]) <= parse_ts(row["timestamp"]) <= parse_ts(p["actual_end_time"]), "inspection outside batch window")

    ml = frames["maintenance_logs"]
    assert_true(set(ml["machine_id"].to_list()) <= machines, "maintenance machine FK failure")
    for row in ml.iter_rows(named=True):
        assert_true(parse_ts(row["created_at"]) <= parse_ts(row["started_at"]) <= parse_ts(row["completed_at"]), "maintenance timeline failure")

    alarms = frames["machine_alarms"]
    assert_true(set(alarms["machine_id"].to_list()) <= machines, "alarm machine FK failure")
    related = [value for value in alarms["related_batch_id"].to_list() if value is not None]
    assert_true(set(related) <= batches, "alarm related batch FK failure")
    for row in alarms.iter_rows(named=True):
        assert_true(parse_ts(row["timestamp"]) <= parse_ts(row["acknowledged_at"]), "alarm ack timeline failure")

    tel = frames["telemetry"]
    assert_true(set(tel["machine_id"].to_list()) <= machines, "telemetry machine FK failure")
    assert_true(bool((tel["rpm"] >= 0).all()), "negative rpm")
    assert_true(bool((tel["vibration_mm_s"] >= 0).all()), "negative vibration")
    assert_true(bool(((tel["temperature_c"] >= 15) & (tel["temperature_c"] <= 95)).all()), "temperature bounds")
    assert_true(bool((tel["current_a"] >= 0).all()), "negative current")
    assert_true(bool(((tel["load_pct"] >= 0) & (tel["load_pct"] <= 100)).all()), "load bounds")
    assert_true(bool((tel["spindle_power_kw"] >= 0).all()), "negative power")
    for value in tel["timestamp"].head(5).to_list():
        parse_ts(value)

    metrics = compute_case_metrics(frames, cases)
    assert_true(metrics["CASE-001"]["scenario_vibration_mean"] > metrics["CASE-001"]["baseline_vibration_mean"] * 1.5, "CASE-001 vibration trend weak")
    assert_true(metrics["CASE-001"]["diameter_after_mean"] > metrics["CASE-001"]["diameter_before_mean"], "CASE-001 quality drift weak")
    assert_true(metrics["CASE-001"]["reject_rate_after"] > metrics["CASE-001"]["reject_rate_before"] * 2, "CASE-001 rejection increase weak")
    assert_true(any(c["case_id"] == "CASE-001" and c["relevant_record_ids"]["alarms"] for c in cases), "CASE-001 missing alarms")
    assert_true(any(c["case_id"] == "CASE-001" and c["relevant_record_ids"]["maintenance"] for c in cases), "CASE-001 missing maintenance")
    assert_true(any(c["case_id"] == "CASE-001" and c["relevant_record_ids"]["quality"] for c in cases), "CASE-001 missing quality")
    assert_true(metrics["CASE-003"]["scenario_temperature_mean"] > metrics["CASE-003"]["baseline_temperature_mean"] + 5, "CASE-003 thermal trend weak")
    assert_true(metrics["CASE-004"]["reject_rate_after"] > metrics["CASE-004"]["reject_rate_before"] * 2, "CASE-004 rejection change weak")
    assert_true(metrics["CASE-005"]["recurring_alarm_count"] >= 3, "CASE-005 recurring alarms missing")

    for case in cases:
        assert_true("hidden_simulated_cause" in case, "case missing hidden ground truth")
    for name, frame in frames.items():
        for column in frame.columns:
            if column != "source_dataset":
                assert_true(not column.startswith("hidden_simulated_cause"), f"{name} leaks hidden cause")
        assert_true(not any(str(v).startswith("kaggle_") for v in frame["source_dataset"].unique().to_list()), f"{name} has external lineage")

    assert_true(START <= parse_ts(tel["timestamp"].min()) <= END, "telemetry min outside range")
    assert_true(START <= parse_ts(tel["timestamp"].max()) <= END, "telemetry max outside range")
    return {"status": "passed", "metrics": metrics}

