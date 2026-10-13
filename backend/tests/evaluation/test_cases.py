from __future__ import annotations

import pytest

from evaluation.cases import get_suite, list_suites
from evaluation.models import EvaluationCase


def test_suites_listed() -> None:
    assert set(list_suites()) == {"smoke", "core"}


def test_unknown_suite_rejected() -> None:
    with pytest.raises(ValueError, match="unknown evaluation suite"):
        get_suite("nope")


def test_smoke_suite_small_and_stable() -> None:
    first = get_suite("smoke")
    second = get_suite("smoke")
    assert 5 <= len(first) <= 10
    assert [c.case_id for c in first] == [c.case_id for c in second]


def test_core_suite_category_coverage() -> None:
    cases = get_suite("core")
    assert len(cases) >= 50
    by_category: dict[str, int] = {}
    for case in cases:
        by_category[case.category] = by_category.get(case.category, 0) + 1
    for category in ("document", "maintenance", "quality", "production",
                     "multi", "safety", "clarification", "negative"):
        assert by_category.get(category, 0) >= 5, category


def test_case_ids_unique() -> None:
    for suite in list_suites():
        ids = [c.case_id for c in get_suite(suite)]
        assert len(set(ids)) == len(ids)


def test_document_cases_follow_fallback_mapping() -> None:
    for case in get_suite("core"):
        if case.category == "document":
            assert case.expected_agents == ["DOCUMENT"]
            assert case.machine_id is None


def test_demo_multi_cases_carry_hidden_cause() -> None:
    multi = [c for c in get_suite("core") if c.case_id.startswith("MULTI-CASE-")]
    assert len(multi) == 5
    assert all(c.expected_hidden_cause for c in multi)


def test_case_model_rejects_empty_query() -> None:
    with pytest.raises(Exception):
        EvaluationCase(case_id="X", category="document", query="  ")


def test_negative_batch_scope_preserved() -> None:
    cases = {c.case_id: c for c in get_suite("core")}
    neg4 = cases["NEG-004"]
    assert neg4.batch_id == "BATCH-UNKNOWN-1"
    assert neg4.expected_agents == ["DOCUMENT", "QUALITY", "PRODUCTION"]
