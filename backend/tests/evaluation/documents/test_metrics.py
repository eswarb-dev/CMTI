from __future__ import annotations

from evaluation.documents import metrics as metrics_module


def test_retrieval_metrics_hit_and_mrr() -> None:
    result = metrics_module.retrieval_metrics(["E9", "USR-X", "E3"], "USR-X")
    assert result["hit_at_1"] is False
    assert result["hit_at_3"] is True
    assert result["hit_at_5"] is True
    assert result["mrr"] == 0.5


def test_retrieval_metrics_first_rank() -> None:
    result = metrics_module.retrieval_metrics(["USR-X"], "USR-X")
    assert result["hit_at_1"] is True
    assert result["mrr"] == 1.0


def test_page_hit() -> None:
    assert metrics_module.page_hit([1, 2], [2]) is True
    assert metrics_module.page_hit([1], [3]) is False
    assert metrics_module.page_hit([1], []) is None


def _evidence(**overrides):
    base = {
        "evidence_id": "EVIDENCE-CHUNK-USR-X",
        "title": "Manual",
        "content": "text",
        "retrieval_score": 0.8,
        "provenance": {
            "document_id": "USR-ABCDEF123456",
            "page_start": 2,
            "chunk_id": "CHUNK-USR-X",
            "source_dataset": "manufacturaiq_dynamic_documents",
        },
    }
    base.update(overrides)
    return base


def test_provenance_valid_ok() -> None:
    ok, issues = metrics_module.provenance_valid(_evidence(), "USR-ABCDEF123456")
    assert ok is True
    assert issues == []


def test_provenance_valid_flags_problems() -> None:
    evidence = _evidence()
    evidence["provenance"] = {"document_id": "DOC-1", "page_start": 0}
    ok, issues = metrics_module.provenance_valid(evidence, "USR-ABCDEF123456")
    assert ok is False
    assert issues


def test_provenance_valid_flags_path_leak() -> None:
    evidence = _evidence()
    evidence["title"] = "D:\\CMTI\\data\\documents\\originals\\x.pdf"
    ok, issues = metrics_module.provenance_valid(evidence, "USR-ABCDEF123456")
    assert ok is False
    assert any("leak" in issue for issue in issues)


def test_unicode_filename_and_title_do_not_trigger_path_leak() -> None:
    evidence = _evidence(title="unicode_grinder.pdf")
    evidence["content"] = "Überwachung der Spindel — 温度管理 — contrôle du mandrin"
    ok, issues = metrics_module.provenance_valid(evidence, "USR-ABCDEF123456")
    assert ok is True
    assert issues == []


def test_real_windows_absolute_path_triggers_leak() -> None:
    issues = metrics_module.public_value_issues({"title": r"D:\CMTI\data\documents\originals\x.pdf"})
    assert issues[0]["category"] == "windows absolute path"


def test_real_unix_absolute_path_triggers_leak() -> None:
    issues = metrics_module.public_value_issues({"title": "/var/lib/manufacturaiq/documents/x.pdf"})
    assert issues[0]["category"] == "unix absolute path"


def test_registry_db_path_triggers_leak() -> None:
    issues = metrics_module.public_value_issues({"error": r"D:\CMTI\data\documents\registry\documents.db"})
    assert any(issue["category"] == "windows absolute path" for issue in issues)
    assert any(issue["category"] == "registry DB path" for issue in issues)


def test_vector_store_path_triggers_leak() -> None:
    issues = metrics_module.public_value_issues({"error": r"D:\CMTI\data\documents\vectors\collection"})
    assert any(issue["category"] == "vector-store path" for issue in issues)


def test_sha_handling_matches_public_field_policy() -> None:
    digest = "a" * 64
    assert metrics_module.public_value_issues({"document_id": digest}) == []
    issues = metrics_module.public_value_issues({"sha256": digest})
    assert issues == [{"field": "sha256", "category": "sha-256"}]


def test_response_safe_fields_ok() -> None:
    body = {"document_id": "USR-X", "status": "READY", "duplicate": False,
            "documents": [], "count": 0, "deleted": True}
    ok, issues = metrics_module.response_safe_fields(body)
    assert ok is True
    assert issues == []


def test_response_safe_fields_flags_internals() -> None:
    ok, issues = metrics_module.response_safe_fields(
        {"document_id": "USR-X", "stored_filename": "x.pdf", "sha256": "abc"})
    assert ok is False
    assert issues


def test_fingerprint_stable() -> None:
    first = metrics_module.fingerprint(["A"], ["C1"], ["e1"], [1])
    second = metrics_module.fingerprint(["A"], ["C1"], ["e1"], [1])
    assert first == second


def test_latency_stats() -> None:
    stats = metrics_module.latency_stats([10.0, 20.0, 30.0, 40.0])
    assert stats["count"] == 4
    assert stats["median"] == 25.0
    assert stats["max"] == 40.0
    empty = metrics_module.latency_stats([])
    assert empty["count"] == 0 and empty["median"] is None
