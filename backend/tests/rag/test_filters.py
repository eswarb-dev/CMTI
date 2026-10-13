from __future__ import annotations

import pytest
from qdrant_client import models

from app.contracts.query import QueryRequest
from app.rag.filters import (
    DOCUMENT_FILTER_KEYS,
    IDENTITY_KEYS,
    build_query_filter,
    extract_document_filters,
    validate_top_k,
)


def query(user_context: dict | None = None, **kwargs) -> QueryRequest:
    defaults = dict(query_id="Q-1", query="how do I set a tool offset")
    defaults.update(kwargs)
    return QueryRequest(user_context=user_context or {}, **defaults)


def test_validate_top_k_bounds_requests() -> None:
    assert validate_top_k(1) == 1
    assert validate_top_k(10, max_top_k=50) == 10
    assert validate_top_k(999, max_top_k=50) == 50

    for invalid in (0, -3):
        with pytest.raises(ValueError):
            validate_top_k(invalid)
    for invalid in (True, 1.5, "5"):
        with pytest.raises(ValueError):
            validate_top_k(invalid)  # type: ignore[arg-type]


def test_identity_keys_are_never_document_filters() -> None:
    for key in IDENTITY_KEYS:
        assert key not in DOCUMENT_FILTER_KEYS

    supported, ignored = extract_document_filters(
        {"machine_id": "CNC-05", "product_id": "SHAFT-A", "batch_id": "B-77"}
    )
    assert supported == {}
    assert sorted(ignored) == ["batch_id", "machine_id", "product_id"]


def test_supported_keys_are_normalised_and_unknown_keys_reported() -> None:
    supported, ignored = extract_document_filters(
        {"manufacturer": "  Haas ", "language": ["English", "German"], "colour": "red"}
    )
    assert supported == {"manufacturer": ["Haas"], "language": ["English", "German"]}
    assert ignored == ["colour"]


def test_no_supported_context_yields_no_filter() -> None:
    q = query({"machine_id": "CNC-05", "product_id": "SHAFT-A"})
    qfilter, ignored = build_query_filter(q)

    assert qfilter is None
    assert sorted(ignored) == ["machine_id", "product_id"]


def test_machine_identity_is_ignored_while_document_type_is_bound() -> None:
    q = query(
        {
            "machine_id": "CNC-05",
            "product_id": "SHAFT-A",
            "batch_id": "B-77",
            "document_type": "SAFETY",
        }
    )
    qfilter, ignored = build_query_filter(q)

    assert qfilter is not None
    assert sorted(ignored) == ["batch_id", "machine_id", "product_id"]

    must = list(qfilter.must or [])
    assert len(must) == 1
    nested = must[0]
    assert isinstance(nested, models.Filter)
    assert nested.should is not None and len(nested.should) == 2
    keys = {condition.key for condition in nested.should}
    assert keys == {"document_type", "source_type"}


def test_document_type_filter_matches_raw_or_canonical_values() -> None:
    qfilter, _ = build_query_filter(query({"document_type": "SAFETY"}))
    assert qfilter is not None

    raw_condition, source_condition = qfilter.must[0].should  # type: ignore[union-attr]
    assert raw_condition.key == "document_type"
    assert raw_condition.match == models.MatchValue(value="SAFETY")
    assert source_condition.key == "source_type"
    assert source_condition.match == models.MatchValue(value="SAFETY")


def test_multi_value_filter_uses_match_any() -> None:
    qfilter, _ = build_query_filter(query({"manufacturer": ["Haas", "Siemens"]}))
    assert qfilter is not None

    condition = qfilter.must[0]
    assert isinstance(condition, models.FieldCondition)
    assert condition.key == "manufacturer"
    assert condition.match == models.MatchAny(any=["Haas", "Siemens"])


def test_document_id_filter_is_single_valued() -> None:
    qfilter, _ = build_query_filter(query({"document_id": "DOC-3EA7380FA108"}))
    assert qfilter is not None

    condition = qfilter.must[0]
    assert isinstance(condition, models.FieldCondition)
    assert condition.key == "document_id"
    assert condition.match == models.MatchValue(value="DOC-3EA7380FA108")
