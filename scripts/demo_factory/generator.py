from __future__ import annotations

import hashlib
import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from .config import (
    CASES_PATH,
    END,
    FACTORY_NAME,
    GENERATOR_VERSION,
    MACHINES,
    MANIFEST_PATH,
    OUTPUT_ROOT,
    PRODUCTS,
    PROFILES,
    REPORT_PATH,
    SCHEMA_VERSION,
    SEED,
    SOURCE_DATASET,
    START,
    SYNTHETIC_ROOT,
    TELEMETRY_INTERVAL_MIN,
    TIMEZONE_NAME,
)
from .distributions import bounded_noise, clamp, reject_counts
from .scenarios import CASE_WINDOWS, case001_vibration_multiplier, case003_temperature_add


TABLES = [
    "machines",
    "products",
    "production_orders",
    "maintenance_logs",
    "quality_inspections",
    "machine_alarms",
    "telemetry",
]


def iso(dt: datetime) -> str:
    return dt.isoformat()


def add_synthetic(row: dict[str, Any]) -> dict[str, Any]:
    row["is_synthetic"] = True
    row["source_dataset"] = SOURCE_DATASET
    return row


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_table(name: str, rows: list[dict[str, Any]]) -> Path:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_ROOT / f"{name}.parquet"
    if path.exists():
        path.unlink()
    pl.DataFrame(rows, infer_schema_length=None).write_parquet(path)
    return path


class DemoFactoryGenerator:
    def __init__(self, seed: int = SEED) -> None:
        self.seed = seed
        self.rng = random.Random(seed)
        self.case_records: dict[str, dict[str, list[str]]] = {
            case_id: {kind: [] for kind in ["production", "quality", "maintenance", "alarms", "telemetry"]}
            for case_id in CASE_WINDOWS
        }

    def machines(self) -> list[dict[str, Any]]:
        return [add_synthetic(dict(row)) for row in MACHINES]

    def products(self) -> list[dict[str, Any]]:
        return [add_synthetic(dict(row)) for row in PRODUCTS]

    def production_orders(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        machine_cycle = ["CNC-01", "CNC-03", "CNC-05"]
        product_cycle = ["SHAFT-A", "GEAR-B", "HOUSING-C"]
        pid = 1
        current = START
        while pid <= 180:
            machine = machine_cycle[(pid - 1) % len(machine_cycle)]
            product = product_cycle[(pid + (0 if machine != "CNC-05" else 1)) % len(product_cycle)]
            if 21 <= (current.date() - START.date()).days + 1 <= 29 and machine == "CNC-05":
                product = "SHAFT-A"
            if 31 <= (current.date() - START.date()).days + 1 <= 36:
                product = "SHAFT-A"
                machine = "CNC-01"
            if 38 <= (current.date() - START.date()).days + 1 <= 43:
                product = "GEAR-B"
                machine = "CNC-01" if pid % 2 else "CNC-05"
            planned = 80 + (pid % 5) * 12
            actual = planned - (pid % 4)
            day = (current.date() - START.date()).days + 1
            reject_rate = 0.025
            if machine == "CNC-05" and product == "SHAFT-A" and 27 <= day <= 29:
                reject_rate = 0.14
            elif 38 <= day <= 43 and product == "GEAR-B":
                reject_rate = 0.12
            elif 31 <= day <= 36 and product == "SHAFT-A":
                reject_rate = 0.10
            accepted, rejected = reject_counts(actual, reject_rate)
            start = current + timedelta(minutes=(pid % 3) * 10)
            cycle = next(p["nominal_cycle_time_sec"] for p in PRODUCTS if p["product_id"] == product)
            end = start + timedelta(seconds=actual * cycle)
            batch_id = f"BATCH-202609-{pid:03d}"
            production_id = f"PRODORD-{pid:06d}"
            row = add_synthetic(
                {
                    "production_id": production_id,
                    "batch_id": batch_id,
                    "machine_id": machine,
                    "product_id": product,
                    "planned_quantity": planned,
                    "actual_quantity": actual,
                    "accepted_quantity": accepted,
                    "rejected_quantity": rejected,
                    "reject_rate": round(rejected / actual, 5),
                    "planned_start_time": iso(start - timedelta(minutes=30)),
                    "actual_start_time": iso(start),
                    "actual_end_time": iso(end),
                    "cycle_time_sec": cycle,
                    "shift": ["A", "B", "C"][pid % 3],
                    "production_status": "COMPLETE",
                }
            )
            rows.append(row)
            if machine == "CNC-05" and product == "SHAFT-A" and 21 <= day <= 29:
                self.case_records["CASE-001"]["production"].append(production_id)
            if product == "SHAFT-A" and 31 <= day <= 36:
                self.case_records["CASE-002"]["production"].append(production_id)
            if product == "GEAR-B" and 38 <= day <= 43:
                self.case_records["CASE-004"]["production"].append(production_id)
            current += timedelta(hours=6)
            pid += 1
        return rows

    def quality_inspections(self, production_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        qid = 1
        for prod in production_rows:
            start = datetime.fromisoformat(prod["actual_start_time"])
            end = datetime.fromisoformat(prod["actual_end_time"])
            count = 5
            for idx in range(count):
                parameter = ["diameter_mm", "runout_mm", "surface_finish_ra_um"][idx % 3]
                if parameter == "diameter_mm":
                    nominal, lsl, usl = 25.0, 24.98, 25.02
                    measured = bounded_noise(self.rng, nominal, 0.008, 24.96, 25.06, 5)
                elif parameter == "runout_mm":
                    nominal, lsl, usl = 0.0, 0.0, 0.03
                    measured = bounded_noise(self.rng, 0.014, 0.008, 0.0, 0.07, 5)
                else:
                    nominal, lsl, usl = 1.2, 0.0, 1.6
                    measured = bounded_noise(self.rng, nominal, 0.15, 0.6, 2.1, 5)
                day = (start.date() - START.date()).days + 1
                if prod["machine_id"] == "CNC-05" and prod["product_id"] == "SHAFT-A" and parameter == "diameter_mm":
                    if 21 <= day <= 25:
                        measured = round(25.012 + (day - 21) * 0.0015 + idx * 0.0002, 5)
                    elif 26 <= day <= 29:
                        measured = round(25.024 + (day - 26) * 0.002 + idx * 0.0004, 5)
                if prod["product_id"] == "SHAFT-A" and 31 <= day <= 36 and parameter == "diameter_mm":
                    measured = round(25.023 + (idx * 0.001), 5)
                if prod["product_id"] == "GEAR-B" and 38 <= day <= 43 and parameter == "surface_finish_ra_um":
                    measured = round(1.72 + idx * 0.03, 5)
                result = "PASS" if lsl <= measured <= usl else "FAIL"
                timestamp = start + (end - start) * ((idx + 1) / (count + 1))
                inspection_id = f"QI-{qid:06d}"
                row = add_synthetic(
                    {
                        "inspection_id": inspection_id,
                        "batch_id": prod["batch_id"],
                        "machine_id": prod["machine_id"],
                        "product_id": prod["product_id"],
                        "timestamp": iso(timestamp),
                        "parameter": parameter,
                        "nominal_value": nominal,
                        "lsl": lsl,
                        "usl": usl,
                        "measured_value": measured,
                        "result": result,
                        "defect_type": None if result == "PASS" else ("DIMENSIONAL" if parameter != "surface_finish_ra_um" else "SURFACE_FINISH"),
                        "inspection_method": "Synthetic CMM" if parameter != "surface_finish_ra_um" else "Synthetic surface gauge",
                    }
                )
                rows.append(row)
                if prod["production_id"] in self.case_records["CASE-001"]["production"]:
                    self.case_records["CASE-001"]["quality"].append(inspection_id)
                if prod["production_id"] in self.case_records["CASE-002"]["production"]:
                    self.case_records["CASE-002"]["quality"].append(inspection_id)
                if prod["production_id"] in self.case_records["CASE-004"]["production"]:
                    self.case_records["CASE-004"]["quality"].append(inspection_id)
                qid += 1
        return rows

    def telemetry(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        tid = 1
        current = START
        while current <= END:
            for machine_id, profile in PROFILES.items():
                rpm = bounded_noise(self.rng, profile.rpm, 95, 0, 5000)
                vibration = bounded_noise(self.rng, profile.vibration, 0.18, 0, 12)
                temp = bounded_noise(self.rng, profile.temperature, 2.2, 15, 95)
                current_a = bounded_noise(self.rng, profile.current, 2.0, 0, 80)
                load = bounded_noise(self.rng, profile.load, 8.0, 0, 100)
                if machine_id == "CNC-05":
                    multiplier = case001_vibration_multiplier(current)
                    vibration = clamp(vibration * multiplier, 0, 12)
                    if multiplier > 1.2 and tid % 9 == 0:
                        self.case_records["CASE-001"]["telemetry"].append(f"TEL-{tid:06d}")
                if machine_id == "CNC-03":
                    add = case003_temperature_add(current)
                    temp = clamp(temp + add, 15, 95)
                    current_a = clamp(current_a + add * 0.35, 0, 80)
                    load = clamp(load + add * 0.55, 0, 100)
                    if add > 4 and tid % 11 == 0:
                        self.case_records["CASE-003"]["telemetry"].append(f"TEL-{tid:06d}")
                row = add_synthetic(
                    {
                        "telemetry_id": f"TEL-{tid:06d}",
                        "machine_id": machine_id,
                        "timestamp": iso(current),
                        "rpm": rpm,
                        "vibration_mm_s": vibration,
                        "temperature_c": temp,
                        "current_a": current_a,
                        "load_pct": load,
                        "spindle_power_kw": clamp(profile.power * load / 65.0, 0, 30),
                    }
                )
                rows.append(row)
                tid += 1
            current += timedelta(minutes=TELEMETRY_INTERVAL_MIN)
        return rows

    def maintenance_logs(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        mid = 1
        for day in range(0, 45, 2):
            for machine in ["CNC-01", "CNC-03", "CNC-05"]:
                created = START + timedelta(days=day, hours=1)
                started = created + timedelta(hours=2)
                completed = started + timedelta(minutes=45 + (mid % 5) * 5)
                row = add_synthetic(
                    {
                        "maintenance_id": f"MNT-{mid:06d}",
                        "machine_id": machine,
                        "created_at": iso(created),
                        "started_at": iso(started),
                        "completed_at": iso(completed),
                        "maintenance_type": "PREVENTIVE",
                        "symptom": "Routine inspection interval",
                        "component": "General machine condition",
                        "failure_code": None,
                        "inspection_findings": "No abnormal condition recorded.",
                        "action_taken": "Routine checks and housekeeping completed.",
                        "planned_downtime_min": 60,
                        "actual_downtime_min": int((completed - started).total_seconds() / 60),
                        "status": "COMPLETE",
                    }
                )
                rows.append(row)
                mid += 1
        scenario_rows = [
            ("CNC-05", 20, "CONDITION_BASED", "Elevated spindle vibration observed", "Spindle/tool-holder assembly", "VIBRATION_TREND", "Inspection found increasing vibration indicators; no confirmed root cause recorded.", "Checked tool holder seating and scheduled follow-up monitoring.", "CASE-001"),
            ("CNC-05", 29, "INSPECTION", "Repeat vibration alarm and quality drift review", "Spindle/tool-holder assembly", "VIBRATION_REPEAT", "Indicators support deeper spindle alignment review; diagnosis not confirmed in user-visible record.", "Escalated for precision inspection.", "CASE-001"),
            ("CNC-03", 18, "CONDITION_BASED", "Rising temperature trend", "Cooling and spindle load context", "TEMP_TREND", "Thermal trend confirmed under load; no root cause proven from telemetry alone.", "Cleaned vents and scheduled coolant review.", "CASE-003"),
            ("CNC-01", 36, "INSPECTION", "SHAFT-A dimensional rejects", "Fixture and measurement setup", "QUALITY_REVIEW", "Inspection requested after repeated dimensional failures.", "Fixture setup checked and production hold reviewed.", "CASE-002"),
            ("CNC-01", 43, "CORRECTIVE", "GEAR-B rejection-rate increase", "Process setup", "REJECT_RATE", "Production and inspection data showed rejection increase.", "Adjusted setup and requested quality confirmation.", "CASE-004"),
            ("CNC-03", 34, "INSPECTION", "Recurring servo alarm family", "Servo drive context", "ALARM_RECUR", "Recurring synthetic servo alarms reviewed.", "Connector inspection and monitoring scheduled.", "CASE-005"),
        ]
        for machine, day, mtype, symptom, component, code, findings, action, case_id in scenario_rows:
            created = START + timedelta(days=day, hours=8)
            started = created + timedelta(minutes=45)
            completed = started + timedelta(minutes=90)
            maintenance_id = f"MNT-{mid:06d}"
            rows.append(
                add_synthetic(
                    {
                        "maintenance_id": maintenance_id,
                        "machine_id": machine,
                        "created_at": iso(created),
                        "started_at": iso(started),
                        "completed_at": iso(completed),
                        "maintenance_type": mtype,
                        "symptom": symptom,
                        "component": component,
                        "failure_code": code,
                        "inspection_findings": findings,
                        "action_taken": action,
                        "planned_downtime_min": 90,
                        "actual_downtime_min": 90,
                        "status": "COMPLETE",
                    }
                )
            )
            self.case_records[case_id]["maintenance"].append(maintenance_id)
            mid += 1
        return rows

    def alarms(self, production_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        aid = 1
        for day in range(0, 45):
            machine = ["CNC-01", "CNC-03", "CNC-05"][day % 3]
            ts = START + timedelta(days=day, hours=10)
            rows.append(
                add_synthetic(
                    {
                        "alarm_id": f"ALM-{aid:06d}",
                        "machine_id": machine,
                        "timestamp": iso(ts),
                        "alarm_code": "ALM-INFO-00",
                        "severity": "INFO",
                        "category": "INFORMATIONAL",
                        "description": "Synthetic routine operator notification.",
                        "acknowledged": True,
                        "acknowledged_at": iso(ts + timedelta(minutes=5)),
                        "related_batch_id": None,
                    }
                )
            )
            aid += 1
        scenario_alarms = [
            ("CNC-05", 16, "ALM-VIB-01", "WARNING", "VIBRATION", "Synthetic spindle vibration warning.", "CASE-001"),
            ("CNC-05", 29, "ALM-VIB-01", "CRITICAL", "VIBRATION", "Synthetic repeat spindle vibration alarm.", "CASE-001"),
            ("CNC-03", 18, "ALM-TEMP-02", "WARNING", "THERMAL", "Synthetic temperature trend alarm.", "CASE-003"),
            ("CNC-03", 24, "ALM-SERVO-03", "WARNING", "SERVO", "Synthetic recurring servo alarm.", "CASE-005"),
            ("CNC-03", 27, "ALM-SERVO-03", "WARNING", "SERVO", "Synthetic recurring servo alarm.", "CASE-005"),
            ("CNC-03", 31, "ALM-SERVO-03", "CRITICAL", "SERVO", "Synthetic recurring servo alarm escalation.", "CASE-005"),
        ]
        for machine, day, code, sev, category, desc, case_id in scenario_alarms:
            ts = START + timedelta(days=day, hours=9)
            related = None
            if case_id == "CASE-001":
                candidates = [p for p in production_rows if p["machine_id"] == "CNC-05" and p["product_id"] == "SHAFT-A"]
                related = candidates[min(len(candidates) - 1, max(0, day - 21))]["batch_id"]
            alarm_id = f"ALM-{aid:06d}"
            rows.append(
                add_synthetic(
                    {
                        "alarm_id": alarm_id,
                        "machine_id": machine,
                        "timestamp": iso(ts),
                        "alarm_code": code,
                        "severity": sev,
                        "category": category,
                        "description": desc,
                        "acknowledged": True,
                        "acknowledged_at": iso(ts + timedelta(minutes=12)),
                        "related_batch_id": related,
                    }
                )
            )
            self.case_records[case_id]["alarms"].append(alarm_id)
            aid += 1
        return rows

    def demo_cases(self) -> list[dict[str, Any]]:
        specs = {
            "CASE-001": ("CNC-05 spindle vibration increase", "Why did CNC-05 SHAFT-A rejects increase after vibration alarms?", ["MAINTENANCE", "QUALITY", "PRODUCTION"], ["CNC-05"], ["SHAFT-A"], "spindle bearing degradation"),
            "CASE-002": ("SHAFT-A dimensional deviation", "Which evidence explains SHAFT-A dimensional failures?", ["QUALITY", "PRODUCTION"], ["CNC-01"], ["SHAFT-A"], "fixture setup drift"),
            "CASE-003": ("CNC-03 thermal/overheating trend", "Is CNC-03 showing a thermal trend that needs maintenance review?", ["MAINTENANCE"], ["CNC-03"], [], "cooling airflow restriction"),
            "CASE-004": ("production rejection-rate increase", "Which batches show the GEAR-B rejection-rate increase?", ["PRODUCTION", "QUALITY"], ["CNC-01", "CNC-05"], ["GEAR-B"], "process setup drift"),
            "CASE-005": ("recurring machine alarm", "What history exists for recurring CNC-03 servo alarms?", ["MAINTENANCE"], ["CNC-03"], [], "intermittent servo connector issue"),
        }
        cases = []
        for case_id, (title, query, domains, machines, products, hidden) in specs.items():
            start, end = CASE_WINDOWS[case_id]
            record_ids = {kind: sorted(ids) for kind, ids in self.case_records[case_id].items()}
            cases.append(
                {
                    "case_id": case_id,
                    "title": title,
                    "description": f"Synthetic evaluation case for {title}.",
                    "query": query,
                    "expected_domains": domains,
                    "expected_machine_ids": machines,
                    "expected_product_ids": products,
                    "relevant_record_ids": record_ids,
                    "relevant_time_window": {"start": iso(start), "end": iso(end)},
                    "expected_evidence_types": [kind for kind, ids in record_ids.items() if ids],
                    "hidden_simulated_cause": hidden,
                    "expected_observations": [
                        "Evidence should be combined across listed records.",
                        "Hidden simulated cause is evaluation-only and must not be loaded by application data paths.",
                    ],
                    "evaluation_notes": "Synthetic ground truth separated from Parquet application records.",
                }
            )
        return cases

    def generate(self) -> dict[str, Any]:
        OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        SYNTHETIC_ROOT.mkdir(parents=True, exist_ok=True)
        rows = {
            "machines": self.machines(),
            "products": self.products(),
        }
        rows["production_orders"] = self.production_orders()
        rows["quality_inspections"] = self.quality_inspections(rows["production_orders"])
        rows["telemetry"] = self.telemetry()
        rows["maintenance_logs"] = self.maintenance_logs()
        rows["machine_alarms"] = self.alarms(rows["production_orders"])
        paths = {name: write_table(name, table_rows) for name, table_rows in rows.items()}
        cases = self.demo_cases()
        CASES_PATH.write_text(json.dumps(cases, indent=2), encoding="utf-8")
        manifest = self.manifest(rows, paths, cases)
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(self.report(rows, cases), encoding="utf-8")
        return manifest

    def manifest(self, rows: dict[str, list[dict[str, Any]]], paths: dict[str, Path], cases: list[dict[str, Any]]) -> dict[str, Any]:
        tables = {}
        for name, path in paths.items():
            frame = pl.read_parquet(path)
            tables[name] = {"path": str(path), "format": "parquet", "rows": frame.height, "columns": len(frame.columns), "sha256": sha256_file(path)}
        return {
            "generator_version": GENERATOR_VERSION,
            "seed": self.seed,
            "generated_at": "2026-09-26T00:00:00+05:30",
            "timezone": TIMEZONE_NAME,
            "factory_name": FACTORY_NAME,
            "is_synthetic": True,
            "tables": tables,
            "row_counts": {name: len(value) for name, value in rows.items()},
            "date_range": {"start": iso(START), "end": iso(END)},
            "machine_ids": [m["machine_id"] for m in MACHINES],
            "product_ids": [p["product_id"] for p in PRODUCTS],
            "scenario_ids": [case["case_id"] for case in cases],
            "schema_version": SCHEMA_VERSION,
        }

    def report(self, rows: dict[str, list[dict[str, Any]]], cases: list[dict[str, Any]]) -> str:
        from .validators import compute_case_metrics

        frames = {name: pl.DataFrame(data, infer_schema_length=None) for name, data in rows.items()}
        metrics = compute_case_metrics(frames, cases)
        abnormal = sum(1 for r in rows["quality_inspections"] if r["result"] == "FAIL") + sum(1 for r in rows["machine_alarms"] if r["severity"] != "INFO")
        total = len(rows["quality_inspections"]) + len(rows["machine_alarms"]) + len(rows["maintenance_logs"]) + len(rows["production_orders"])
        lines = [
            "# Demo Factory Report",
            "",
            f"Factory: {FACTORY_NAME}",
            f"Seed: {self.seed}",
            f"Date range: {iso(START)} to {iso(END)}",
            f"Timezone: {TIMEZONE_NAME}",
            f"Telemetry sample interval: {TELEMETRY_INTERVAL_MIN} minutes",
            "",
            "## Record Counts",
            "",
        ]
        for name in TABLES:
            lines.append(f"- {name}: {len(rows[name])}")
        lines.extend(["", f"Approximate abnormal evidence proportion: {abnormal / total:.3f}", "", "## Machines", ""])
        for machine in MACHINES:
            lines.append(f"- {machine['machine_id']}: {machine['machine_type']} ({machine['location']})")
        lines.extend(["", "## Products", ""])
        for product in PRODUCTS:
            lines.append(f"- {product['product_id']}: {product['material']}")
        lines.extend(["", "## Case Summaries", ""])
        for case in cases:
            lines.append(f"### {case['case_id']} - {case['title']}")
            lines.append(f"- Query: {case['query']}")
            lines.append(f"- Expected domains: {', '.join(case['expected_domains'])}")
            lines.append(f"- Metrics: {json.dumps(metrics.get(case['case_id'], {}), ensure_ascii=False)}")
            lines.append("")
        lines.extend(["## Validation Result", "", "Run `python scripts\\demo_factory\\run.py --validate` for the current validation result.", "", "## Warnings", "", "- Hidden simulated causes exist only in `datasets/synthetic/demo_cases.json`, not in Parquet application records.", "- Generated limits and telemetry ranges are demo-factory parameters, not universal industrial thresholds.", ""])
        return "\n".join(lines)


def generate(seed: int = SEED) -> dict[str, Any]:
    return DemoFactoryGenerator(seed).generate()

