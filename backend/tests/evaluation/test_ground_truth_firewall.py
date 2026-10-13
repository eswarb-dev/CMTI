"""Ground-truth firewall: hidden evaluator fields must never reach production."""

from __future__ import annotations

import pytest

from evaluation.cases import get_suite
from evaluation.models import EvaluationCase
from evaluation.runner import assert_firewall, build_query_request


MARKED_HIDDEN = "HIDDEN-CAUSE-ZXQV-9f8e7d6c5b4a"


def _marked_case(**overrides) -> EvaluationCase:
    fields: dict = {
        "case_id": "FIREWALL-001",
        "category": "negative",
        "query": "Show the lockout tagout procedure.",
        "expected_hidden_cause": MARKED_HIDDEN,
        "expected_record_ids": ["HIDDEN-RECORD-12345"],
        "expected_document_ids": ["HIDDEN-DOC-99999"],
        "notes": "HIDDEN-NOTE-qwerty-112233",
    }
    fields.update(overrides)
    return EvaluationCase(**fields)


def test_hidden_fields_absent_from_query_request() -> None:
    request = build_query_request(_marked_case())
    dumped = request.model_dump_json()
    assert MARKED_HIDDEN not in dumped
    assert "HIDDEN-RECORD-12345" not in dumped
    assert "HIDDEN-DOC-99999" not in dumped
    assert "HIDDEN-NOTE-qwerty-112233" not in dumped


def test_firewall_rejects_leaking_request() -> None:
    request = build_query_request(_marked_case())

    class LeakingRequest:
        def model_dump_json(self) -> str:
            return f'{{"user_context": {{"hidden": "{MARKED_HIDDEN}"}}}}'

    with pytest.raises(AssertionError, match="ground-truth leak"):
        assert_firewall(_marked_case(), LeakingRequest())


def test_demo_suite_hidden_causes_never_in_requests() -> None:
    for case in get_suite("core"):
        request = build_query_request(case)
        dumped = request.model_dump_json()
        if case.expected_hidden_cause:
            assert case.expected_hidden_cause not in dumped
        for record_id in case.expected_record_ids:
            assert record_id not in dumped
        for document_id in case.expected_document_ids:
            assert document_id not in dumped


def test_workflow_initial_state_carries_no_hidden_fields() -> None:
    case = _marked_case()
    request = build_query_request(case)
    initial_state = {"query": request, "agent_results_by_name": {}}
    dumped = request.model_dump_json()
    assert MARKED_HIDDEN not in dumped
    assert set(initial_state.keys()) == {"query", "agent_results_by_name"}


def test_only_evaluator_comparison_reads_hidden_cause() -> None:
    from evaluation.runner import _weak_cause_alignment

    case = _marked_case()
    request = build_query_request(case)
    assert MARKED_HIDDEN not in request.model_dump_json()
    # Post-inference comparison is the ONLY allowed reader.
    assert _weak_cause_alignment(MARKED_HIDDEN, ["unrelated text"]) == \
        "no_keyword_alignment:human-review-required"
