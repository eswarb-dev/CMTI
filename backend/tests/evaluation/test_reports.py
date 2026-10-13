from __future__ import annotations

import json

from evaluation.models import CaseResult, EvaluationRun
from evaluation.reports import scan_for_secrets, write_run
from evaluation.runner import summarize


def _payload(case_id="R-001", failures=(), metrics=()):
    case = CaseResult(
        case_id=case_id, category="document", mode="offline", query="q",
        routing_agents=["DOCUMENT"], evidence_ids=["E1"],
        reasoning_provider_status="UNAVAILABLE", review_action="HUMAN_REVIEW",
        metrics=list(metrics), failures=list(failures), latency_ms=12.5,
    )
    return {"case": case,
            "human_row": {"case_id": case_id, "query": "q",
                          "hidden_expected_cause__evaluator_only": "hidden cause"},
            "fingerprint": {"routing": ["DOCUMENT"]}}


def _run():
    return EvaluationRun(run_id="20260101T000000_offline", mode="offline",
                         suite="smoke", started_at="2026-01-01T00:00:00+00:00",
                         finished_at="2026-01-01T00:01:00+00:00", case_count=1,
                         environment={"mode": "offline"})


def test_write_run_produces_all_artifacts(tmp_path) -> None:
    payloads = [_payload()]
    summary = summarize(payloads)
    paths = write_run(tmp_path / "run1", _run(), payloads, summary,
                      {"repeated_cases": 0, "mismatched_cases": []})
    assert set(paths) == {"summary", "cases", "metrics", "failures",
                          "human_review", "latency", "report"}
    for path in paths.values():
        assert path.exists()
    summary_doc = json.loads(paths["summary"].read_text(encoding="utf-8"))
    assert summary_doc["run"]["run_id"] == "20260101T000000_offline"
    assert summary_doc["summary"]["case_count"] == 1
    lines = paths["cases"].read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["case_id"] == "R-001"
    assert "hidden_expected_cause__evaluator_only" in paths["human_review"].read_text(encoding="utf-8")


def test_secret_scan_detects_key_material() -> None:
    assert scan_for_secrets("nothing sensitive here") == []
    assert scan_for_secrets("GEMINI_API_KEY=AIzaSyD-secret-value") != []
    assert scan_for_secrets("bearer abc.def.ghi") != []


def test_write_run_refuses_secret_leak(tmp_path) -> None:
    from evaluation.models import MetricResult

    payload = _payload()
    payload["human_row"]["raw_answer"] = "leaked GEMINI_API_KEY=AIzaSyD0123456789abcdefghi"
    payload["case"].metrics.append(MetricResult(name="x", value=1.0))
    try:
        write_run(tmp_path / "run2", _run(), [payload], summarize([payload]),
                  {"repeated_cases": 0, "mismatched_cases": []})
    except AssertionError as exc:
        assert "secret pattern detected" in str(exc)
    else:
        raise AssertionError("expected secret refusal")


def test_summarize_aggregates_and_counts_failures() -> None:
    from evaluation.models import MetricResult

    good = _payload("R-001")
    bad = _payload("R-002", failures=["routing_mismatch"])
    bad["case"].metrics.append(MetricResult(name="routing_exact_match", value=0.0))
    good["case"].metrics.append(MetricResult(name="routing_exact_match", value=1.0))
    summary = summarize([good, bad])
    assert summary["case_count"] == 2
    assert summary["cases_with_failures"] == 1
    assert summary["failure_counts"] == {"routing_mismatch": 1}
    assert summary["metric_means"]["routing_exact_match"]["mean"] == 0.5
    assert summary["latency"]["count"] == 2
