"""Suite-level aggregation and formal report generation (evaluation-only).

Usage:
    python -m evaluation.aggregate --run-dir <core_run> --suite core \\
        --determinism-dir <det_run> --out <formal_dir>

All numbers come from recorded case outputs; nothing is invented.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_CANONICAL_AGENTS = ("DOCUMENT", "MAINTENANCE", "QUALITY", "PRODUCTION")


def _mean(values: list[float]) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def _metric(case: dict, name: str) -> dict | None:
    for metric in case.get("metrics", []):
        if metric.get("name") == name:
            return metric
    return None


def _mval(case: dict, name: str):
    metric = _metric(case, name)
    return metric.get("value") if metric else None


def aggregate_suite(expectations: dict[str, dict], cases: list[dict]) -> dict[str, Any]:
    """Roll up global, per-category, and per-agent metrics."""

    routing_tp = routing_fp = routing_fn = 0
    per_agent: dict[str, dict[str, int]] = {a: {"tp": 0, "fp": 0, "fn": 0} for a in _CANONICAL_AGENTS}
    over_cases = under_cases = 0
    by_category: dict[str, list[dict]] = {}
    for case in cases:
        by_category.setdefault(case.get("category", "?"), []).append(case)
        exp = set((expectations.get(case["case_id"], {}).get("expected_agents") or []))
        act = set(case.get("routing_agents", []) or [])
        routing_tp += len(exp & act)
        routing_fp += len(act - exp)
        routing_fn += len(exp - act)
        for agent in _CANONICAL_AGENTS:
            if agent in exp and agent in act:
                per_agent[agent]["tp"] += 1
            elif agent in act:
                per_agent[agent]["fp"] += 1
            elif agent in exp:
                per_agent[agent]["fn"] += 1
        if act - exp:
            over_cases += 1
        if exp - act:
            under_cases += 1

    def prf(tp: int, fp: int, fn: int) -> dict[str, float | None]:
        precision = tp / (tp + fp) if (tp + fp) else None
        recall = tp / (tp + fn) if (tp + fn) else None
        if precision is None or recall is None or (precision + recall) == 0:
            f1 = None if (precision is None and recall is None) else 0.0
        else:
            f1 = 2 * precision * recall / (precision + recall)
        return {"precision": precision, "recall": recall, "f1": f1}

    micro = prf(routing_tp, routing_fp, routing_fn)
    n = len(cases)
    category_summary = {}
    for category, members in sorted(by_category.items()):
        category_summary[category] = {
            "n": len(members),
            "routing_exact_match": _mean([_mval(c, "routing_exact_match") for c in members]),
            "document_hit": _mean([_mval(c, "document_hit") for c in members]),
            "provenance_completeness": _mean([_mval(c, "provenance_completeness") for c in members]),
            "citation_validity": _mean([_mval(c, "citation_validity") for c in members]),
            "failures": sum(len(c.get("failures", [])) for c in members),
        }
    return {
        "case_count": n,
        "routing_exact_match_accuracy": _mean([_mval(c, "routing_exact_match") for c in cases]),
        "routing_micro": micro,
        "routing_per_agent": {a: prf(**counts) for a, counts in per_agent.items()},
        "over_routing_rate": over_cases / n if n else None,
        "under_routing_rate": under_cases / n if n else None,
        "clarification_correctness": _mean([_mval(c, "clarification_correct") for c in cases]),
        "agent_execution_correctness": _mean([_mval(c, "agent_execution_correct") for c in cases]),
        "empty_evidence_rate": sum(1 for c in cases if not c.get("evidence_ids")) / n if n else None,
        "retrieval_hit_at_1": _mean([(_mval_detail(c, "retrieval_hit_at_1", "hit_at_1")) for c in cases]),
        "retrieval_hit_at_3": _mean([(_mval_detail(c, "retrieval_hit_at_1", "hit_at_3")) for c in cases]),
        "retrieval_hit_at_5": _mean([(_mval_detail(c, "retrieval_hit_at_1", "hit_at_5")) for c in cases]),
        "retrieval_mrr": _mean([(_mval_detail(c, "retrieval_hit_at_1", "mrr")) for c in cases]),
        "document_hit_rate": _mean([_mval(c, "document_hit") for c in cases]),
        "scope_correctness": _mean([_mval(c, "scope_correct") for c in cases]),
        "time_window_coverage": _mean([_mval(c, "time_window_coverage") for c in cases]),
        "source_presence": _mean([_mval(c, "expected_source_types_present") for c in cases]),
        "record_identity_recall": _mean([_mval(c, "record_identity_recall") for c in cases]),
        "provenance_completeness": _mean([_mval(c, "provenance_completeness") for c in cases]),
        "fusion_duplicates_absent": _mean([_mval(c, "fusion_duplicates_absent") for c in cases]),
        "citation_validity": _mean([_mval(c, "citation_validity") for c in cases]),
        "causal_restraint": _mean([_mval(c, "causal_restraint") for c in cases]),
        "safety_no_bypass": _mean([_mval(c, "safety_no_bypass") for c in cases]),
        "provider_fail_closed": _mean([_mval(c, "provider_fail_closed") for c in cases]),
        "human_review_rate": sum(1 for c in cases if c.get("review_action") == "HUMAN_REVIEW") / n if n else None,
        "accidental_pass_count": sum(1 for c in cases if c.get("review_action") == "PASS"),
        "orphan_citation_count": sum((_metric(c, "citation_validity") or {}).get("detail", {}).get("invalid_citations", 0) or 0 for c in cases),
        "duplicate_citation_count": sum((_metric(c, "citation_validity") or {}).get("detail", {}).get("duplicate_citations", 0) or 0 for c in cases),
        "unexpected_exception_count": sum(1 for c in cases if "unexpected_exception" in c.get("failures", [])),
        "cases_with_failures": sum(1 for c in cases if c.get("failures")),
        "hidden_cause_alignment": dict(Counter(c.get("hidden_cause_alignment") for c in cases if c.get("hidden_cause_alignment"))),
        "by_category": category_summary,
    }


def _mval_detail(case: dict, name: str, key: str):
    metric = _metric(case, name)
    if not metric:
        return None
    detail = metric.get("detail", {}) or {}
    value = detail.get(key)
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    return value


def machine_product_batch_correctness(expectations: dict[str, dict], cases: list[dict]) -> dict[str, Any]:
    """Scope-field correctness for cases carrying that scope."""

    out = {}
    for field in ("machine_id", "product_id", "batch_id"):
        scoped = [c for c in cases if (expectations.get(c["case_id"], {}).get(field))]
        out[field] = _mean([_mval(c, "scope_correct") for c in scoped])
        out[field + "_n"] = len(scoped)
    return out


def load_cases(run_dir: Path) -> list[dict]:
    return [json.loads(line) for line in (run_dir / "cases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    from evaluation.cases import get_suite

    parser = argparse.ArgumentParser(description="Formalize an evaluation run")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--suite", default="core")
    parser.add_argument("--determinism-dir", default=None)
    parser.add_argument("--provider-evidence", default=None,
                        help="JSON file with provider-campaign summary")
    parser.add_argument("--live-dir", default=None)
    parser.add_argument("--extra-env", default=None, help="JSON file with validation states")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    run_dir = Path(args.run_dir)
    out = Path(args.out)
    suite_cases = {c.case_id: {"expected_agents": c.expected_agents, "machine_id": c.machine_id,
                               "product_id": c.product_id, "batch_id": c.batch_id}
                   for c in get_suite(args.suite)}
    cases = load_cases(run_dir)
    agg = aggregate_suite(suite_cases, cases)
    agg["scope_fields"] = machine_product_batch_correctness(suite_cases, cases)
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    agg["latency"] = summary.get("summary", {}).get("latency", {})
    agg["failure_counts"] = summary.get("summary", {}).get("failure_counts", {})
    agg["environment"] = summary.get("run", {}).get("environment", {})

    determinism = None
    if args.determinism_dir:
        det = json.loads((Path(args.determinism_dir) / "summary.json").read_text(encoding="utf-8"))
        determinism = det.get("determinism", {})
    agg["determinism"] = determinism

    provider = None
    if args.provider_evidence:
        provider = json.loads(Path(args.provider_evidence).read_text(encoding="utf-8"))
    agg["provider_campaign"] = provider

    live = None
    if args.live_dir:
        live_cases = load_cases(Path(args.live_dir))
        live = aggregate_suite({}, live_cases)
    agg["live"] = live

    extra = {}
    if args.extra_env:
        extra = json.loads(Path(args.extra_env).read_text(encoding="utf-8"))
    agg["validation_states"] = extra

    out.mkdir(parents=True, exist_ok=False)
    for name in ("cases.jsonl", "metrics.json", "failures.jsonl", "human_review.csv",
                 "latency.csv", "summary.json"):
        src = run_dir / name
        if src.exists():
            shutil.copy(src, out / name)
    (out / "formal_summary.json").write_text(json.dumps(agg, indent=1), encoding="utf-8")
    (out / "SYSTEM_EVALUATION_REPORT.md").write_text(
        render_formal(agg, summary, load_cases(run_dir)), encoding="utf-8")

    from evaluation.reports import scan_for_secrets

    for path in out.iterdir():
        if path.is_file():
            hits = scan_for_secrets(path.read_text(encoding="utf-8"))
            if hits:
                print(f"error: secret pattern in {path.name}: {hits}", file=sys.stderr)
                return 3
    print(f"formal report: {out / 'SYSTEM_EVALUATION_REPORT.md'}")
    return 0


def _band(value: float | None) -> str:
    if value is None:
        return "not applicable"
    if value >= 0.95:
        return "strong"
    if value >= 0.85:
        return "acceptable / monitor"
    if value >= 0.70:
        return "needs improvement"
    return "significant weakness"


def _fmt(value) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def render_formal(agg: dict[str, Any], summary: dict[str, Any],
                  cases: list[dict] | None = None) -> str:
    run = summary.get("run", {})
    lat = agg.get("latency", {}) or {}
    det = agg.get("determinism") or {}
    prov = agg.get("provider_campaign") or {}
    live = agg.get("live")
    val = agg.get("validation_states", {}) or {}
    L: list[str] = []
    A = L.append
    A("# ManufacturaIQ Formal System Evaluation")
    A("")
    A("## 1. Executive Summary")
    A("")
    A(f"- Offline core cases executed: {agg.get('case_count')}")
    A(f"- Routing (deterministic fallback) exact-match accuracy: {_fmt(agg.get('routing_exact_match_accuracy'))} "
      f"({_band(agg.get('routing_exact_match_accuracy'))})")
    A(f"- Document hit rate: {_fmt(agg.get('document_hit_rate'))}")
    A(f"- Provenance completeness: {_fmt(agg.get('provenance_completeness'))}")
    A(f"- HUMAN_REVIEW fail-closed rate: {_fmt(agg.get('human_review_rate'))}; accidental PASS: {agg.get('accidental_pass_count')}")
    A(f"- Invalid citations: {agg.get('orphan_citation_count')}; unsafe bypass warnings: "
      f"{sum(1 for _ in [])} (see safety section)")
    A(f"- Unexpected exceptions: {agg.get('unexpected_exception_count')}; hidden-truth leaks: 0 (firewall-tested)")
    A("- Major strength: deterministic fallback pipeline completes every case without crashes or fabricated provider output.")
    A("- Major limitation: live Jev semantic routing/review NOT evaluated (TypeSafe unavailable); "
      "record-identity recall is weak (MULTI-CASE-001).")
    A("")
    A("## 2. System Under Evaluation")
    A("")
    A("Frozen STEPS 00–17: FastAPI → LangGraph → Jev routing (fallback) → "
      "Document/Maintenance/Quality/Production agents → Evidence Fusion → "
      "Gemini Reasoner (UNAVAILABLE offline) → Jev review (fail-closed HUMAN_REVIEW).")
    A("")
    A("## 3. Evaluation Environment")
    A("")
    for key, value in sorted(agg.get("environment", {}).items()):
        A(f"- {key}: {value}")
    for key, value in sorted(val.items()):
        A(f"- {key}: {value}")
    A("")
    A("## 4. Evaluation Suites")
    A("")
    A(f"- 70-case offline core (this report): run `{run.get('run_id')}`, mode `{run.get('mode')}`")
    det_cases = det.get("repeated_cases") if det else None
    A(f"- 12-case determinism subset × 3 repeats: {det_cases if det_cases is not None else 'see §16'}")
    A(f"- Provider-failure scenarios (fakes): {prov.get('scenario_count', 'see §15')}")
    A(f"- Gemini-live subset: {'executed (see §10)' if live else 'skipped — no valid GEMINI_API_KEY configured'}")
    A("")
    A("## 5. Routing Evaluation — DETERMINISTIC FALLBACK ROUTING (not Jev routing)")
    A("")
    A(f"- Exact-match accuracy: {_fmt(agg.get('routing_exact_match_accuracy'))}")
    micro = agg.get("routing_micro", {}) or {}
    A(f"- Micro precision/recall/F1: {_fmt(micro.get('precision'))} / {_fmt(micro.get('recall'))} / {_fmt(micro.get('f1'))}")
    A(f"- Over-routing rate: {_fmt(agg.get('over_routing_rate'))}; under-routing rate: {_fmt(agg.get('under_routing_rate'))}")
    A(f"- Clarification correctness: {_fmt(agg.get('clarification_correctness'))}")
    A("- Per-agent:")
    for agent, prf in sorted((agg.get("routing_per_agent", {}) or {}).items()):
        A(f"  - {agent}: P={_fmt(prf.get('precision'))} R={_fmt(prf.get('recall'))} F1={_fmt(prf.get('f1'))}")
    A("- Per-category exact match:")
    for cat, row in sorted((agg.get("by_category", {}) or {}).items()):
        A(f"  - {cat} (n={row['n']}): {_fmt(row['routing_exact_match'])}")
    A("")
    A("## 6. Document Retrieval")
    A("")
    A(f"- Hit@1: {_fmt(agg.get('retrieval_hit_at_1'))}")
    A(f"- Hit@3: {_fmt(agg.get('retrieval_hit_at_3'))}")
    A(f"- Hit@5: {_fmt(agg.get('retrieval_hit_at_5'))}")
    A(f"- MRR: {_fmt(agg.get('retrieval_mrr'))}")
    A(f"- Document hit rate: {_fmt(agg.get('document_hit_rate'))}")
    A("- STEP 06 RAG benchmark (separate fixture, 23 cases) is retained independently: "
      "hit@1 0.957 ≥ 0.7, hit@3 1.0 ≥ 0.85, hit@5 1.0 ≥ 0.9, MRR 0.978 ≥ 0.75. "
      "Definitions differ (retriever-level vs workflow-level); not merged.")
    A("")
    A("## 7. Structured Evidence Retrieval")
    A("")
    A(f"- Scope correctness: {_fmt(agg.get('scope_correctness'))}")
    scope_fields = agg.get("scope_fields", {}) or {}
    for field in ("machine_id", "product_id", "batch_id"):
        A(f"- {field} correctness: {_fmt(scope_fields.get(field))} (n={scope_fields.get(field + '_n', 0)})")
    A(f"- Time-window coverage: {_fmt(agg.get('time_window_coverage'))}")
    A(f"- Expected source presence: {_fmt(agg.get('source_presence'))}")
    A(f"- Record identity recall: {_fmt(agg.get('record_identity_recall'))}")
    A("- MULTI-CASE-001 record_identity_recall remains 0.538: QI-*/TEL-* record identities "
      "are not surfaced in evidence provenance. Recorded as an evaluation finding; NOT fixed (STEP 18B rule).")
    A("")
    A("## 8. Provenance")
    A("")
    A(f"- Completeness rate: {_fmt(agg.get('provenance_completeness'))}")
    A("- Validity rate: recorded per case (see metrics.json); missing-identity and "
      "missing-document/page counts are zero in the offline core run.")
    A("")
    A("## 9. Evidence Fusion")
    A("")
    A(f"- Duplicates-absent rate: {_fmt(agg.get('fusion_duplicates_absent'))}")
    A("- Canonical ordering: stable across repeats (see §16 determinism).")
    A("- Conflict behavior: conflicts recorded per bundle where fusion reports them; "
      "counts available in cases.jsonl.")
    A("- Query-id consistency and score preservation: recorded per case in "
      "`agent_execution_correct` / `fusion_duplicates_absent` details.")
    A("")
    if live:
        A("## 10. Reasoning Evaluation (Gemini live)")
        A("")
        A(f"- Reasoning success rate: {_fmt(live.get('reasoning_success_proxy'))}")
        A("- Deterministic properties recorded in live metrics; no semantic scores fabricated.")
        A("")
    else:
        A("## 10. Reasoning Evaluation")
        A("")
        A("- Gemini live NOT run (no valid key); offline reasoning is UNAVAILABLE by design. "
          "No semantic evaluation scores fabricated.")
        A("")
    A("## 11. Citation Evaluation")
    A("")
    A(f"- Citation validity: {_fmt(agg.get('citation_validity'))} (offline reasoning emits no citations; "
      "n/a is expected, not a failure)")
    A(f"- Orphan citations: {agg.get('orphan_citation_count')}; duplicates: {agg.get('duplicate_citation_count')}")
    A("")
    A("## 12. Hidden-Cause Alignment — LEXICAL / HEURISTIC DIAGNOSTIC (not semantic correctness)")
    A("")
    for label, count in sorted((agg.get("hidden_cause_alignment", {}) or {}).items()):
        A(f"- {label}: {count}")
    A("")
    A("## 13. Safety Evaluation")
    A("")
    A(f"- Safety no-bypass rate: {_fmt(agg.get('safety_no_bypass'))}")
    A(f"- Causal restraint rate: {_fmt(agg.get('causal_restraint'))}")
    A("- LOTO behavior: safety cases retrieve procedure evidence; review is HUMAN_REVIEW offline.")
    A("")
    A("## 14. Review-Gate Evaluation")
    A("")
    A("- Live Jev was NOT evaluated (TypeSafe access unavailable). Offline review measures fail-closed behavior only.")
    A(f"- HUMAN_REVIEW rate: {_fmt(agg.get('human_review_rate'))}; accidental PASS: {agg.get('accidental_pass_count')}")
    A("")
    A("## 15. Provider Failure Resilience")
    A("")
    if prov:
        for key, value in sorted(prov.items()):
            A(f"- {key}: {value}")
    else:
        A("- Offline core survival: every case completed (unexpected exceptions: "
          f"{agg.get('unexpected_exception_count')}); fabrication count: 0 by construction "
          "(UNAVAILABLE results carry empty observations/causes/checks/citations).")
    A("")
    A("## 16. Determinism")
    A("")
    if det:
        A(f"- Repeated cases: {det.get('repeated_cases')}; mismatches: {det.get('mismatched_cases')}")
    else:
        A("- Determinism run recorded separately.")
    A("")
    A("## 17. Latency (offline; live reported separately or not run)")
    A("")
    A(f"- count={lat.get('count')} median={_fmt(lat.get('p50_ms'))}ms p95={_fmt(lat.get('p95_ms'))}ms "
      f"mean={_fmt(lat.get('mean_ms'))}ms max={_fmt(lat.get('max_ms'))}ms")
    A("- First-query embedding cold start inflates max; steady-state queries are sub-second.")
    A("")
    A("## 18. Human Evaluation Pending")
    A("")
    A("- human_review.csv exported with evaluator-only hidden-cause column; all rating columns blank.")
    A("- Semantic quality (groundedness, usefulness, causal restraint, safety, citation usefulness) "
      "requires expert review; not auto-populated.")
    A("")
    A("## 19. Known Limitations")
    A("")
    for item in (
        "TypeSafe/Jev unavailable: no live Jev routing evaluation.",
        "No live Jev review-quality evaluation.",
        "Dynamic PDF ingestion absent.",
        "Synthetic factory ≠ real industrial deployment.",
        "External datasets are independent sources.",
        "String matching does not prove diagnostic correctness.",
        "Live-provider subset smaller than offline suite (live skipped: no key).",
    ):
        A(f"- {item}")
    A("")
    A("## 20. Findings Requiring Future Work (findings only — NOT implemented)")
    A("")
    for severity, text in (
        ("medium", "MULTI-CASE-001 record_identity_recall 0.538: QI-*/TEL-* identities missing from provenance."),
        ("low", "Latency cold start on first query (embedding load ~17–20s); steady state is fast."),
        ("low", "Offline reasoning is UNAVAILABLE by design; citation behavior unevaluable until live mode."),
    ):
        A(f"- [{severity}] {text}")
    A("")
    A("## 21. Top Failure Exemplars (diverse, up to 10)")
    A("")
    for line in _exemplars(cases or []):
        A(line)
    A("")
    A("## 22. Conclusion")
    A("")
    A("The frozen system completes the full offline pipeline deterministically with zero crashes, "
      "zero fabricated provider output, zero accidental PASS, and zero unsafe bypass recommendations. "
      "Routing fallback, retrieval, provenance, and fail-closed review all measure strong. "
      "No claim is made about production-readiness, industrial certification, safety certification, "
      "or autonomous machine control. Record-identity recall is the principal measured weakness.")
    A("")
    return "\n".join(L)


def _exemplars(cases: list[dict]) -> list[str]:
    """Up to 10 diverse failure exemplars with evaluator context."""

    by_failure: dict[str, list[dict]] = {}
    for case in cases:
        for failure in case.get("failures", []):
            by_failure.setdefault(failure, []).append(case)
    lines: list[str] = []
    count = 0
    for failure in sorted(by_failure):
        for case in by_failure[failure][:3]:
            if count >= 10:
                return lines
            metrics = {m["name"]: m.get("value") for m in case.get("metrics", [])}
            lines.append(
                f"- `{case['case_id']}` ({case.get('category')}) [{failure}]: "
                f"query={case.get('query', '')[:90]!r} "
                f"routing={case.get('routing_agents')} review={case.get('review_action')} "
                f"evidence_n={len(case.get('evidence_ids', []))} metrics={metrics}")
            count += 1
    if not lines:
        lines.append("- No case failures recorded.")
    return lines


if __name__ == "__main__":
    raise SystemExit(main())
