from __future__ import annotations

from typing import Any

from qdrant_client import models

from ..contracts.query import QueryRequest

# Keys that are safe to translate into payload filters for the document corpus.
DOCUMENT_FILTER_KEYS = (
    "document_type",
    "manufacturer",
    "machine_family",
    "model",
    "document_id",
    "language",
)

# Structured identity fields that must never be bound to a manual/document chunk.
IDENTITY_KEYS = ("machine_id", "product_id", "batch_id")


def validate_top_k(top_k: int, max_top_k: int = 50) -> int:
    """Clamp requested result counts into a sane, bounded range."""

    if isinstance(top_k, bool) or not isinstance(top_k, int):
        raise ValueError("top_k must be an integer")
    if top_k < 1:
        raise ValueError("top_k must be greater than zero")
    if top_k > max_top_k:
        return max_top_k
    return top_k


def _normalize_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple, set, frozenset)):
        values: list[str] = []
        for item in value:
            values.extend(_normalize_values(item))
        return values
    text = str(value).strip()
    return [text] if text else []


def extract_document_filters(user_context: dict[str, Any] | None) -> tuple[dict[str, list[str]], list[str]]:
    """Return supported document filters plus the context keys that were ignored."""

    supported: dict[str, list[str]] = {}
    ignored: list[str] = []
    for key, value in (user_context or {}).items():
        if key in DOCUMENT_FILTER_KEYS:
            values = _normalize_values(value)
            if values:
                supported[key] = values
        else:
            ignored.append(key)
    return supported, ignored


def _match_condition(key: str, values: list[str]) -> models.FieldCondition:
    if len(values) == 1:
        return models.FieldCondition(key=key, match=models.MatchValue(value=values[0]))
    return models.FieldCondition(key=key, match=models.MatchAny(any=values))


def build_query_filter(query: QueryRequest) -> tuple[models.Filter | None, list[str]]:
    """Build a Qdrant payload filter from explicit user context only.

    ``machine_id`` / ``product_id`` / ``batch_id`` are intentionally ignored:
    the document corpus contains manuals, so machine identity must never
    silently restrict which documents can be retrieved.
    """

    supported, ignored = extract_document_filters(query.user_context)
    conditions: list[models.Condition] = []
    for key in DOCUMENT_FILTER_KEYS:
        values = supported.get(key)
        if not values:
            continue
        condition: models.Condition = _match_condition(key, values)
        if key == "document_type":
            # ``document_type`` may be given as the raw staged value
            # (``OPERATOR_MANUAL``) or as the canonical evidence source type
            # (``MANUAL``), so match either payload field.
            condition = models.Filter(
                should=[condition, _match_condition("source_type", values)]
            )
        conditions.append(condition)
    if not conditions:
        return None, ignored
    return models.Filter(must=conditions), ignored
