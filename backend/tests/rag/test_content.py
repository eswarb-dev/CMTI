from __future__ import annotations

import json
from pathlib import Path

from app.rag.validation import (
    CONTENT_REQUIREMENT_KEYS,
    compute_content_metrics,
    content_requirements,
    is_content_hit,
)


def item(**overrides) -> dict:
    base = {
        "document_id": "DOC-53F6788896F3",
        "chunk_id": "CHUNK-X",
        "source_type": "MANUAL",
        "score": 0.7,
        "title": "Milling -- 14.1 Lists for the tool management",
        "text": "Open the tool management lists to edit tool data for the magazine.",
        "heading_path": ["14.1 Lists for the tool management"],
    }
    base.update(overrides)
    return base


def requirements(**overrides) -> dict:
    base = {
        "documents": ["DOC-53F6788896F3"],
        "source_types": ["MANUAL"],
        "keywords_all": ["tool"],
        "keywords_any": ["tool management", "magazine"],
        "heading_all": [],
        "heading_forbidden": [],
    }
    base.update(overrides)
    return base


def test_content_hit_requires_document_source_keywords_and_heading() -> None:
    req = requirements()
    assert is_content_hit(item(), req) is True
    assert is_content_hit(item(document_id="DOC-OTHER"), req) is False
    assert is_content_hit(item(source_type="SAFETY"), req) is False
    assert is_content_hit(item(text="Unrelated overview paragraph."), req) is False


def test_content_hit_supports_any_of_and_heading_rules() -> None:
    req = requirements(keywords_all=[], keywords_any=["magazine", "spindle"])
    assert is_content_hit(item(), req) is True
    assert is_content_hit(item(text="Generic overview without the terms."), req) is False

    heading_req = requirements(
        keywords_all=[], keywords_any=[], heading_all=["tool management"]
    )
    assert is_content_hit(item(), heading_req) is True
    assert is_content_hit(item(title="Milling", heading_path=["Overview"]), heading_req) is False

    forbidden_req = requirements(
        keywords_all=[], keywords_any=[], heading_forbidden=["work offset"]
    )
    assert is_content_hit(item(), forbidden_req) is True
    assert (
        is_content_hit(item(title="Mill -- 4.43 Set a Work Offset"), forbidden_req)
        is False
    )


def test_content_matching_uses_tokens_not_substrings() -> None:
    req = requirements(documents=[], source_types=[], keywords_all=["oil"], keywords_any=[])
    assert is_content_hit(item(text="Add oil to the reservoir."), req) is True
    # "oil" must not match inside "boil"/"coil"/"soil".
    assert is_content_hit(item(text="Boil the coolant coil clean."), req) is False

    phrase_req = requirements(
        documents=[], source_types=[], keywords_all=["tool management"], keywords_any=[]
    )
    assert is_content_hit(item(), phrase_req) is True


def test_content_requirements_absent_for_document_only_cases() -> None:
    assert content_requirements({"expected_document_ids": ["DOC-1"]}) is None
    assert content_requirements({"required_source_types": ["MANUAL"]}) is None
    full = content_requirements({"expected_keywords": ["alarm"]})
    assert full is not None
    assert full["keywords_all"] == ["alarm"]


def test_compute_content_metrics_counts_only_content_cases() -> None:
    req = requirements()
    results = [
        {
            "case_id": "doc-only",
            "content_requirements": None,
            "returned": [item()],
        },
        {
            "case_id": "hit",
            "content_requirements": req,
            "returned": [item(), item(text="Other paragraph.")],
        },
        {
            "case_id": "miss",
            "content_requirements": req,
            "returned": [item(text="Other paragraph."), item(text="More overview.")],
        },
    ]
    metrics = compute_content_metrics(results)

    assert metrics["cases"] == 2
    assert metrics["content_hit_at_1"] == 0.5
    assert metrics["content_hit_at_3"] == 0.5
    assert metrics["content_hit_at_5"] == 0.5
    assert metrics["content_mrr"] == 0.5
    assert metrics["failed_cases"] == ["miss"]
    assert compute_content_metrics([])["cases"] == 0


def test_fixture_declares_content_fields_for_core_queries(settings) -> None:
    fixture = (
        Path(settings.project_root)
        / "backend"
        / "tests"
        / "rag"
        / "fixtures"
        / "retrieval_cases.json"
    )
    cases = {case["case_id"]: case for case in json.loads(fixture.read_text(encoding="utf-8"))["cases"]}

    for case_id in (
        "content_spindle_lubrication",
        "content_lathe_chuck_safety",
        "content_sinumerik_tool_management",
        "content_lockout_tagout_energy",
        "content_siemens_alarm_reset",
    ):
        assert case_id in cases
        assert any(cases[case_id].get(key) for key in CONTENT_REQUIREMENT_KEYS)

    content_cases = [case for case in cases.values() if content_requirements(case)]
    assert len(content_cases) >= 10


def test_content_metrics_are_reported_as_info(retrieval_quality) -> None:
    content = retrieval_quality["content_metrics"]

    assert content["cases"] >= 10
    for name in ("content_hit_at_1", "content_hit_at_3", "content_hit_at_5"):
        assert 0.0 <= content[name] <= 1.0
    assert content["content_hit_at_3"] >= 0.9
    assert content["content_hit_at_5"] >= 0.9
    assert isinstance(content["failed_cases"], list)

    checks = {check.name: check.status for check in retrieval_quality["checks"]}
    assert checks["retrieval_content_hit_at_1"] == "PASS"
    assert checks["retrieval_content_hit_at_3"] == "PASS"
    assert checks["retrieval_content_hit_at_5"] == "PASS"
