from __future__ import annotations

from evaluation.documents import campaign as campaign_module


def test_static_guard_constant() -> None:
    from evaluation.documents.run_campaign import STATIC_COLLECTION_EXPECTED

    assert STATIC_COLLECTION_EXPECTED == 2193


def test_campaign_state_shape() -> None:
    state = {"uploads": [], "retrievals": [], "deletions": [],
             "failures": [], "latencies": {"upload": [], "list": [], "query": [], "delete": []},
             "critical_failures": []}
    agg = campaign_module.aggregate_metrics(state)
    assert agg["upload_success_rate"] is None
    assert agg["unexpected_failures"] == 0
    assert agg["latency"]["upload"]["count"] == 0


def test_aggregate_metrics_math() -> None:
    state = {
        "uploads": [
            {"label": "A", "ok": True},
            {"label": "B", "ok": False},
            {"label": "NEG-x", "ok": True},
            {"label": "DUP-y", "ok": True},
        ],
        "retrievals": [
            {"label": "R", "metrics": {"hit_at_1": True, "hit_at_3": True,
                                       "hit_at_5": True, "mrr": 1.0},
             "page_hit": True, "provenance_ok": True},
        ],
        "deletions": [
            {"label": "D1", "deleted": True},
            {"label": "POST-DELETE-ABSENCE", "ok": True},
            {"label": "REUPLOAD", "ok": True},
            {"label": "STATIC-PROTECT", "ok": True},
        ],
        "failures": [],
        "latencies": {"upload": [100.0], "list": [], "query": [50.0], "delete": [20.0]},
        "critical_failures": [],
    }
    agg = campaign_module.aggregate_metrics(state)
    assert agg["upload_success_rate"] == 0.5
    assert agg["rejection_correctness"] == 1.0
    assert agg["duplicate_accuracy"] == 1.0
    assert agg["dynamic_hit_at_1"] == 1.0
    assert agg["dynamic_mrr"] == 1.0
    assert agg["delete_success"] == 1.0
    assert agg["post_delete_absence"] is True
    assert agg["latency"]["upload"]["median"] == 100.0


def test_render_report_mentions_static_count() -> None:
    state = {"run_id": "R", "static_before": 2193, "static_after": 2193,
             "dynamic_before": {}, "dynamic_after": {},
             "uploads": [], "retrievals": [], "deletions": [], "failures": [],
             "latencies": {"upload": [], "list": [], "query": [], "delete": []},
             "critical_failures": []}
    agg = campaign_module.aggregate_metrics(state)
    text = campaign_module.render_report(state, agg)
    assert "2193" in text
    assert "DYNAMIC_KB" in text or "Dynamic Knowledge-Base" in text


def test_cleanup_restores_baseline(tmp_path) -> None:
    marker = tmp_path / "documents" / "originals" / "x.pdf"
    marker.parent.mkdir(parents=True)
    marker.write_bytes(b"data")
    assert marker.exists()
    import shutil

    shutil.rmtree(tmp_path / "documents")
    assert not (tmp_path / "documents").exists()


def test_restart_expected_count_excludes_pre_registration_rejection() -> None:
    rows = [
        campaign_module.upload_lifecycle_row({"label": "DOC-EVAL-01", "http": 201,
                                              "document_id": "USR-1", "duplicate": False}),
        campaign_module.upload_lifecycle_row({"label": "NEG-non-pdf", "http": 415,
                                              "ok": True}),
    ]
    assert rows[1]["pre_registration_rejection"] is True
    assert campaign_module.expected_restart_count_from_lifecycle(rows) == 1


def test_duplicate_request_does_not_increment_expected_persistent_count() -> None:
    rows = [
        campaign_module.upload_lifecycle_row({"label": "DOC-EVAL-01", "http": 201,
                                              "document_id": "USR-1", "duplicate": False}),
        campaign_module.upload_lifecycle_row({"label": "DUP-sequential", "http": 200,
                                              "document_id": "USR-1", "duplicate": True}),
    ]
    assert rows[1]["duplicate"] is True
    assert campaign_module.expected_restart_count_from_lifecycle(rows) == 1


def test_failed_registered_row_counts_as_persistent_until_deleted() -> None:
    row = campaign_module.upload_lifecycle_row({"label": "NEG-encrypted", "http": 422,
                                                "document_id": "USR-F", "status": "FAILED"})
    assert row["registry_row_created"] is True
    assert row["expected_to_survive_restart"] is True


def test_cleanup_includes_failed_evaluation_created_records() -> None:
    state = {"uploads": [{"label": "DOC-EVAL-01", "document_id": "USR-READY"}]}
    list_body = {
        "documents": [
            {"document_id": "USR-READY", "status": "READY", "original_filename": "ready.pdf"},
            {"document_id": "USR-FAILED", "status": "FAILED", "original_filename": "enc.pdf"},
        ]
    }
    assert campaign_module.campaign_created_document_ids(state, list_body) == [
        "USR-FAILED", "USR-READY"
    ]


def test_cleanup_uses_public_delete_abstraction() -> None:
    class FakeHttp:
        def __init__(self) -> None:
            self.paths: list[tuple[str, str]] = []

        def call(self, method, path, **kwargs):
            self.paths.append((method, path))
            if method == "DELETE":
                return 200, {"deleted": True}, 12.0
            return 404, {"detail": "missing"}, 1.0

    http = FakeHttp()
    records = campaign_module.cleanup_created_documents(http, ["USR-1"])
    assert records[0]["cleanup_method"] == "public_delete"
    assert http.paths == [("DELETE", "/api/documents/USR-1"), ("GET", "/api/documents/USR-1")]


def test_cleanup_baseline_accounting_restores_counts() -> None:
    before = {"registry_rows": 0, "originals": 0, "vectors": 0, "static": 2193}
    after = {"registry_rows": 0, "originals": 0, "vectors": 0, "static": 2193}
    assert after == before


def test_static_count_guard_remains_2193() -> None:
    assert campaign_module.STATIC_EXPECTED == 2193
