"""Pure metric helpers for the STEP 20 dynamic-KB campaign (no I/O)."""

from __future__ import annotations

import re
import statistics
from typing import Any

_SAFE_FIELDS = {
    "document_id", "original_filename", "mime_type", "file_size_bytes",
    "status", "page_count", "chunk_count", "created_at", "updated_at",
    "error_code", "error_message", "duplicate", "documents", "count",
    "deleted", "error",
}

_SECRET_PATTERNS = (
    re.compile(r"(?i)(gemini_api_key|typesafe_api_key)\s*[:=]\s*\S+"),
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"AQ\.[A-Za-z0-9_\-]{20,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-\.]+"),
)

_WINDOWS_ABSOLUTE_PATH = re.compile(r"\b[A-Za-z]:\\[^'\"\s]+")
_UNIX_ABSOLUTE_PATH = re.compile(r"(^|[\s'\":])/(tmp|var|home|root|data|app)/[^'\"\s]+")
_REGISTRY_DB_PATH = re.compile(r"(?i)(documents|registry)[^'\"\s]*\.db\b|\.db\b")
_VECTOR_STORE_PATH = re.compile(r"(?i)(qdrant|vector[_-]?store|vectors[/\\][^'\"\s]+)")
_SHA256_VALUE = re.compile(r"\b[a-fA-F0-9]{64}\b")
_SHA256_LABEL = re.compile(r"(?i)\bsha[-_]?256\b")


def forbidden_public_value_issues(key: str, value: Any) -> list[str]:
    """Classify forbidden internal public values without flagging Unicode text.

    Public document identity such as document_id, title, filename, page, and
    chunk IDs is allowed. This scanner is intentionally value-specific: words
    like "path", Unicode punctuation, slashes inside ordinary titles, and short
    IDs are not leaks unless they reveal an internal path or server-only hash.
    """

    if not isinstance(value, str):
        return []
    issues: list[str] = []
    if key == "stored_filename":
        issues.append("stored_filename")
    if _WINDOWS_ABSOLUTE_PATH.search(value):
        issues.append("windows absolute path")
    if _UNIX_ABSOLUTE_PATH.search(value):
        issues.append("unix absolute path")
    if _REGISTRY_DB_PATH.search(value):
        issues.append("registry DB path")
    if _VECTOR_STORE_PATH.search(value):
        issues.append("vector-store path")
    if key.lower() in {"sha256", "sha_256", "checksum_sha256"} and _SHA256_VALUE.search(value):
        issues.append("sha-256")
    if _SHA256_LABEL.search(key) and _SHA256_VALUE.search(value):
        issues.append("sha-256")
    return list(dict.fromkeys(issues))


def public_value_issues(payload: Any) -> list[dict[str, str]]:
    """Return classified public-data leaks with field path and category."""

    issues: list[dict[str, str]] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                child = f"{path}.{key}" if path else key
                for issue in forbidden_public_value_issues(key, item):
                    issues.append({"field": child, "category": issue})
                walk(item, child)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")

    walk(payload, "")
    return issues


def retrieval_metrics(ranked_doc_ids: list[str | None], expected_doc_id: str,
                      ks: tuple[int, ...] = (1, 3, 5)) -> dict[str, Any]:
    """Hit@k + MRR for one query against one expected dynamic document."""

    out: dict[str, Any] = {}
    for k in ks:
        out[f"hit_at_{k}"] = expected_doc_id in [d for d in ranked_doc_ids[:k] if d]
    rr = 0.0
    for rank, doc_id in enumerate(ranked_doc_ids, start=1):
        if doc_id == expected_doc_id:
            rr = 1.0 / rank
            break
    out["mrr"] = rr
    return out


def page_hit(evidence_pages: list[int | None], expected_pages: list[int]) -> bool | None:
    if not expected_pages:
        return None
    actual = {p for p in evidence_pages if p}
    return bool(actual & set(expected_pages))


def provenance_valid(evidence: dict[str, Any], expected_doc_id: str) -> tuple[bool, list[str]]:
    """Check one dynamic evidence item's provenance; returns (ok, issues)."""

    issues: list[str] = []
    prov = evidence.get("provenance", {}) or {}
    if not str(prov.get("document_id") or "").startswith("USR-"):
        issues.append("document_id not USR-*")
    if prov.get("document_id") != expected_doc_id:
        issues.append("document_id mismatch")
    page = prov.get("page_start")
    if not isinstance(page, int) or page < 1:
        issues.append("bad page")
    if not prov.get("chunk_id"):
        issues.append("missing chunk_id")
    if not evidence.get("title"):
        issues.append("missing title")
    if prov.get("source_dataset") != "manufacturaiq_dynamic_documents":
        issues.append("wrong source dataset")
    if evidence.get("retrieval_score") is None:
        issues.append("missing retrieval score")
    for pattern in _SECRET_PATTERNS:
        if pattern.search(str(evidence)):
            issues.append("secret pattern")
    for leak in public_value_issues(evidence):
        issues.append(f"path/identity leak: {leak['field']} ({leak['category']})")
    return (not issues, issues)


def response_safe_fields(body: Any) -> tuple[bool, list[str]]:
    """Public API bodies must expose only safe fields (recursively)."""

    issues: list[str] = []

    def walk(value: Any, where: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key not in _SAFE_FIELDS and where in ("upload", "list", "get", "delete"):
                    # 'detail'/'error_code' wrappers from FastAPI errors are allowed.
                    if key not in ("detail",):
                        issues.append(f"unexpected field: {key}")
                walk(item, where)
        elif isinstance(value, list):
            for item in value:
                walk(item, where)

    if isinstance(body, dict):
        walk(body, "upload")
    text = str(body)
    for pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            issues.append("secret pattern")
    return (not issues, issues)


def fingerprint(doc_ids: list, chunk_ids: list, order: list, pages: list) -> dict[str, Any]:
    return {"doc_ids": list(doc_ids), "chunk_ids": list(chunk_ids),
            "order": list(order), "pages": list(pages)}


def latency_stats(values_ms: list[float]) -> dict[str, Any]:
    if not values_ms:
        return {"count": 0, "median": None, "p95": None, "max": None}
    ordered = sorted(values_ms)
    p95 = ordered[max(0, min(len(ordered) - 1, int(0.95 * len(ordered))))]
    return {"count": len(ordered), "median": statistics.median(ordered),
            "p95": p95, "max": ordered[-1]}
