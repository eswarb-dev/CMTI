from __future__ import annotations

from evaluation.metrics import retrieval_metrics


def test_hit_at_k_and_mrr() -> None:
    result = retrieval_metrics(["E3", "E1", "E9"], ["E1", "E5"])
    assert result["hit_at_1"] is False
    assert result["hit_at_3"] is True
    assert result["hit_at_5"] is True
    assert result["mrr"] == 0.5
    assert result["relevant_found"] is True


def test_first_rank_mrr_one() -> None:
    result = retrieval_metrics(["E1", "E2"], ["E1"])
    assert result["hit_at_1"] is True
    assert result["mrr"] == 1.0


def test_no_relevant_is_not_applicable() -> None:
    result = retrieval_metrics(["E1"], [])
    assert result["hit_at_1"] is None
    assert result["mrr"] is None
    assert result["relevant_found"] is False


def test_empty_ranking_miss() -> None:
    result = retrieval_metrics([], ["E1"])
    assert result["hit_at_1"] is False
    assert result["hit_at_3"] is False
    assert result["hit_at_5"] is False
    assert result["mrr"] is None
