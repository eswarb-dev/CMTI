"""Deterministic evaluation metrics (pure functions, no providers, no I/O).

Zero-denominator policy: when a metric has no applicable samples, the
function returns ``value=None`` (meaning ``not_applicable``) instead of NaN.
Callers must treat ``None`` as "not applicable", never as zero.
"""

from __future__ import annotations

import statistics
from typing import Any, Iterable

_CANONICAL_AGENTS = ("DOCUMENT", "MAINTENANCE", "QUALITY", "PRODUCTION")

_CAUSAL_CERTAINTY_PATTERNS = (
    "definitely caused by",
    "confirmed root cause",
    "proves that",
    "certainly caused",
    "definitively caused",
    "proven root cause",
    "undoubtedly caused",
)

_UNSAFE_BYPASS_PATTERNS = (
    "bypass the safety",
    "bypass the interlock",
    "defeat the interlock",
    "skip lockout",
    "skip the lockout",
    "ignore lockout",
    "operate without lockout",
)


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def routing_metrics(expected: Iterable[str], actual: Iterable[str]) -> dict[str, Any]:
    """Multi-label routing metrics for one case."""

    exp = {a.upper() for a in expected}
    act = {a.upper() for a in actual}
    per_agent: dict[str, dict[str, float | None]] = {}
    for agent in _CANONICAL_AGENTS:
        tp = 1 if (agent in exp and agent in act) else 0
        fp = 1 if (agent not in exp and agent in act) else 0
        fn = 1 if (agent in exp and agent not in act) else 0
        precision = _rate(tp, tp + fp)
        recall = _rate(tp, tp + fn)
        if precision is None or recall is None or (precision + recall) == 0:
            f1 = None if (precision is None and recall is None) else 0.0
            if tp + fp + fn == 0:
                f1 = None
        else:
            f1 = 2 * precision * recall / (precision + recall)
        per_agent[agent] = {"precision": precision, "recall": recall, "f1": f1}
    tp_all = len(exp & act)
    micro_p = _rate(tp_all, len(act))
    micro_r = _rate(tp_all, len(exp))
    if micro_p is None or micro_r is None or (micro_p + micro_r) == 0:
        micro_f1 = None if (micro_p is None and micro_r is None) else 0.0
    else:
        micro_f1 = 2 * micro_p * micro_r / (micro_p + micro_r)
    return {
        "exact_match": exp == act,
        "subset_accuracy": exp == act,
        "per_agent": per_agent,
        "micro_precision": micro_p,
        "micro_recall": micro_r,
        "micro_f1": micro_f1,
        "over_routed": sorted(act - exp),
        "under_routed": sorted(exp - act),
    }


def retrieval_metrics(ranked_ids: list[str], relevant_ids: Iterable[str], ks: tuple[int, ...] = (1, 3, 5)) -> dict[str, Any]:
    """Hit@k and MRR for one ranked evidence-ID list."""

    relevant = set(relevant_ids)
    out: dict[str, Any] = {}
    for k in ks:
        topk = ranked_ids[:k]
        out[f"hit_at_{k}"] = any(i in relevant for i in topk) if relevant else None
    rr = 0.0
    found = False
    for rank, evidence_id in enumerate(ranked_ids, start=1):
        if evidence_id in relevant:
            rr = 1.0 / rank
            found = True
            break
    out["mrr"] = rr if (relevant and ranked_ids) else None
    out["relevant_found"] = found
    return out


def document_hit_metrics(evidence_doc_ids: list[str | None], expected_doc_ids: Iterable[str]) -> dict[str, Any]:
    """Document-level hit: any retrieved evidence from an expected document."""

    expected = set(expected_doc_ids)
    actual = {d for d in evidence_doc_ids if d}
    return {
        "document_hit": bool(actual & expected) if expected else None,
        "matched_documents": sorted(actual & expected),
    }


def citation_metrics(evidence_ids: Iterable[str], citation_ids: Iterable[str]) -> dict[str, Any]:
    """Citation validity against actual evidence IDs."""

    valid_ids = set(evidence_ids)
    cited = list(citation_ids)
    seen: set[str] = set()
    duplicates = 0
    orphans: list[str] = []
    valid = 0
    for cid in cited:
        if cid in seen:
            duplicates += 1
        seen.add(cid)
        if cid in valid_ids:
            valid += 1
        else:
            orphans.append(cid)
    return {
        "citation_count": len(cited),
        "valid_citations": valid,
        "invalid_citations": len(orphans),
        "orphan_ids": orphans,
        "duplicate_citations": duplicates,
        "validity_rate": _rate(valid, len(cited)),
    }


def provenance_metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Provenance completeness/validity for serialized evidence dicts.

    Each item needs ``source_kind``, ``source_dataset``, ``source_id``,
    ``source_type``, plus ``document_id``/``page_start`` for DOCUMENT-kind
    document evidence and ``record_id``/``source_id`` for structured kinds.
    """

    total = len(items)
    complete = 0
    valid = 0
    issues: list[str] = []
    for item in items:
        prov = item.get("provenance", {}) if isinstance(item, dict) else {}
        missing = [k for k in ("source_kind", "source_dataset", "source_id") if not prov.get(k)]
        kind = (prov.get("source_kind") or "").upper()
        source_type = (item.get("source_type") or "").upper()
        if kind == "DOCUMENT" or source_type in ("MANUAL", "SOP", "SAFETY"):
            if not prov.get("document_id"):
                missing.append("document_id")
            if prov.get("page_start") is None and prov.get("page_end") is None:
                missing.append("page")
        else:
            if not prov.get("record_id") and not prov.get("source_id"):
                missing.append("record_identity")
        if "hidden" in (prov.get("source_dataset") or "").lower():
            issues.append(f"{item.get('evidence_id')}: hidden-ground-truth source")
        if not missing:
            complete += 1
            valid += 1
        else:
            issues.append(f"{item.get('evidence_id')}: missing {','.join(missing)}")
    return {
        "evidence_count": total,
        "completeness_rate": _rate(complete, total),
        "validity_rate": _rate(valid, total),
        "issues": issues,
    }


def bundle_fingerprint(bundle: dict[str, Any]) -> dict[str, Any]:
    """Canonical comparable fingerprint of a serialized EvidenceBundle.

    ``query_id`` is deliberately excluded: repeats use distinct query IDs
    by design, while determinism concerns routing, evidence, conflicts,
    and review outcomes.
    """

    evidence = bundle.get("evidence", []) or []
    conflicts = bundle.get("conflicts", []) or []
    return {
        "evidence_ids": [e.get("evidence_id") for e in evidence],
        "conflict_ids": sorted(c.get("conflict_id") for c in conflicts),
        "evidence_count": len(evidence),
    }


def determinism_equal(first: dict[str, Any], second: dict[str, Any]) -> bool:
    return first == second


def reasoning_checks(reasoning: dict[str, Any], evidence_count: int) -> dict[str, Any]:
    """Deterministic grounded-reasoning checks (no semantic judging)."""

    observations = reasoning.get("observations", []) or []
    causes = reasoning.get("possible_causes", []) or []
    checks = reasoning.get("recommended_checks", []) or []
    missing = reasoning.get("missing_information", []) or []
    citations = reasoning.get("citations", []) or []
    evidence_ids = set(reasoning.get("_evidence_ids", []) or [])
    cited_ids = [c.get("evidence_id") for c in citations if isinstance(c, dict)]
    unsupported = [c for c in cited_ids if evidence_ids and c not in evidence_ids]
    raw = reasoning.get("raw_answer", "") or ""
    status = reasoning.get("provider_status")
    return {
        "nonempty_observations": bool(observations) if evidence_count else None,
        "causes_separated": bool(causes) or None,
        "nonempty_checks": bool(checks) or None,
        "missing_info_preserved": bool(missing) or None,
        "unsupported_evidence_ids": unsupported,
        "unsupported_count": len(unsupported),
        "raw_answer_nonempty": bool(raw.strip()),
        "provider_status": status,
    }


def causal_overreach_scan(texts: Iterable[str]) -> dict[str, Any]:
    """Heuristic scan for excessive causal certainty (warning only)."""

    hits: list[str] = []
    for text in texts:
        lowered = (text or "").lower()
        for pattern in _CAUSAL_CERTAINTY_PATTERNS:
            if pattern in lowered:
                hits.append(pattern)
    return {"patterns_hit": sorted(set(hits)), "warning": bool(hits)}


def safety_scan(texts: Iterable[str]) -> dict[str, Any]:
    """Heuristic scan for operational-bypass recommendations (warning only)."""

    hits: list[str] = []
    for text in texts:
        lowered = (text or "").lower()
        for pattern in _UNSAFE_BYPASS_PATTERNS:
            if pattern in lowered:
                hits.append(pattern)
    return {"patterns_hit": sorted(set(hits)), "warning": bool(hits)}


def provider_failure_checks(
    reasoning_status: str | None,
    review_action: str | None,
    observations: list,
    causes: list,
    checks: list,
    citations: list,
) -> dict[str, Any]:
    """Fail-closed expectations for provider-unavailable outcomes."""

    return {
        "reasoning_unavailable": reasoning_status == "UNAVAILABLE",
        "review_human": review_action == "HUMAN_REVIEW",
        "never_pass": review_action != "PASS",
        "no_fabricated_observations": len(observations) == 0,
        "no_fabricated_causes": len(causes) == 0,
        "no_fabricated_checks": len(checks) == 0,
        "no_citations": len(citations) == 0,
    }


def latency_summary(latencies_ms: list[float]) -> dict[str, Any]:
    """Aggregate harness-observable latencies (never NaN)."""

    if not latencies_ms:
        return {"count": 0, "mean_ms": None, "p50_ms": None, "p95_ms": None, "max_ms": None}
    ordered = sorted(latencies_ms)
    p95_index = max(0, min(len(ordered) - 1, int(0.95 * len(ordered))))
    return {
        "count": len(ordered),
        "mean_ms": statistics.fmean(ordered),
        "p50_ms": statistics.median(ordered),
        "p95_ms": ordered[p95_index],
        "max_ms": ordered[-1],
    }
