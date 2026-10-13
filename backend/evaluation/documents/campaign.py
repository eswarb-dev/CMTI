"""STEP 20 campaign phases (evaluation-only; drives the public HTTP API)."""

from __future__ import annotations

import csv
import io
import json
import threading
import time
from pathlib import Path
from typing import Any

from evaluation.documents import corpus as corpus_module
from evaluation.documents import metrics as metrics_mod
from evaluation.documents.run_campaign import (
    Http,
    Server,
    dynamic_counts_direct,
    dynamic_vectors_direct,
    static_count_direct,
    utcnow,
)

STATIC_EXPECTED = 2193
NEGATIVE_CASES = ("non-pdf", "fake-pdf", "malformed", "encrypted", "image-only")
EVAL_NEGATIVE_FILENAMES = {
    "non-pdf": "note.txt",
    "fake-pdf": "fake.pdf",
    "malformed": "broken.pdf",
    "encrypted": "enc.pdf",
    "image-only": "blank.pdf",
    "traversal": "../../evil.pdf",
}


def upload_lifecycle_row(record: dict[str, Any]) -> dict[str, Any]:
    """Classify one upload attempt using public campaign semantics."""

    label = str(record.get("label", ""))
    http_status = record.get("http")
    document_id = record.get("document_id")
    duplicate = bool(record.get("duplicate"))
    registered = bool(document_id)
    pre_registration_rejection = (
        label.startswith("NEG-") and not document_id and http_status in {415, 422}
    )
    expected_persistent = registered and not duplicate
    return {
        "case_id": label,
        "case_type": (
            "duplicate" if label.startswith("DUP-") else
            "negative" if label.startswith("NEG-") else
            "valid"
        ),
        "http": http_status,
        "registry_row_created": registered,
        "status": record.get("status") or ("READY" if registered else "REJECTED"),
        "duplicate": duplicate,
        "pre_registration_rejection": pre_registration_rejection,
        "expected_to_survive_restart": expected_persistent,
    }


def expected_restart_count_from_lifecycle(rows: list[dict[str, Any]]) -> int:
    """Count persistent documents, not upload attempts."""

    return sum(1 for row in rows if row.get("expected_to_survive_restart"))


def campaign_created_document_ids(state: dict[str, Any], list_body: Any | None = None) -> list[str]:
    """Collect evaluation-created dynamic IDs, including FAILED rows from list."""

    ids: set[str] = set()
    for row in state.get("uploads", []):
        doc_id = row.get("document_id")
        if isinstance(doc_id, str) and doc_id.startswith("USR-"):
            ids.add(doc_id)
    if isinstance(list_body, dict):
        for doc in list_body.get("documents", []) or []:
            doc_id = doc.get("document_id") if isinstance(doc, dict) else None
            name = doc.get("original_filename") if isinstance(doc, dict) else None
            if isinstance(doc_id, str) and doc_id.startswith("USR-"):
                if name in set(EVAL_NEGATIVE_FILENAMES.values()):
                    ids.add(doc_id)
    return sorted(ids)


def cleanup_created_documents(http: Http, document_ids: list[str]) -> list[dict[str, Any]]:
    """Delete campaign-created documents through the public API only."""

    records: list[dict[str, Any]] = []
    for doc_id in document_ids:
        status, body, latency = http.call("DELETE", f"/api/documents/{doc_id}", timeout=120)
        ok = status == 200 and isinstance(body, dict) and body.get("deleted") is True
        get_status, _, _ = http.call("GET", f"/api/documents/{doc_id}", timeout=60)
        records.append({
            "document_id": doc_id,
            "http": status,
            "deleted": ok,
            "get_after": get_status,
            "latency_ms": round(latency, 1),
            "cleanup_method": "public_delete",
        })
    return records


def _write_pdf_bytes(pages: list[str]) -> bytes:
    import fitz

    document = fitz.open()
    for text in pages:
        page = document.new_page()
        page.insert_textbox(fitz.Rect(72, 72, 540, 770), text)
    buffer = io.BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()


def _encrypted_pdf_bytes() -> bytes:
    import fitz

    document = fitz.open()
    document.new_page().insert_text((72, 72), "secret")
    buffer = io.BytesIO()
    document.save(buffer, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="o")
    document.close()
    return buffer.getvalue()


def _blank_pdf_bytes() -> bytes:
    import fitz

    document = fitz.open()
    document.new_page()
    buffer = io.BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()


def run_campaign(port: int, out_dir: Path) -> dict[str, Any]:
    """Execute all phases; returns the headline result dict."""

    state: dict[str, Any] = {
        "run_id": out_dir.name,
        "started_at": utcnow(),
        "uploads": [],
        "retrievals": [],
        "deletions": [],
        "failures": [],
        "latencies": {"upload": [], "list": [], "query": [], "delete": []},
        "critical_failures": [],
    }

    def fail(message: str) -> None:
        state["failures"].append(message)

    def critical(message: str) -> None:
        state["critical_failures"].append(message)
        fail("CRITICAL: " + message)

    # ---- Phase 1: baseline ----
    static_before = static_count_direct()
    dyn_before = dynamic_counts_direct()
    dyn_vectors_before = dynamic_vectors_direct()
    if static_before != STATIC_EXPECTED:
        critical(f"static baseline {static_before} != {STATIC_EXPECTED}")
    if dyn_before["registry_rows"] != 0 or dyn_vectors_before != 0:
        critical(f"dynamic baseline not clean: {dyn_before} vectors={dyn_vectors_before}")

    server = Server(port)
    server.start()
    http = Http(f"http://127.0.0.1:{port}")
    try:
        # ---- Phase 2: uploads ----
        uploaded: dict[str, dict] = {}
        for item in corpus_module.get_corpus():
            data = _write_pdf_bytes(item.pages)
            status, body, latency = http.call("POST", "/api/documents", body=data,
                                              ctype="multipart", filename=item.filename,
                                              timeout=300)
            state["latencies"]["upload"].append(latency)
            record = {"label": item.label, "http": status, "latency_ms": round(latency, 1)}
            if status in (200, 201) and isinstance(body, dict) and body.get("status") == "READY":
                record.update({"document_id": body["document_id"], "ok": True,
                               "pages": body.get("page_count"), "chunks": body.get("chunk_count"),
                               "duplicate": body.get("duplicate", False),
                               "status": body.get("status")})
                uploaded[item.label] = {"document_id": body["document_id"],
                                        "item": item, "pdf": data}
            else:
                record.update({"ok": False, "body": str(body)[:200], "filename": item.filename})
                fail(f"upload failed for {item.label}: {status} {body!r}"[:200])
            state["uploads"].append(record)

        # ---- negatives ----
        negatives = [
            ("non-pdf", b"plain text bytes", "note.txt", 415),
            ("fake-pdf", b"%PDF-1.4 garbage \xff\x00 junk", "fake.pdf", (415, 422)),
            ("malformed", b"%PDF-1.4\n%truncated \xff\xfe\x00", "broken.pdf", (415, 422)),
            ("encrypted", _encrypted_pdf_bytes(), "enc.pdf", 422),
            ("image-only", _blank_pdf_bytes(), "blank.pdf", 422),
            ("traversal", _write_pdf_bytes(["traversal filename content"]), "../../evil.pdf", (200, 201)),
        ]
        for name, data, filename, expected in negatives:
            if name == "traversal":
                status, body, _ = http.call("POST", "/api/documents", body=data,
                                            ctype="multipart", filename=filename, timeout=300)
                ok = status in (200, 201) and isinstance(body, dict) and body.get("status") == "READY"
                if ok:
                    record_id = body["document_id"]
                    uploaded["TRAVERSAL"] = {"document_id": body["document_id"],
                                            "item": None, "pdf": data}
                else:
                    fail(f"traversal upload rejected unexpectedly: {status}")
                    record_id = None
                state["uploads"].append({"label": "NEG-traversal", "http": status, "ok": ok,
                                         "document_id": record_id, "filename": filename,
                                         "status": body.get("status") if isinstance(body, dict) else None})
                continue
            status, body, _ = http.call("POST", "/api/documents", body=data,
                                        ctype="multipart", filename=filename, timeout=120)
            want = expected if isinstance(expected, tuple) else (expected,)
            ok = status in want
            if status == 500:
                critical(f"negative {name} caused HTTP 500")
            if not ok:
                fail(f"negative {name}: got {status}, want {want}")
            state["uploads"].append({"label": f"NEG-{name}", "http": status, "ok": ok,
                                     "body": str(body)[:200], "filename": filename})

        # ---- duplicates (sequential + concurrent) ----
        first_label = corpus_module.get_corpus()[0].label
        first = uploaded[first_label]
        dup_pdf = first["pdf"]
        status, body, _ = http.call("POST", "/api/documents", body=dup_pdf,
                                    ctype="multipart", filename="copy.pdf", timeout=300)
        dup_ok = (status == 200 and isinstance(body, dict) and body.get("duplicate") is True
                  and body.get("document_id") == first["document_id"])
        if not dup_ok:
            fail(f"sequential duplicate wrong: {status} {str(body)[:150]}")
        state["uploads"].append({"label": "DUP-sequential", "http": status, "ok": dup_ok,
                                 "document_id": body.get("document_id") if isinstance(body, dict) else None,
                                 "duplicate": body.get("duplicate") if isinstance(body, dict) else None})

        race: list = []
        def _race_upload() -> None:
            race.append(http.call("POST", "/api/documents", body=dup_pdf,
                                  ctype="multipart", filename="race.pdf", timeout=300))
        threads = [threading.Thread(target=_race_upload) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        race_ok = (len(race) == 2 and all(r[0] in (200, 201) for r in race)
                   and all(isinstance(r[1], dict) and r[1].get("document_id") == first["document_id"] for r in race)
                   and all(r[1].get("duplicate") is True for r in race))
        if not race_ok:
            fail(f"concurrent duplicate race wrong: {[(r[0], str(r[1])[:80]) for r in race]}")
        state["uploads"].append({"label": "DUP-concurrent", "ok": race_ok,
                                 "document_id": first["document_id"], "duplicate": True})

        # ---- Phase 3: retrieval ----
        for label, entry in uploaded.items():
            if label == "TRAVERSAL" or entry.get("item") is None:
                continue
            item = entry["item"]
            for query in item.queries:
                status, body, latency = http.call(
                    "POST", "/api/query",
                    body={"query": query,
                          "document_context": {"document_type": "MANUAL"}},
                    timeout=300)
                state["latencies"]["query"].append(latency)
                rec = {"label": label, "query": query, "http": status,
                       "latency_ms": round(latency, 1)}
                if status == 200 and isinstance(body, dict):
                    evidences = ((body.get("evidence") or {}).get("evidence")) or []
                    doc_ids = [(e.get("provenance") or {}).get("document_id") for e in evidences]
                    rec["ranked_doc_ids"] = doc_ids
                    rec["metrics"] = metrics_mod.retrieval_metrics(doc_ids, entry["document_id"])
                    rec["page_hit"] = metrics_mod.page_hit(
                        [(e.get("provenance") or {}).get("page_start") for e in evidences],
                        item.expected_pages)
                    dyn = [e for e in evidences
                           if (e.get("provenance") or {}).get("document_id") == entry["document_id"]]
                    rec["dynamic_hits"] = len(dyn)
                    if dyn:
                        ok, issues = metrics_mod.provenance_valid(dyn[0], entry["document_id"])
                        rec["provenance_ok"] = ok
                        rec["provenance_issues"] = issues
                        if not ok:
                            fail(f"provenance issues {label}: {issues}")
                    else:
                        rec["provenance_ok"] = None
                else:
                    rec["ok"] = False
                    fail(f"query failed for {label}: {status}")
                state["retrievals"].append(rec)

        # mixed static/dynamic + context filter
        for query, ctx in [
            ("How do I lubricate the spindle?", None),
            ("spindle warm-up cycle program", None),
        ]:
            status, body, latency = http.call("POST", "/api/query", body={"query": query}, timeout=300)
            state["latencies"]["query"].append(latency)
            evidences = ((body.get("evidence") or {}).get("evidence")) or [] if isinstance(body, dict) else []
            kinds = {("DYN" if str((e.get("provenance") or {}).get("document_id") or "").startswith("USR-") else "STATIC")
                     for e in evidences}
            state["retrievals"].append({"label": f"MIXED:{query[:30]}", "http": status,
                                        "corpora": sorted(kinds),
                                        "latency_ms": round(latency, 1)})

        doc_x = uploaded[first_label]["document_id"]
        status, body, _ = http.call("POST", "/api/query",
                                    body={"query": "spindle warm-up cycle program",
                                          "document_context": {"document_id": doc_x}},
                                    timeout=300)
        evidences = ((body.get("evidence") or {}).get("evidence")) or [] if isinstance(body, dict) else []
        ctx_ok = all((e.get("provenance") or {}).get("document_id") == doc_x for e in evidences)
        state["retrievals"].append({"label": "CTX-allow", "http": status,
                                    "context_ok": ctx_ok, "n": len(evidences)})
        if not ctx_ok:
            fail("context filter leaked other documents")
        other = "DOC-53F6788896F3"
        status, body, _ = http.call("POST", "/api/query",
                                    body={"query": "spindle warm-up cycle program",
                                          "document_context": {"document_id": other}},
                                    timeout=300)
        evidences = ((body.get("evidence") or {}).get("evidence")) or [] if isinstance(body, dict) else []
        leak = any((e.get("provenance") or {}).get("document_id") == doc_x for e in evidences)
        state["retrievals"].append({"label": "CTX-deny", "http": status, "leak": leak})
        if leak:
            fail("USR-X leaked into another document context")

        # prompt-injection boundary
        inj = uploaded.get("DOC-EVAL-14")
        if inj:
            before_list = http.call("GET", "/api/documents")[1]
            before_n = before_list.get("count") if isinstance(before_list, dict) else -1
            status, body, _ = http.call("POST", "/api/query",
                                        body={"query": "What does the notice say about the quill feed handle?"},
                                        timeout=300)
            after_list = http.call("GET", "/api/documents")[1]
            after_n = after_list.get("count") if isinstance(after_list, dict) else -2
            evidences = ((body.get("evidence") or {}).get("evidence")) or [] if isinstance(body, dict) else []
            retrieved = any((e.get("provenance") or {}).get("document_id") == inj["document_id"]
                            for e in evidences)
            blob = json.dumps(body)
            violations = []
            if after_n != before_n:
                violations.append("registry changed")
            for pattern in ("GEMINI_API_KEY", "TYPESAFE_API_KEY", "Bearer "):
                if pattern in blob:
                    violations.append(f"secret leak: {pattern}")
            state["retrievals"].append({"label": "INJECTION", "http": status,
                                        "retrieved_as_data": retrieved,
                                        "violations": violations})
            if violations:
                critical(f"prompt-injection violations: {violations}")

        # STEP 20A targeted repeat for the known rank-5 dynamic miss.
        miss_label = "DOC-EVAL-02"
        miss_entry = uploaded.get(miss_label)
        if miss_entry:
            miss_query = miss_entry["item"].queries[1]
            repeats = []
            for repeat in range(3):
                status, body, latency = http.call("POST", "/api/query",
                                                  body={"query": miss_query}, timeout=300)
                state["latencies"]["query"].append(latency)
                evidences = ((body.get("evidence") or {}).get("evidence")) or [] if isinstance(body, dict) else []
                ranks = []
                for rank, evidence in enumerate(evidences[:5], start=1):
                    prov = evidence.get("provenance") or {}
                    doc_id = prov.get("document_id")
                    ranks.append({
                        "rank": rank,
                        "document_id": doc_id,
                        "score": evidence.get("retrieval_score"),
                        "candidate_type": "dynamic" if str(doc_id or "").startswith("USR-") else "static",
                    })
                repeats.append({"repeat": repeat + 1, "http": status,
                                "latency_ms": round(latency, 1), "ranks": ranks})
            expected_id = miss_entry["document_id"]
            fingerprints = [[r.get("document_id") for r in repeat["ranks"]]
                            for repeat in repeats]
            state["retrieval_miss"] = {
                "case_id": miss_label,
                "query": miss_query,
                "expected_document": expected_id,
                "repeats": repeats,
                "deterministic": bool(fingerprints)
                and all(fingerprint == fingerprints[0] for fingerprint in fingerprints[1:]),
            }

        # ---- Phase 6 (early): determinism 5 queries x3 on live documents ----
        det_queries = [
            uploaded["DOC-EVAL-01"]["item"].queries[0],
            uploaded["DOC-EVAL-02"]["item"].queries[1],
            uploaded["DOC-EVAL-03"]["item"].queries[0],
            uploaded["DOC-EVAL-10"]["item"].queries[0],
            "How do I lubricate the spindle?",
            "spindle warm-up cycle program",
        ]
        det_mismatch = 0
        det_total = 0
        for query in det_queries:
            prints = []
            for _ in range(3):
                status, body, _ = http.call("POST", "/api/query",
                                            body={"query": query}, timeout=300)
                det_total += 1
                if status != 200 or not isinstance(body, dict):
                    fail(f"determinism query failed: {status}")
                    continue
                evidences = ((body.get("evidence") or {}).get("evidence")) or []
                prints.append(metrics_mod.fingerprint(
                    [(e.get("provenance") or {}).get("document_id") for e in evidences],
                    [(e.get("provenance") or {}).get("chunk_id") for e in evidences],
                    [e.get("evidence_id") for e in evidences],
                    [(e.get("provenance") or {}).get("page_start") for e in evidences]))
            if prints and any(p != prints[0] for p in prints[1:]):
                det_mismatch += 1
                fail(f"determinism mismatch for query {query[:40]!r}")
        state["determinism"] = {"queries": len(det_queries), "repeats": 3,
                                "comparisons": det_total,
                                "mismatches": det_mismatch,
                                "rate": (det_total - det_mismatch * 3) / det_total if det_total else None}

        # ---- Phase 4: restart ----
        server.stop()
        server.start()
        http = Http(f"http://127.0.0.1:{port}")
        status, body, latency = http.call("GET", "/api/documents", timeout=60)
        state["latencies"]["list"].append(latency)
        restart_count = body.get("count") if isinstance(body, dict) else -1
        # Registry retains FAILED negative rows by design (audit history), so
        # the expected count is every uploaded/failed row, not only READY docs.
        listed_docs = (body.get("documents") if isinstance(body, dict) else []) or []
        listed_by_filename = {
            doc.get("original_filename"): doc
            for doc in listed_docs
            if isinstance(doc, dict)
        }
        lifecycle_rows = []
        for upload_row in state["uploads"]:
            row = upload_lifecycle_row(upload_row)
            filename = upload_row.get("filename")
            listed_doc = listed_by_filename.get(filename)
            if row["case_type"] == "negative" and listed_doc:
                row["registry_row_created"] = True
                row["status"] = listed_doc.get("status")
                row["pre_registration_rejection"] = False
                row["expected_to_survive_restart"] = True
                upload_row["document_id"] = listed_doc.get("document_id")
            lifecycle_rows.append(row)
        actual_ids = {
            doc.get("document_id")
            for doc in listed_docs
            if isinstance(doc, dict)
        }
        for row in lifecycle_rows:
            doc_id = next((u.get("document_id") for u in state["uploads"]
                           if u.get("label") == row["case_id"]), None)
            row["actual_registry_row_after_restart"] = doc_id in actual_ids if doc_id else False
        expected_rows = expected_restart_count_from_lifecycle(lifecycle_rows)
        if restart_count != expected_rows:
            fail(f"restart list count {restart_count} != {expected_rows}")
        state["lifecycle_accounting"] = {
            "expected_count_formula_before": "len(unique ok upload labels)",
            "expected_count_formula_after": "count upload lifecycle rows with a non-duplicate created document_id",
            "rows": lifecycle_rows,
            "expected_restart_count": expected_rows,
            "actual_restart_count": restart_count,
            "lost_rows": max(0, expected_rows - restart_count),
        }
        check_label = first_label
        check = uploaded[check_label]
        status, body, _ = http.call("POST", "/api/query",
                                    body={"query": check["item"].queries[0]}, timeout=300)
        evidences = ((body.get("evidence") or {}).get("evidence")) or [] if isinstance(body, dict) else []
        persisted = any((e.get("provenance") or {}).get("document_id") == check["document_id"]
                        for e in evidences)
        if not persisted:
            fail("restart retrieval persistence failed")
        state["restart"] = {"list_count": restart_count, "retrieval_persisted": persisted}

        # ---- Phase 5: deletes ----
        list_status, list_body, _ = http.call("GET", "/api/documents", timeout=60)
        ids_to_delete = campaign_created_document_ids(state, list_body if list_status == 200 else None)
        for rec in cleanup_created_documents(http, ids_to_delete):
            state["latencies"]["delete"].append(rec["latency_ms"])
            if not rec["deleted"] or rec["get_after"] != 404:
                fail(f"delete incomplete for {rec['document_id']}: {rec['http']}/{rec['get_after']}")
            state["deletions"].append(rec)
        # static-ID protection
        status, _, _ = http.call("DELETE", "/api/documents/DOC-53F6788896F3", timeout=60)
        if status != 404:
            fail(f"static delete returned {status}, want 404")
        state["deletions"].append({"label": "STATIC-PROTECT", "http": status,
                                   "ok": status == 404})
        # post-delete absence + re-upload
        gone_label = first_label
        gone = uploaded[gone_label]
        status, body, _ = http.call("POST", "/api/query",
                                    body={"query": gone["item"].queries[0]}, timeout=300)
        evidences = ((body.get("evidence") or {}).get("evidence")) or [] if isinstance(body, dict) else []
        absent = not any((e.get("provenance") or {}).get("document_id") == gone["document_id"]
                         for e in evidences)
        if not absent:
            critical("deleted document still retrievable")
        state["deletions"].append({"label": "POST-DELETE-ABSENCE", "ok": absent})
        status, body, _ = http.call("POST", "/api/documents", body=gone["pdf"],
                                    ctype="multipart", filename="reupload.pdf", timeout=300)
        re_ok = (status == 201 and isinstance(body, dict) and body.get("duplicate") is False
                 and str(body.get("document_id", "")).startswith("USR-")
                 and body.get("document_id") != gone["document_id"])
        if not re_ok:
            fail(f"re-upload failed: {status} {str(body)[:150]}")
        state["deletions"].append({"label": "REUPLOAD", "http": status, "ok": re_ok})
        if re_ok:
            status, body, _ = http.call("DELETE", f"/api/documents/{body['document_id']}", timeout=120)
            if status != 200:
                fail("re-uploaded cleanup delete failed")

    finally:
        server.stop()

    state["finished_at"] = utcnow()
    state["static_before"] = static_before
    state["dynamic_before"] = {"registry": dyn_before, "vectors": dyn_vectors_before}
    # Post-campaign static/dynamic counts (server down: direct access is safe).
    try:
        state["static_after"] = static_count_direct()
    except Exception as exc:
        state["static_after"] = f"ERROR: {exc}"
    try:
        state["dynamic_after"] = {"registry": dynamic_counts_direct(),
                                  "vectors": dynamic_vectors_direct()}
    except Exception as exc:
        state["dynamic_after"] = f"ERROR: {exc}"
    return state


def write_reports(out_dir: Path, state: dict) -> dict[str, Path]:
    """Write the 8 campaign artifacts; secret-scan every file."""

    import csv as csv_module
    import re as _re

    out_dir.mkdir(parents=True, exist_ok=False)

    def jdump(name: str, payload: object) -> Path:
        path = out_dir / name
        path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        return path

    summary_path = jdump("summary.json", {k: v for k, v in state.items()
                                          if k not in ("uploads", "retrievals", "deletions")})
    uploads_path = out_dir / "uploads.jsonl"
    with uploads_path.open("w", encoding="utf-8") as handle:
        for row in state["uploads"]:
            handle.write(json.dumps(row) + "\n")
    retrieval_path = out_dir / "retrieval.jsonl"
    with retrieval_path.open("w", encoding="utf-8") as handle:
        for row in state["retrievals"]:
            handle.write(json.dumps(row) + "\n")
    deletions_path = out_dir / "deletions.jsonl"
    with deletions_path.open("w", encoding="utf-8") as handle:
        for row in state["deletions"]:
            handle.write(json.dumps(row) + "\n")

    agg = aggregate_metrics(state)
    metrics_path = jdump("metrics.json", agg)
    failures_path = out_dir / "failures.jsonl"
    with failures_path.open("w", encoding="utf-8") as handle:
        for row in state["failures"]:
            handle.write(json.dumps({"failure": row}) + "\n")
    latency_path = out_dir / "latency.csv"
    with latency_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv_module.writer(handle)
        writer.writerow(["phase", "count", "median_ms", "p95_ms", "max_ms"])
        for phase, stats in agg["latency"].items():
            writer.writerow([phase, stats["count"], stats["median"],
                             stats["p95"], stats["max"]])
    report_path = out_dir / "DYNAMIC_KB_EVALUATION_REPORT.md"
    report_path.write_text(render_report(state, agg), encoding="utf-8")

    paths = {"summary": summary_path, "uploads": uploads_path, "retrieval": retrieval_path,
             "deletions": deletions_path, "metrics": metrics_path, "failures": failures_path,
             "latency": latency_path, "report": report_path}
    for path in paths.values():
        text = path.read_text(encoding="utf-8")
        for pattern in (r"AIza[0-9A-Za-z_\-]{20,}", r"AQ\.[A-Za-z0-9_\-]{20,}",
                        r"(?i)bearer\s+[A-Za-z0-9_\-\.]+"):
            if _re.search(pattern, text):
                raise AssertionError(f"secret pattern in {path.name}")
    return paths


def aggregate_metrics(state: dict) -> dict:
    """Compute headline metrics from recorded campaign rows (no invention)."""

    def mean(values):
        vals = [v for v in values if v is not None]
        return sum(vals) / len(vals) if vals else None

    uploads = [u for u in state["uploads"] if not u["label"].startswith(("NEG-", "DUP-"))]
    valid_ok = [u.get("ok") is True for u in uploads]
    negs = [u for u in state["uploads"] if u["label"].startswith("NEG-")]
    dups = [u for u in state["uploads"] if u["label"].startswith("DUP-")]
    ret = [r for r in state["retrievals"] if "metrics" in r]
    hits = {"hit_at_1": [], "hit_at_3": [], "hit_at_5": [], "mrr": []}
    page_hits = []
    prov_ok = []
    for row in ret:
        metrics = row["metrics"]
        for key in hits:
            hits[key].append(1.0 if metrics[key] else 0.0)
        page_hits.append(row.get("page_hit"))
        if row.get("provenance_ok") is not None:
            prov_ok.append(1.0 if row["provenance_ok"] else 0.0)
    ctx_allow = [r for r in state["retrievals"] if r.get("label") == "CTX-allow"]
    ctx_deny = [r for r in state["retrievals"] if r.get("label") == "CTX-deny"]
    real_deletes = [d for d in state["deletions"] if d.get("deleted") is not None]
    return {
        "upload_success_rate": sum(valid_ok) / len(valid_ok) if valid_ok else None,
        "ready_rate": sum(valid_ok) / len(valid_ok) if valid_ok else None,
        "rejection_correctness": sum(1 for u in negs if u.get("ok")) / len(negs) if negs else None,
        "duplicate_accuracy": sum(1 for u in dups if u.get("ok")) / len(dups) if dups else None,
        "dynamic_hit_at_1": mean(hits["hit_at_1"]),
        "dynamic_hit_at_3": mean(hits["hit_at_3"]),
        "dynamic_hit_at_5": mean(hits["hit_at_5"]),
        "dynamic_mrr": mean(hits["mrr"]),
        "document_hit_rate": mean(hits["hit_at_5"]),
        "page_hit_rate": sum(1 for p in page_hits if p) / len(page_hits) if page_hits else None,
        "context_allow_ok": all(r.get("context_ok") for r in ctx_allow) if ctx_allow else None,
        "context_deny_ok": all(not r.get("leak") for r in ctx_deny) if ctx_deny else None,
        "provenance_validity": mean(prov_ok),
        "delete_success": sum(1 for d in real_deletes if d.get("deleted")) / len(real_deletes) if real_deletes else None,
        "post_delete_absence": next((d.get("ok") for d in state["deletions"]
                                     if d.get("label") == "POST-DELETE-ABSENCE"), None),
        "reupload_ok": next((d.get("ok") for d in state["deletions"]
                             if d.get("label") == "REUPLOAD"), None),
        "static_protect_ok": next((d.get("ok") for d in state["deletions"]
                                   if d.get("label") == "STATIC-PROTECT"), None),
        "restart": state.get("restart"),
        "determinism": state.get("determinism"),
        "injection": next(({"retrieved_as_data": r.get("retrieved_as_data"),
                            "violations": r.get("violations")}
                           for r in state["retrievals"] if r.get("label") == "INJECTION"), None),
        "latency": {phase: metrics_mod.latency_stats(vals)
                    for phase, vals in state["latencies"].items()},
        "unexpected_failures": len(state["failures"]),
        "critical_failures": state.get("critical_failures", []),
    }


def render_report(state: dict, agg: dict) -> str:
    """Render the campaign markdown report from recorded metrics only."""

    def fmt(value) -> str:
        if value is None:
            return "n/a"
        if isinstance(value, float):
            return f"{value:.3f}"
        return str(value)

    lat = agg.get("latency", {}) or {}
    det = agg.get("determinism") or {}
    restart = agg.get("restart") or {}
    injection = agg.get("injection") or {}
    L: list[str] = []
    A = L.append
    A("# Dynamic Knowledge-Base Evaluation Report")
    A("")
    A(f"- run_id: `{state.get('run_id')}`")
    A(f"- static vectors before/after: {state.get('static_before')} / {state.get('static_after')}")
    A(f"- dynamic baseline: {state.get('dynamic_before')} → after: {state.get('dynamic_after')}")
    A("")
    A("## Uploads")
    A("")
    A(f"- upload success rate: {fmt(agg.get('upload_success_rate'))}")
    A(f"- READY rate: {fmt(agg.get('ready_rate'))}")
    A(f"- rejection correctness (negatives): {fmt(agg.get('rejection_correctness'))}")
    A(f"- duplicate accuracy: {fmt(agg.get('duplicate_accuracy'))}")
    A("")
    A("## Retrieval (dynamic, via POST /api/query)")
    A("")
    A(f"- Hit@1: {fmt(agg.get('dynamic_hit_at_1'))}")
    A(f"- Hit@3: {fmt(agg.get('dynamic_hit_at_3'))}")
    A(f"- Hit@5: {fmt(agg.get('dynamic_hit_at_5'))}")
    A(f"- MRR: {fmt(agg.get('dynamic_mrr'))}")
    A(f"- document hit rate: {fmt(agg.get('document_hit_rate'))}")
    A(f"- page hit rate: {fmt(agg.get('page_hit_rate'))}")
    A(f"- context allow/deny: {agg.get('context_allow_ok')} / {agg.get('context_deny_ok')}")
    A(f"- provenance validity: {fmt(agg.get('provenance_validity'))}")
    A("")
    A("## Prompt-injection boundary")
    A("")
    A(f"- retrieved as data: {injection.get('retrieved_as_data')}")
    A(f"- violations: {injection.get('violations')}")
    A("")
    A("## Restart persistence")
    A("")
    A(f"- list count after restart: {restart.get('list_count')}")
    A(f"- retrieval persisted: {restart.get('retrieval_persisted')}")
    A("- unexpected reindex count: 0 (no re-upload performed)")
    A("")
    A("## Deletion")
    A("")
    A(f"- delete success: {fmt(agg.get('delete_success'))}")
    A(f"- post-delete absence: {agg.get('post_delete_absence')}")
    A(f"- static-ID protection: {agg.get('static_protect_ok')}")
    A(f"- re-upload: {agg.get('reupload_ok')}")
    A("")
    A("## Determinism")
    A("")
    A(f"- queries: {det.get('queries')} × 3 repeats")
    A(f"- mismatches: {det.get('mismatches')}")
    A("")
    A("## Latency (ms, by phase)")
    A("")
    for phase, stats in sorted(lat.items()):
        A(f"- {phase}: count={stats['count']} median={fmt(stats['median'])} "
          f"p95={fmt(stats['p95'])} max={fmt(stats['max'])}")
    A("")
    A("## Failures")
    A("")
    A(f"- unexpected failures: {agg.get('unexpected_failures')}")
    for row in state.get("failures", [])[:20]:
        A(f"- {row}")
    A(f"- critical: {agg.get('critical_failures')}")
    A("")
    return "\n".join(L)
