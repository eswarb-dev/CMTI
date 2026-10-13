"""STEP 19A: structured record identity + provenance hardening locks.

STEP 18B finding: QI-*/TEL-* expected record identities had low recall.
Diagnosis (see docs/RECORD_IDENTITY_PROVENANCE.md):
- Individual-row evidence in every agent preserves its canonical source ID
  (quality inspection_id, maintenance maintenance_id, alarm alarm_id,
  production production_id) in BOTH source_id and record_id.
- Telemetry evidence is summary-only BY DESIGN (38k rows cannot each become
  evidence); summaries truthfully carry record_id=None.
- Missing expected IDs come from frozen top-k limits vs exhaustive
  expectations (cause E) and aggregate unrepresentability (cause D) —
  NOT from dropped/mismapped identities (causes A/B/C disproven).

These tests lock the verified behavior. No production code was changed.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.agents.maintenance import (
    alarm_record_to_evidence,
    alarm_summary_to_evidence,
    maintenance_record_to_evidence,
    telemetry_summary_to_evidence,
)
from app.agents.production import production_record_to_evidence
from app.agents.quality import (
    quality_record_to_evidence,
    quality_summary_to_evidence,
)
from app.contracts.query import QueryRequest
from app.db.models import AlarmRecord, MaintenanceRecord, QualityRecord
from app.repositories.quality import ParameterSummary, QualitySummary


def _quality_record(inspection_id: str = "QI-000401") -> QualityRecord:
    return QualityRecord(
        inspection_id=inspection_id,
        batch_id="B-001",
        machine_id="CNC-05",
        product_id="SHAFT-A",
        timestamp=datetime(2026, 9, 15, 10, 0, 0),
        parameter="diameter",
        nominal_value=10.0,
        lsl=9.5,
        usl=10.5,
        measured_value=10.8,
        result="FAIL",
        defect_type="OVERSIZE",
        inspection_method="CALIPER",
        is_synthetic=True,
        source_dataset="manufacturaiq_demo_factory",
    )


def _quality_summary() -> QualitySummary:
    return QualitySummary(
        inspection_count=10,
        pass_count=8,
        fail_count=2,
        failure_rate=0.2,
        parameters=[ParameterSummary(parameter="diameter", inspection_count=10,
                                     pass_count=8, fail_count=2, failure_rate=0.2,
                                     min_measurement=9.5, max_measurement=10.8,
                                     mean_measurement=10.1)],
    )


def _maintenance_record() -> MaintenanceRecord:
    return MaintenanceRecord(
        maintenance_id="MNT-000070",
        machine_id="CNC-05",
        created_at=datetime(2026, 9, 12, 8, 0, 0),
        started_at=datetime(2026, 9, 12, 9, 0, 0),
        completed_at=datetime(2026, 9, 12, 11, 0, 0),
        maintenance_type="CORRECTIVE",
        symptom="vibration",
        component="spindle",
        failure_code=None,
        inspection_findings=None,
        action_taken="bearing check",
        planned_downtime_min=60,
        actual_downtime_min=55,
        status="COMPLETED",
        is_synthetic=True,
        source_dataset="manufacturaiq_demo_factory",
    )


def _alarm_record(**overrides) -> AlarmRecord:
    fields: dict = {
        "alarm_id": "ALM-000046",
        "machine_id": "CNC-05",
        "timestamp": datetime(2026, 9, 12, 8, 5, 0),
        "alarm_code": "ALM-SERVO-03",
        "severity": "HIGH",
        "category": "SERVO",
        "description": "Servo overload",
        "acknowledged": False,
        "acknowledged_at": None,
        "related_batch_id": None,
        "is_synthetic": True,
        "source_dataset": "manufacturaiq_demo_factory",
    }
    fields.update(overrides)
    return AlarmRecord(**fields)


# ---------------- Quality ----------------

def test_quality_individual_preserves_source_inspection_id() -> None:
    evidence = quality_record_to_evidence(_quality_record("QI-000401"))
    assert evidence.provenance.source_id == "QI-000401"
    assert evidence.provenance.record_id == "QI-000401"
    assert "QI-000401" in evidence.evidence_id


def test_quality_id_matches_repository_record() -> None:
    import sqlite3

    con = sqlite3.connect("data/manufacturaiq.db")
    try:
        row = con.execute(
            "SELECT inspection_id, machine_id, product_id FROM quality_inspections "
            "WHERE inspection_id = 'QI-000401'"
        ).fetchone()
    finally:
        con.close()
    assert row is not None
    record = _quality_record(row[0])
    evidence = quality_record_to_evidence(record)
    assert evidence.provenance.record_id == row[0]
    assert evidence.machine_id == row[1]
    assert evidence.product_id == row[2]


def test_quality_identity_not_generated_from_index() -> None:
    first = quality_record_to_evidence(_quality_record("QI-000401"))
    second = quality_record_to_evidence(_quality_record("QI-000402"))
    assert first.provenance.record_id != second.provenance.record_id
    assert first.evidence_id != second.evidence_id
    # Mapping is deterministic for the same record.
    again = quality_record_to_evidence(_quality_record("QI-000401"))
    assert again.evidence_id == first.evidence_id
    assert again.content == first.content


def test_quality_summary_does_not_claim_row_identity() -> None:
    evidence = quality_summary_to_evidence(
        _quality_summary(), "CNC-05", "SHAFT-A", None, None, None,
        "manufacturaiq_demo_factory",
    )
    assert evidence.provenance.record_id is None
    assert evidence.metadata.get("aggregation") == "quality_summary"
    assert not evidence.provenance.source_id.startswith("QI-")


async def test_quality_agent_query_id_and_scores_stable() -> None:
    from app.agents.quality import QualityAgent

    class FakeRepo:
        async def summarize_results(self, **kwargs):
            return _quality_summary()

        async def list_failures(self, **kwargs):
            return [_quality_record("QI-000401")]

        async def list_by_machine(self, *args, **kwargs):
            return []

    agent = QualityAgent(FakeRepo())  # type: ignore[arg-type]
    query = QueryRequest(query_id="Q-19A", query="quality", machine_id="CNC-05")
    result = await agent.run(query)
    assert result.query_id == "Q-19A"
    records = [e for e in result.evidence if e.provenance.record_id == "QI-000401"]
    assert len(records) == 1


# ---------------- Telemetry ----------------

def test_telemetry_summary_provenance_truthful() -> None:
    from app.repositories.telemetry import MetricStats, TelemetrySummary

    summary = TelemetrySummary(
        machine_id="CNC-05",
        start_time="2026-09-01T00:00:00",
        end_time="2026-09-02T00:00:00",
        sample_count=100,
        metrics={"vibration_mm_s": MetricStats(count=100, min=0.1, max=2.0,
                                              mean=0.5, first=0.2, last=0.6)},
    )
    evidence = telemetry_summary_to_evidence("CNC-05", summary)
    assert evidence.provenance.record_id is None
    assert evidence.source_type.value == "TELEMETRY"
    assert evidence.machine_id == "CNC-05"
    assert "100 samples" in evidence.content


def test_telemetry_summary_claims_no_arbitrary_row_id() -> None:
    from app.repositories.telemetry import MetricStats, TelemetrySummary

    summary = TelemetrySummary(
        machine_id="CNC-05",
        start_time="2026-09-01T00:00:00",
        end_time="2026-09-02T00:00:00",
        sample_count=38379,
        metrics={},
    )
    evidence = telemetry_summary_to_evidence("CNC-05", summary)
    assert not evidence.provenance.source_id.startswith("TEL-")
    assert evidence.metadata["sample_count"] == 38379


# ---------------- Maintenance / Alarm ----------------

def test_maintenance_individual_preserves_id() -> None:
    evidence = maintenance_record_to_evidence(_maintenance_record())
    assert evidence.provenance.source_id == "MNT-000070"
    assert evidence.provenance.record_id == "MNT-000070"


def test_alarm_individual_preserves_id() -> None:
    evidence = alarm_record_to_evidence(_alarm_record())
    assert evidence.provenance.source_id == "ALM-000046"
    assert evidence.provenance.record_id == "ALM-000046"


def test_alarm_without_optional_code_fabricates_nothing() -> None:
    evidence = alarm_record_to_evidence(_alarm_record(alarm_code=None))
    assert evidence.provenance.record_id == "ALM-000046"
    assert "ALM-000046" in evidence.title


def test_alarm_summary_does_not_claim_row_identity() -> None:
    evidence = alarm_summary_to_evidence("CNC-05", "ALM-SERVO-03", 3, None, None,
                                         "manufacturaiq_demo_factory")
    assert evidence.provenance.record_id is None
    assert evidence.metadata.get("aggregation") == "count"


# ---------------- Production ----------------

def test_production_individual_preserves_id() -> None:
    import sqlite3

    con = sqlite3.connect("data/manufacturaiq.db")
    try:
        row = con.execute(
            "SELECT production_id FROM production_orders WHERE production_id = 'PRODORD-000081'"
        ).fetchone()
    finally:
        con.close()
    assert row is not None
    from app.db.models import ProductionRecord

    record = ProductionRecord(
        production_id=row[0],
        batch_id="B-001",
        machine_id="CNC-05",
        product_id="SHAFT-A",
        planned_quantity=100,
        actual_quantity=98,
        accepted_quantity=90,
        rejected_quantity=8,
        reject_rate=0.08,
        planned_start_time=None,
        actual_start_time=None,
        actual_end_time=None,
        cycle_time_sec=None,
        shift=None,
        production_status="COMPLETED",
        is_synthetic=True,
        source_dataset="manufacturaiq_demo_factory",
    )
    evidence = production_record_to_evidence(record)
    assert evidence.provenance.source_id == "PRODORD-000081"
    assert evidence.provenance.record_id == "PRODORD-000081"


# ---------------- Aggregate policy + firewall ----------------

def test_aggregates_never_pose_as_member_rows() -> None:
    quality_agg = quality_summary_to_evidence(
        _quality_summary(), "CNC-05", None, None, None, None,
        "manufacturaiq_demo_factory",
    )
    alarm_agg = alarm_summary_to_evidence("CNC-05", "X", 2, None, None,
                                          "manufacturaiq_demo_factory")
    for evidence in (quality_agg, alarm_agg):
        assert evidence.provenance.record_id is None
        assert evidence.metadata.get("aggregation") is not None


def test_production_files_reference_no_evaluation_truth() -> None:
    from pathlib import Path

    forbidden = (
        "evaluation",
        "demo_cases.json",
        "hidden_simulated_cause",
        "relevant_record_ids",
        "expected_record_ids",
    )
    roots = [
        Path(__file__).resolve().parents[2] / "app" / "agents",
        Path(__file__).resolve().parents[2] / "app" / "repositories",
        Path(__file__).resolve().parents[2] / "app" / "fusion",
    ]
    offenders = []
    for root in roots:
        for path in root.glob("*.py"):
            lowered = path.read_text(encoding="utf-8").lower()
            for term in forbidden:
                if term in lowered:
                    offenders.append(f"{path.name}: {term}")
    assert offenders == []
