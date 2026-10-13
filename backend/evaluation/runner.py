"""Offline/live evaluation runner with a ground-truth firewall.

Firewall rule: the production workflow only ever receives ``query``,
structured scope (machine/product/batch/time), and ``document_context``.
Hidden evaluator fields (``expected_hidden_cause``, ``notes``,
``expected_record_ids``, ``expected_document_ids``) are asserted absent
from the serialized ``QueryRequest`` BEFORE the workflow runs and are only
compared AFTER the result exists.
"""

from __future__ import annotations

import hashlib
import platform
import sys
import time
from typing import Any

from evaluation.cases import get_suite
from evaluation.metrics import (
    bundle_fingerprint,
    causal_overreach_scan,
    citation_metrics,
    determinism_equal,
    document_hit_metrics,
    latency_summary,
    provenance_metrics,
    provider_failure_checks,
    reasoning_checks,
    retrieval_metrics,
    routing_metrics,
    safety_scan,
)

_FAILURE = "unexpected_exception"


def build_query_request(case, index: int = 0):
    """Build a production ``QueryRequest`` from NON-HIDDEN case fields only."""

    from app.contracts.query import QueryRequest

    request = QueryRequest(
        query_id=f"EVAL-{case.case_id}-{index}",
        query=case.query,
        machine_id=case.machine_id,
        product_id=case.product_id,
        batch_id=case.batch_id,
        time_start=case.time_start,
        time_end=case.time_end,
        user_context=dict(case.document_context or {}),
    )
    assert_firewall(case, request)
    return request


def assert_firewall(case, request) -> None:
    """Prove hidden evaluator strings never entered production inputs."""

    dumped = request.model_dump_json().lower()
    guarded = [case.expected_hidden_cause or "", case.notes or ""]
    guarded.extend(case.expected_record_ids)
    guarded.extend(case.expected_document_ids)
    # NOTE: expected_keywords are intentionally NOT guarded: legitimate
    # query text may contain the same ordinary words ("spindle", ...).
    for secret in guarded:
        if secret and len(secret.strip()) >= 4 and secret.lower() in dumped:
            raise AssertionError(
                f"ground-truth leak for case {case.case_id}: hidden value present in QueryRequest"
            )


def build_orchestrator(mode: str):
    """Compose the production orchestrator for an evaluation mode."""

    from app.core.config import Settings
    from app.decision.jev import build_jev_decision_engine
    from app.orchestration import build_manufacturaiq_orchestrator
    from app.reasoning import build_gemini_reasoner

    if mode == "offline":
        settings = Settings(typesafe_api_key=None, gemini_api_key=None)
        return build_manufacturaiq_orchestrator(
            decision_engine=build_jev_decision_engine(settings),
            reasoner=build_gemini_reasoner(settings),
        ), {"typesafe_available": False, "gemini_available": False}
    if mode in ("gemini-live", "full-provider"):
        settings = Settings()
        return build_manufacturaiq_orchestrator(
            decision_engine=build_jev_decision_engine(settings),
            reasoner=build_gemini_reasoner(settings),
        ), {
            "typesafe_available": bool(settings.typesafe_api_key),
            "gemini_available": bool(settings.gemini_api_key),
            "gemini_model": settings.gemini_model,
            "jev_enabled": settings.jev_enabled,
        }
    raise ValueError(f"unknown evaluation mode: {mode!r}")


def environment_metadata(mode: str, provider_info: dict[str, Any]) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "python": platform.python_version(),
        "mode": mode,
        "typesafe_available": provider_info.get("typesafe_available", False),
        "gemini_available": provider_info.get("gemini_available", False),
    }
    for key in ("gemini_model", "jev_enabled"):
        if key in provider_info:
            meta[key] = provider_info[key]
    try:
        from pathlib import Path

        manifest = Path(__file__).resolve().parents[2] / "datasets" / "manifests" / "documents.json"
        if manifest.exists():
            meta["dataset_manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()[:16]
    except OSError:
        pass
    try:
        import langgraph  # type: ignore

        meta["langgraph_version"] = getattr(langgraph, "__version__", "unknown")
    except ImportError:
        pass
    meta["python_implementation"] = platform.python_implementation()
    meta["interpreter"] = sys.version.split()[0]
    return meta


def _serialize(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, (list, tuple)):
        return [_serialize(v) for v in value]
    return value


async def evaluate_case(orchestrator, case, index: int = 0) -> dict[str, Any]:
    """Run one case through production, then compare (evaluator-only)."""

    from evaluation.models import CaseResult, MetricResult

    request = build_query_request(case, index)
    started = time.perf_counter()
    failures: list[str] = []
    warnings: list[str] = []
    result: dict[str, Any] = {}
    try:
        result = await orchestrator.run(request) or {}
    except Exception as exc:  # harness boundary, not production behavior
        failures.append(_FAILURE)
        warnings.append(f"{type(exc).__name__}: {exc}")
    latency_ms = (time.perf_counter() - started) * 1000.0

    routing = _serialize(result.get("routing_decision")) or {}
    agents = [_serialize(a) or {} for a in (result.get("agent_results") or [])]
    bundle = _serialize(result.get("evidence_bundle")) or {}
    reasoning = _serialize(result.get("reasoning_result")) or {}
    review = _serialize(result.get("review_decision")) or {}
    result_query_id = result.get("query_id")

    selected = routing.get("selected_agents", []) or []
    evidence_items = bundle.get("evidence", []) or []
    evidence_ids = [e.get("evidence_id") for e in evidence_items]
    doc_ids = [(e.get("provenance") or {}).get("document_id") for e in evidence_items]
    citations = reasoning.get("citations", []) or []
    cited_ids = [c.get("evidence_id") for c in citations if isinstance(c, dict)]

    metrics: list[MetricResult] = []
    rm = routing_metrics(case.expected_agents, selected)
    metrics.append(MetricResult(name="routing_exact_match", value=1.0 if rm["exact_match"] else 0.0,
                                passed=rm["exact_match"], detail=rm))
    if not rm["exact_match"] and case.expected_agents:
        failures.append("routing_mismatch")
    if bool(routing.get("needs_clarification", False)) != case.expected_clarification:
        failures.append("routing_mismatch")
        warnings.append("clarification expectation unmet")
    metrics.append(MetricResult(name="clarification_correct",
                                value=1.0 if not warnings or "clarification" not in warnings[-1] else 0.0,
                                passed=bool(routing.get("needs_clarification", False)) == case.expected_clarification))

    if case.expected_source_types:
        actual_types = sorted({(e.get("source_type") or "").upper() for e in evidence_items})
        missing = [t for t in case.expected_source_types if t.upper() not in actual_types]
        metrics.append(MetricResult(name="expected_source_types_present",
                                    value=1.0 if not missing else 0.0, passed=not missing,
                                    detail={"expected": case.expected_source_types, "actual": actual_types}))
        if missing:
            failures.append("missing_expected_evidence")
    if case.expected_document_ids:
        dh = document_hit_metrics(doc_ids, case.expected_document_ids)
        metrics.append(MetricResult(name="document_hit", value=1.0 if dh["document_hit"] else 0.0,
                                    passed=bool(dh["document_hit"]), detail=dh))
        if not dh["document_hit"]:
            failures.append("missing_expected_evidence")
        ret = retrieval_metrics(evidence_ids, [], (1, 3, 5))
        _ = ret
    if case.expected_record_ids:
        haystack = " ".join(
            str((e.get("provenance") or {}).get(k))
            for e in evidence_items for k in ("record_id", "source_id", "raw_record_id")
        )
        found = [r for r in case.expected_record_ids if r in haystack]
        metrics.append(MetricResult(name="record_identity_recall",
                                    value=(len(found) / len(case.expected_record_ids)) if case.expected_record_ids else None,
                                    passed=len(found) == len(case.expected_record_ids),
                                    detail={"found": found, "expected": case.expected_record_ids}))
        if len(found) != len(case.expected_record_ids):
            failures.append("missing_expected_evidence")

    prov = provenance_metrics(evidence_items)
    metrics.append(MetricResult(name="provenance_completeness", value=prov["completeness_rate"],
                                passed=not prov["issues"], detail=prov))
    if prov["issues"]:
        failures.append("invalid_provenance")

    reasoning["_evidence_ids"] = evidence_ids
    rc = reasoning_checks(reasoning, len(evidence_items))
    metrics.append(MetricResult(name="reasoning_grounded", value=1.0 if rc["unsupported_count"] == 0 else 0.0,
                                passed=rc["unsupported_count"] == 0, detail=rc))
    if rc["unsupported_count"]:
        failures.append("unsupported_reasoning_reference")
    cm = citation_metrics(evidence_ids, cited_ids)
    metrics.append(MetricResult(name="citation_validity", value=cm["validity_rate"],
                                passed=cm["invalid_citations"] == 0, detail=cm))
    if cm["invalid_citations"]:
        failures.append("invalid_citation")

    cause_texts = (reasoning.get("possible_causes", []) or []) + [reasoning.get("raw_answer", "") or ""]
    overreach = causal_overreach_scan(cause_texts)
    metrics.append(MetricResult(name="causal_restraint", value=0.0 if overreach["warning"] else 1.0,
                                passed=not overreach["warning"], detail=overreach))
    if overreach["warning"]:
        failures.append("causal_overreach_warning")
        warnings.append(f"causal-certainty patterns: {overreach['patterns_hit']}")
    if case.safety_expectation:
        scan = safety_scan(cause_texts + (reasoning.get("recommended_checks", []) or []))
        metrics.append(MetricResult(name="safety_no_bypass", value=0.0 if scan["warning"] else 1.0,
                                    passed=not scan["warning"], detail=scan))
        if scan["warning"]:
            failures.append("unsafe_recommendation_warning")
    if (reasoning.get("provider_status") in ("UNAVAILABLE", "ERROR", None) and not evidence_items) or \
            reasoning.get("provider_status") == "UNAVAILABLE":
        pf = provider_failure_checks(
            reasoning.get("provider_status"), review.get("action"),
            reasoning.get("observations", []) or [], reasoning.get("possible_causes", []) or [],
            reasoning.get("recommended_checks", []) or [], citations)
        metrics.append(MetricResult(name="provider_fail_closed", value=1.0 if all(pf.values()) else 0.0,
                                    passed=all(pf.values()), detail=pf))
        if not all(pf.values()):
            failures.append("provider_failure")

    review_action = review.get("action")
    if case.expected_review_action and review_action != case.expected_review_action:
        failures.append("provider_failure")
        warnings.append(f"expected review {case.expected_review_action}, got {review_action}")

    # Agent execution / fusion / scope / retrieval details (harness-observed).
    executed = [str(a.get("agent_name")) for a in agents if a.get("agent_name")]
    agent_evidence_counts = {str(a.get("agent_name")): len(a.get("evidence", []) or []) for a in agents}
    agent_warnings = sum(len(a.get("warnings", []) or []) for a in agents)
    agent_errors = sum(len(a.get("errors", []) or []) for a in agents)
    agent_qids_ok = all(a.get("query_id", result_query_id) == request.query_id for a in agents)
    exec_ok = sorted(executed) == sorted(str(a) for a in selected)
    metrics.append(MetricResult(name="agent_execution_correct", value=1.0 if exec_ok else 0.0,
                                passed=exec_ok,
                                detail={"selected": sorted(str(a) for a in selected),
                                        "executed": sorted(executed),
                                        "evidence_counts": agent_evidence_counts,
                                        "warnings": agent_warnings, "errors": agent_errors,
                                        "query_ids_consistent": agent_qids_ok,
                                        "result_query_id_match": result_query_id == request.query_id}))
    if not exec_ok:
        failures.append("scope_mismatch")
    metrics.append(MetricResult(name="agent_evidence_total", value=float(sum(agent_evidence_counts.values())),
                                detail={"warnings": agent_warnings, "errors": agent_errors}))
    if agent_errors:
        failures.append("unexpected_exception")

    bundle_ids = [e.get("evidence_id") for e in evidence_items]
    metrics.append(MetricResult(name="fusion_duplicates_absent",
                                value=1.0 if len(set(bundle_ids)) == len(bundle_ids) else 0.0,
                                passed=len(set(bundle_ids)) == len(bundle_ids),
                                detail={"conflict_count": len(bundle.get("conflicts", []) or []),
                                        "bundle_query_id_match": bundle.get("query_id") == request.query_id}))
    if len(set(bundle_ids)) != len(bundle_ids):
        failures.append("scope_mismatch")

    scope_fields = {"machine_id": case.machine_id, "product_id": case.product_id, "batch_id": case.batch_id}
    active_scope = {k: v for k, v in scope_fields.items() if v}
    if active_scope:
        matched = [e for e in evidence_items
                   if any(e.get(k) == v for k, v in active_scope.items())]
        scope_ok = len(matched) > 0 if evidence_items else False
        metrics.append(MetricResult(name="scope_correct", value=1.0 if scope_ok else 0.0,
                                    passed=scope_ok,
                                    detail={"scope": active_scope, "matched_count": len(matched)}))
        if not scope_ok and evidence_items:
            failures.append("scope_mismatch")

    if case.time_start or case.time_end:
        dated = [e.get("observed_at") for e in evidence_items if e.get("observed_at")]
        inside = [d for d in dated if (not case.time_start or d >= case.time_start)
                  and (not case.time_end or d <= case.time_end)]
        metrics.append(MetricResult(
            name="time_window_coverage",
            value=(len(inside) / len(dated)) if dated else None,
            detail={"dated_count": len(dated), "inside_count": len(inside)}))

    if case.expected_document_ids:
        ranked_docs = [(e.get("provenance") or {}).get("document_id") for e in evidence_items]
        ranked_docs = [d for d in ranked_docs if d]
        ret = retrieval_metrics(ranked_docs, case.expected_document_ids)
        metrics.append(MetricResult(name="retrieval_hit_at_1", value=1.0 if ret["hit_at_1"] else 0.0,
                                    passed=bool(ret["hit_at_1"]), detail=ret))
        metrics.append(MetricResult(name="retrieval_mrr", value=ret["mrr"], detail=ret))

    hidden_alignment = None
    if case.expected_hidden_cause:
        hidden_alignment = _weak_cause_alignment(
            case.expected_hidden_cause,
            (reasoning.get("possible_causes", []) or []) + [reasoning.get("raw_answer", "") or ""],
        )

    case_result = CaseResult(
        case_id=case.case_id,
        category=case.category,
        mode="",
        query=case.query,
        machine_id=case.machine_id,
        product_id=case.product_id,
        batch_id=case.batch_id,
        routing_agents=[str(a) for a in selected],
        routing_provider_status=str(routing.get("provider_status")) if routing.get("provider_status") else None,
        needs_clarification=bool(routing.get("needs_clarification", False)),
        agents_executed=[str((a.get("agent_name"))) for a in agents],
        evidence_ids=[str(i) for i in evidence_ids],
        evidence_source_types=sorted({str(e.get("source_type")) for e in evidence_items if e.get("source_type")}),
        citation_ids=[str(c) for c in cited_ids],
        reasoning_provider_status=str(reasoning.get("provider_status")) if reasoning.get("provider_status") else None,
        review_action=str(review_action) if review_action else None,
        metrics=metrics,
        failures=sorted(set(failures)),
        latency_ms=round(latency_ms, 3),
        hidden_cause_alignment=hidden_alignment,
        warnings=warnings,
    )
    human_row = {
        "case_id": case.case_id,
        "query": case.query,
        "evidence_summary": " | ".join(f"{e.get('evidence_id')}: {(e.get('title') or '')[:80]}" for e in evidence_items[:8]),
        "observations": " | ".join(reasoning.get("observations", []) or [])[:2000],
        "possible_causes": " | ".join(reasoning.get("possible_causes", []) or [])[:2000],
        "recommended_checks": " | ".join(reasoning.get("recommended_checks", []) or [])[:2000],
        "raw_answer": (reasoning.get("raw_answer", "") or "")[:4000],
        "hidden_expected_cause__evaluator_only": case.expected_hidden_cause or "",
        "groundedness_1_5": "",
        "usefulness_1_5": "",
        "causal_restraint_1_5": "",
        "safety_1_5": "",
        "citation_usefulness_1_5": "",
        "reviewer_notes": "",
    }
    return {"case": case_result, "human_row": human_row,
            "fingerprint": {"routing": sorted(str(a) for a in selected),
                            "bundle": bundle_fingerprint(bundle),
                            "review": str(review_action)}}


def _weak_cause_alignment(hidden_cause: str, texts: list[str]) -> str:
    """Weak keyword-overlap diagnostic (NOT a semantic correctness claim)."""

    tokens = [t for t in hidden_cause.lower().split() if len(t) > 3]
    if not tokens:
        return "no_tokens"
    joined = " ".join((t or "").lower() for t in texts)
    hits = [t for t in tokens if t in joined]
    if len(hits) == len(tokens):
        return "keyword_alignment"
    if hits:
        return f"partial_keyword_alignment:{','.join(hits)}"
    return "no_keyword_alignment:human-review-required"


async def evaluate_suite(suite: str, mode: str, case_filter=None, repeat: int = 1) -> dict[str, Any]:
    """Evaluate a whole suite; returns run record + case payloads."""

    from datetime import datetime, timezone

    from evaluation.models import EvaluationRun

    cases = get_suite(suite)
    if case_filter is not None:
        cases = [c for c in cases if case_filter(c)]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + f"_{mode}"
    started = datetime.now(timezone.utc).isoformat()
    orchestrator, provider_info = build_orchestrator(mode)
    payloads: list[dict[str, Any]] = []
    for index, case in enumerate(cases):
        for rep in range(max(1, repeat)):
            payload = await evaluate_case(orchestrator, case, index * 100 + rep)
            payload["case"].mode = mode
            payloads.append(payload)
    run = EvaluationRun(
        run_id=run_id,
        mode=mode,
        suite=suite,
        started_at=started,
        finished_at=datetime.now(timezone.utc).isoformat(),
        case_count=len(payloads),
        environment=environment_metadata(mode, provider_info),
    )
    return {"run": run, "payloads": payloads}


def summarize(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate suite-level metrics across case payloads."""

    metric_values: dict[str, list[float]] = {}
    failure_counts: dict[str, int] = {}
    latencies: list[float] = []
    for payload in payloads:
        case = payload["case"]
        if case.latency_ms is not None:
            latencies.append(case.latency_ms)
        for failure in case.failures:
            failure_counts[failure] = failure_counts.get(failure, 0) + 1
        for metric in case.metrics:
            if metric.value is not None:
                metric_values.setdefault(metric.name, []).append(metric.value)
    aggregate: dict[str, Any] = {}
    for name, values in metric_values.items():
        aggregate[name] = {
            "mean": sum(values) / len(values),
            "n": len(values),
        }
    return {
        "case_count": len(payloads),
        "cases_with_failures": sum(1 for p in payloads if p["case"].failures),
        "failure_counts": failure_counts,
        "metric_means": aggregate,
        "latency": latency_summary(latencies),
    }


def check_determinism(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare repeated runs of the same case for fingerprint equality."""

    from collections import defaultdict

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for payload in payloads:
        groups[payload["case"].case_id].append(payload["fingerprint"])
    mismatches: list[str] = []
    for case_id, prints in groups.items():
        if len(prints) > 1 and not all(determinism_equal(prints[0], p) for p in prints[1:]):
            mismatches.append(case_id)
    return {"repeated_cases": sum(1 for v in groups.values() if len(v) > 1),
            "mismatched_cases": mismatches}
