from __future__ import annotations

from evaluation.metrics import citation_metrics


def test_citation_validity_two_of_three() -> None:
    result = citation_metrics(["A", "B", "C"], ["A", "C", "X"])
    assert result["citation_count"] == 3
    assert result["valid_citations"] == 2
    assert result["invalid_citations"] == 1
    assert result["orphan_ids"] == ["X"]
    assert result["validity_rate"] == 2 / 3
    assert result["duplicate_citations"] == 0


def test_duplicate_citations_counted() -> None:
    result = citation_metrics(["A"], ["A", "A"])
    assert result["duplicate_citations"] == 1
    assert result["valid_citations"] == 2


def test_no_citations_is_not_applicable() -> None:
    result = citation_metrics(["A"], [])
    assert result["validity_rate"] is None
    assert result["invalid_citations"] == 0
