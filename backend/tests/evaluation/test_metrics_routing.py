from __future__ import annotations

from evaluation.metrics import routing_metrics


def test_exact_match() -> None:
    result = routing_metrics(["DOCUMENT", "QUALITY"], ["DOCUMENT", "QUALITY"])
    assert result["exact_match"] is True
    assert result["subset_accuracy"] is True
    assert result["micro_precision"] == 1.0
    assert result["micro_recall"] == 1.0
    assert result["micro_f1"] == 1.0
    assert result["over_routed"] == []
    assert result["under_routed"] == []


def test_partial_overlap_precision_recall_f1() -> None:
    # expected {DOCUMENT, MAINTENANCE}, actual {DOCUMENT, QUALITY}
    result = routing_metrics(["DOCUMENT", "MAINTENANCE"], ["DOCUMENT", "QUALITY"])
    assert result["exact_match"] is False
    assert result["micro_precision"] == 0.5
    assert result["micro_recall"] == 0.5
    assert result["micro_f1"] == 0.5
    assert result["over_routed"] == ["QUALITY"]
    assert result["under_routed"] == ["MAINTENANCE"]
    assert result["per_agent"]["DOCUMENT"]["f1"] == 1.0
    assert result["per_agent"]["QUALITY"]["precision"] == 0.0
    assert result["per_agent"]["MAINTENANCE"]["recall"] == 0.0


def test_empty_expected_and_actual_is_not_applicable() -> None:
    result = routing_metrics([], [])
    assert result["exact_match"] is True
    assert result["micro_precision"] is None
    assert result["micro_recall"] is None
    assert result["micro_f1"] is None


def test_over_routing_only() -> None:
    result = routing_metrics(["DOCUMENT"], ["DOCUMENT", "QUALITY"])
    assert result["micro_precision"] == 0.5
    assert result["micro_recall"] == 1.0
    assert result["over_routed"] == ["QUALITY"]
    assert result["under_routed"] == []


def test_under_routing_only() -> None:
    result = routing_metrics(["DOCUMENT", "QUALITY"], ["DOCUMENT"])
    assert result["micro_precision"] == 1.0
    assert result["micro_recall"] == 0.5
    assert result["over_routed"] == []
    assert result["under_routed"] == ["QUALITY"]
