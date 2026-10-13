from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


SEED = 20260926
GENERATOR_VERSION = "demo_factory.step02.v1"
SCHEMA_VERSION = "demo_factory.v1"
FACTORY_NAME = "ManufacturaIQ Demo Plant"
SOURCE_DATASET = "manufacturaiq_demo_factory"
TIMEZONE_NAME = "Asia/Kolkata"
TZ = ZoneInfo(TIMEZONE_NAME)
START = datetime(2026, 9, 1, 8, 0, tzinfo=TZ)
END = datetime(2026, 10, 15, 18, 0, tzinfo=TZ)
TELEMETRY_INTERVAL_MIN = 5

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASETS_ROOT = PROJECT_ROOT / "datasets"
OUTPUT_ROOT = DATASETS_ROOT / "normalized" / "demo_factory"
SYNTHETIC_ROOT = DATASETS_ROOT / "synthetic"
MANIFEST_PATH = DATASETS_ROOT / "manifests" / "demo_factory.json"
REPORT_PATH = DATASETS_ROOT / "reports" / "DEMO_FACTORY_REPORT.md"
CASES_PATH = SYNTHETIC_ROOT / "demo_cases.json"


@dataclass(frozen=True)
class MachineProfile:
    machine_id: str
    rpm: float
    vibration: float
    temperature: float
    current: float
    load: float
    power: float


MACHINES = [
    {
        "machine_id": "CNC-01",
        "machine_name": "CNC-01 Vertical Cell",
        "machine_type": "Vertical machining center",
        "asset_group": "CNC",
        "installation_date": "2021-04-12",
        "status": "ACTIVE",
        "location": "Bay A",
        "criticality": "HIGH",
    },
    {
        "machine_id": "CNC-03",
        "machine_name": "CNC-03 Turning Cell",
        "machine_type": "CNC turning center",
        "asset_group": "CNC",
        "installation_date": "2020-11-03",
        "status": "ACTIVE",
        "location": "Bay B",
        "criticality": "HIGH",
    },
    {
        "machine_id": "CNC-05",
        "machine_name": "CNC-05 Precision Milling Cell",
        "machine_type": "Vertical machining center",
        "asset_group": "CNC",
        "installation_date": "2022-01-18",
        "status": "ACTIVE",
        "location": "Bay C",
        "criticality": "CRITICAL",
    },
]

PRODUCTS = [
    {
        "product_id": "SHAFT-A",
        "product_name": "Synthetic precision shaft A",
        "material": "Alloy steel",
        "nominal_cycle_time_sec": 180,
        "description": "Fictional turned and milled shaft for demo investigations.",
    },
    {
        "product_id": "GEAR-B",
        "product_name": "Synthetic gear blank B",
        "material": "Case-hardening steel",
        "nominal_cycle_time_sec": 240,
        "description": "Fictional gear blank for quality and production examples.",
    },
    {
        "product_id": "HOUSING-C",
        "product_name": "Synthetic housing C",
        "material": "Aluminum alloy",
        "nominal_cycle_time_sec": 300,
        "description": "Fictional machined housing for demo factory context.",
    },
]

PROFILES = {
    "CNC-01": MachineProfile("CNC-01", 2100, 1.25, 42.0, 18.0, 62.0, 8.0),
    "CNC-03": MachineProfile("CNC-03", 1650, 1.05, 45.0, 21.0, 67.0, 7.5),
    "CNC-05": MachineProfile("CNC-05", 2300, 1.10, 41.0, 19.0, 64.0, 8.7),
}

