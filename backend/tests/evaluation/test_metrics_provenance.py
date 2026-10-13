from __future__ import annotations

from evaluation.metrics import provenance_metrics


def _document_item(**overrides):
    item = {
        "evidence_id": "EV-DOC",
        "source_type": "MANUAL",
        "provenance": {
            "source_kind": "DOCUMENT",
            "source_dataset": "technical_document_corpus",
            "source_id": "DOC-1",
            "document_id": "DOC-1",
            "page_start": 3,
            "page_end": 4,
        },
    }
    item.update(overrides)
    return item


def _structured_item():
    return {
        "evidence_id": "EV-STR",
        "source_type": "QUALITY",
        "provenance": {
            "source_kind": "DEMO_FACTORY",
            "source_dataset": "manufacturaiq_demo_factory",
            "source_id": "QI-1",
            "record_id": "QI-1",
        },
    }


def test_complete_provenance_passes() -> None:
    result = provenance_metrics([_document_item(), _structured_item()])
    assert result["completeness_rate"] == 1.0
    assert result["validity_rate"] == 1.0
    assert result["issues"] == []


def test_document_missing_document_page_flagged() -> None:
    item = _document_item()
    item["provenance"] = {
        "source_kind": "DOCUMENT",
        "source_dataset": "technical_document_corpus",
        "source_id": "DOC-1",
    }
    result = provenance_metrics([item])
    assert result["completeness_rate"] == 0.0
    assert any("document_id" in issue for issue in result["issues"])


def test_structured_missing_identity_flagged() -> None:
    item = _structured_item()
    item["provenance"] = {
        "source_kind": "DEMO_FACTORY",
        "source_dataset": "manufacturaiq_demo_factory",
        "source_id": "",
    }
    result = provenance_metrics([item])
    assert result["completeness_rate"] == 0.0


def test_no_false_page_requirement_for_structured() -> None:
    result = provenance_metrics([_structured_item()])
    assert result["issues"] == []


def test_empty_list_is_not_applicable() -> None:
    result = provenance_metrics([])
    assert result["completeness_rate"] is None
    assert result["validity_rate"] is None
