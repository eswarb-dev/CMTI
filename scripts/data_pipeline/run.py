from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import polars as pl

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.data_pipeline.adapters import ADAPTERS
from scripts.data_pipeline.base import Artifact
from scripts.data_pipeline.common import ensure_dir, write_json
from scripts.data_pipeline.paths import MANIFESTS_ROOT, REPORTS_ROOT
from scripts.data_pipeline.validators import validate_raw_hashes


def artifact_to_report(adapter_name: str, artifact: Artifact) -> list[str]:
    lines = [
        f"## {adapter_name}: {artifact.artifact_name}",
        "",
        f"- Output location: `{artifact.path}`",
        f"- Raw record count: {artifact.input_rows}",
        f"- Normalized record count: {artifact.rows}",
        f"- Output columns: {artifact.columns}",
        f"- Source files: {', '.join(artifact.source_files)}",
        "",
        "### Duplicate Statistics",
        "",
        "```json",
        __import__("json").dumps(artifact.duplicate_statistics, indent=2, ensure_ascii=False),
        "```",
        "",
        "### Null Statistics",
        "",
        "```json",
        __import__("json").dumps(artifact.null_statistics, indent=2, ensure_ascii=False),
        "```",
        "",
        "### Invalid Parse / Label Statistics",
        "",
        "```json",
        __import__("json").dumps(artifact.invalid_values, indent=2, ensure_ascii=False),
        "```",
        "",
        "### Source To Normalized Mapping",
        "",
        "See the adapter implementation and output Parquet schema. STEP 01 preserves source-specific records independently and does not merge datasets.",
        "",
        "### Derived Columns",
        "",
    ]
    if artifact.derived_columns:
        for name, description in artifact.derived_columns.items():
            lines.append(f"- `{name}`: {description}")
    else:
        lines.append("- None")
    lines.extend(["", "### Warnings", ""])
    if artifact.warnings:
        lines.extend([f"- {warning}" for warning in artifact.warnings])
    else:
        lines.append("- None")
    lines.append("")
    return lines


def write_normalization_report(results: dict[str, list[Artifact]]) -> None:
    lines = [
        "# Normalization Report",
        "",
        "STEP 01 normalized independent external structured datasets only. No application database, RAG, agents, LLM integration, or synthetic demo factory was created.",
        "",
    ]
    for adapter_name, artifacts in results.items():
        for artifact in artifacts:
            lines.extend(artifact_to_report(adapter_name, artifact))
    ensure_dir(REPORTS_ROOT)
    (REPORTS_ROOT / "NORMALIZATION_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def run_adapters(dataset: str | None, validate_only: bool) -> dict[str, list[Artifact]]:
    selected = ADAPTERS if dataset is None else {dataset: ADAPTERS[dataset]}
    results: dict[str, list[Artifact]] = {}
    transformations: list[dict[str, Any]] = []
    normalized_entries: list[dict[str, Any]] = []

    validate_raw_hashes()
    for name, adapter_cls in selected.items():
        adapter = adapter_cls()
        adapter.validate_source()
        if validate_only:
            print(f"validated source: {name}")
            continue
        artifacts = adapter.run()
        results[name] = artifacts
        t_entries, n_entries = adapter.build_manifest_entries(artifacts)
        transformations.extend(t_entries)
        normalized_entries.extend(n_entries)

    if not validate_only:
        write_json(MANIFESTS_ROOT / "transformations.json", transformations)
        write_json(MANIFESTS_ROOT / "normalized_datasets.json", normalized_entries)
        write_normalization_report(results)
        for entries in results.values():
            for artifact in entries:
                pl.scan_parquet(artifact.path).limit(1).collect()
    validate_raw_hashes()
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ManufacturaIQ STEP 01 offline data normalization")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Run all dataset adapters")
    group.add_argument("--dataset", choices=sorted(ADAPTERS), help="Run one dataset adapter")
    parser.add_argument("--validate-only", action="store_true", help="Validate raw/source preconditions without writing outputs")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_adapters(None if args.all else args.dataset, args.validate_only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

