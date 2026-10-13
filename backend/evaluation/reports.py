"""Evaluation report writers (stdlib only: json + csv)."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

_SECRET_PATTERNS = (
    re.compile(r"(?i)(gemini_api_key|typesafe_api_key)\s*[:=]\s*\S+"),
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"AQ\.[A-Za-z0-9_\-]{20,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-\.]+"),
)


def scan_for_secrets(text: str) -> list[str]:
    """Return matched secret-pattern descriptions (never the secret itself)."""

    hits: list[str] = []
    for index, pattern in enumerate(_SECRET_PATTERNS):
        if pattern.search(text):
            hits.append(f"secret_pattern_{index}")
    return hits


def write_run(output_dir: Path, run, payloads: list[dict[str, Any]], summary: dict[str, Any],
              determinism: dict[str, Any]) -> dict[str, Path]:
    """Write all run artifacts; raise if a secret pattern is detected."""

    output_dir.mkdir(parents=True, exist_ok=False)
    run_dict = run.model_dump(mode="json")
    summary_doc = {"run": run_dict, "summary": summary, "determinism": determinism}
    (output_dir / "summary.json").write_text(json.dumps(summary_doc, indent=1), encoding="utf-8")

    cases_path = output_dir / "cases.jsonl"
    with cases_path.open("w", encoding="utf-8") as handle:
        for payload in payloads:
            handle.write(payload["case"].model_dump_json() + "\n")

    metrics_doc = {"run_id": run.run_id, "metric_means": summary.get("metric_means", {}),
                   "latency": summary.get("latency", {}),
                   "failure_counts": summary.get("failure_counts", {})}
    (output_dir / "metrics.json").write_text(json.dumps(metrics_doc, indent=1), encoding="utf-8")

    failures_path = output_dir / "failures.jsonl"
    with failures_path.open("w", encoding="utf-8") as handle:
        for payload in payloads:
            case = payload["case"]
            if case.failures:
                handle.write(json.dumps({"case_id": case.case_id, "category": case.category,
                                         "failures": case.failures, "warnings": case.warnings}) + "\n")

    human_path = output_dir / "human_review.csv"
    rows = [p["human_row"] for p in payloads]
    with human_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else ["case_id"])
        writer.writeheader()
        writer.writerows(rows)

    latency_path = output_dir / "latency.csv"
    with latency_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["case_id", "category", "latency_ms"])
        for payload in payloads:
            writer.writerow([payload["case"].case_id, payload["case"].category, payload["case"].latency_ms])

    (output_dir / "SYSTEM_EVALUATION_REPORT.md").write_text(
        render_markdown(run_dict, summary, determinism, payloads), encoding="utf-8")

    paths = {"summary": output_dir / "summary.json", "cases": cases_path,
             "metrics": output_dir / "metrics.json", "failures": failures_path,
             "human_review": human_path, "latency": latency_path,
             "report": output_dir / "SYSTEM_EVALUATION_REPORT.md"}
    for path in paths.values():
        hits = scan_for_secrets(path.read_text(encoding="utf-8"))
        if hits:
            raise AssertionError(f"secret pattern detected in {path.name}: {hits}")
    return paths


def render_markdown(run: dict[str, Any], summary: dict[str, Any],
                    determinism: dict[str, Any], payloads: list[dict[str, Any]]) -> str:
    lines = [
        "# System Evaluation Report",
        "",
        f"- run_id: `{run.get('run_id')}`",
        f"- mode: `{run.get('mode')}` (offline = deterministic fallback routing, NOT live Jev quality)",
        f"- suite: `{run.get('suite')}`",
        f"- cases: {summary.get('case_count')}",
        f"- cases with failures: {summary.get('cases_with_failures')}",
        "",
        "## Metric means",
        "",
    ]
    for name, agg in sorted((summary.get("metric_means", {}) or {}).items()):
        lines.append(f"- {name}: mean={agg['mean']:.3f} (n={agg['n']})")
    lines += ["", "## Failure counts", ""]
    for name, count in sorted((summary.get("failure_counts", {}) or {}).items()):
        lines.append(f"- {name}: {count}")
    lat = summary.get("latency", {}) or {}
    lines += ["", "## Latency (harness-observable, ms)", "",
              f"- count={lat.get('count')} mean={lat.get('mean_ms')} p50={lat.get('p50_ms')} "
              f"p95={lat.get('p95_ms')} max={lat.get('max_ms')}",
              "", "## Determinism", "",
              f"- repeated cases: {determinism.get('repeated_cases')}",
              f"- mismatched: {determinism.get('mismatched_cases')}",
              "", "## Environment (no secrets)", ""]
    for key, value in sorted((run.get("environment", {}) or {}).items()):
        lines.append(f"- {key}: {value}")
    lines += ["", "## Limitations",
              "",
              "- Live Jev semantic routing is NOT evaluated (TypeSafe access unavailable).",
              "- Live Jev final-review quality is NOT evaluated.",
              "- Offline routing metrics describe deterministic fallback routing only.",
              "- Human semantic ratings cannot be replaced by deterministic string matching.",
              "- Dynamic PDF ingestion is not implemented and out of scope.",
              "- External datasets are independent sources, not one coherent real factory.",
              "- Synthetic demo-factory results do not prove industrial deployment performance.",
              ""]
    return "\n".join(lines)
