from __future__ import annotations

import csv
import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DATASETS_ROOT = Path(r"D:\CMTI\datasets")

DATASETS = [
    {
        "source_id": "kaggle_industrial_maintenance_synthetic",
        "display_name": "Industrial Maintenance Synthetic Dataset",
        "canonical_name": "industrial_maintenance",
        "domains": ["maintenance", "telemetry"],
        "match": "Industrial Maintenance Synthetic Dataset",
        "synthetic": True,
        "usage": [
            "Maintenance Agent",
            "Maintenance work-order/history evidence",
            "Industrial telemetry evidence",
        ],
    },
    {
        "source_id": "kaggle_faulty_steel_plates",
        "display_name": "Faulty Steel Plates",
        "canonical_name": "steel_faults",
        "domains": ["quality"],
        "match": "Faulty Steel Plates",
        "synthetic": False,
        "usage": ["Quality Agent", "Defect/fault evidence", "Quality analytics"],
    },
    {
        "source_id": "kaggle_cnc_mill_tool_wear",
        "display_name": "CNC Mill Tool Wear",
        "canonical_name": "cnc_tool_wear",
        "domains": ["maintenance", "production", "telemetry"],
        "match": "CNC Mill Tool Wear",
        "synthetic": False,
        "usage": [
            "CNC operational evidence",
            "Tool-condition evidence",
            "Maintenance evidence",
            "Production/process evidence",
            "Telemetry evidence",
        ],
    },
    {
        "source_id": "kaggle_ai4i_predictive_maintenance",
        "display_name": "Machine Predictive Maintenance Classification",
        "canonical_name": "predictive_maintenance",
        "domains": ["maintenance", "telemetry"],
        "match": "Machine Predictive Maintenance Classification",
        "synthetic": False,
        "usage": [
            "Maintenance Agent",
            "Telemetry evidence",
            "Machine-state/failure experiments",
        ],
    },
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def detect_encoding(path: Path) -> str:
    sample = path.read_bytes()[:65536]
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            sample.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    return "binary"


def detect_dialect(path: Path, encoding: str) -> csv.Dialect:
    with path.open("r", encoding=encoding, newline="", errors="replace") as handle:
        sample = handle.read(65536)
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        return csv.get_dialect("excel")


def infer_value_type(value: str) -> str:
    text = value.strip()
    if text == "":
        return "null"
    lowered = text.lower()
    if lowered in {"true", "false", "yes", "no"}:
        return "bool"
    try:
        int(text)
        return "integer"
    except ValueError:
        pass
    try:
        float(text)
        return "number"
    except ValueError:
        return "string"


def combine_types(types: set[str]) -> str:
    types.discard("null")
    if not types:
        return "null"
    if types == {"integer"}:
        return "integer"
    if types <= {"integer", "number"}:
        return "number"
    if types == {"bool"}:
        return "bool"
    return "string"


def inspect_csv(path: Path) -> dict[str, Any]:
    encoding = detect_encoding(path)
    dialect = detect_dialect(path, encoding)
    nulls: Counter[str] = Counter()
    uniques: dict[str, set[str]] = {}
    examples: dict[str, str] = {}
    types: dict[str, set[str]] = {}
    row_hashes: set[str] = set()
    duplicate_rows = 0
    row_count = 0

    with path.open("r", encoding=encoding, newline="", errors="replace") as handle:
        reader = csv.DictReader(handle, dialect=dialect)
        columns = list(reader.fieldnames or [])
        for column in columns:
            uniques[column] = set()
            types[column] = set()
        for row in reader:
            row_count += 1
            row_key = json.dumps([row.get(column, "") for column in columns], ensure_ascii=False)
            row_digest = hashlib.sha256(row_key.encode("utf-8")).hexdigest()
            if row_digest in row_hashes:
                duplicate_rows += 1
            else:
                row_hashes.add(row_digest)
            for column in columns:
                value = row.get(column, "")
                if value is None or value == "":
                    nulls[column] += 1
                elif column not in examples:
                    examples[column] = value
                if len(uniques[column]) <= 10000:
                    uniques[column].add("" if value is None else value)
                types[column].add(infer_value_type("" if value is None else value))

    delimiter = getattr(dialect, "delimiter", ",")
    column_stats = [
        {
            "name": column,
            "inferred_type": combine_types(types[column]),
            "null_count": int(nulls[column]),
            "unique_count": len(uniques[column]),
            "example": examples.get(column, ""),
        }
        for column in columns
    ]
    return {
        "format": "csv",
        "encoding": encoding,
        "delimiter": delimiter,
        "row_count": row_count,
        "column_count": len(columns),
        "columns": columns,
        "column_stats": column_stats,
        "duplicate_row_count": duplicate_rows,
        "null_counts": {column: int(nulls[column]) for column in columns},
        "inferred_types": {stat["name"]: stat["inferred_type"] for stat in column_stats},
    }


def inspect_file(path: Path) -> dict[str, Any]:
    info: dict[str, Any] = {
        "name": path.name,
        "extension": path.suffix.lower(),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    if path.suffix.lower() in {".csv", ".tsv"}:
        info.update(inspect_csv(path))
    else:
        info.update(
            {
                "format": path.suffix.lower().lstrip(".") or "file",
                "encoding": detect_encoding(path) if path.suffix.lower() in {".txt", ".md"} else None,
                "row_count": None,
                "column_count": None,
                "columns": [],
                "column_stats": [],
                "duplicate_row_count": None,
                "null_counts": {},
                "inferred_types": {},
            }
        )
    return info


def discover_sources() -> dict[str, Path]:
    directories = [path for path in DATASETS_ROOT.iterdir() if path.is_dir()]
    found: dict[str, Path] = {}
    for spec in DATASETS:
        matches = [path for path in directories if spec["match"].lower() in path.name.lower()]
        if len(matches) == 1:
            found[spec["canonical_name"]] = matches[0]
        elif not matches:
            raise SystemExit(f"Missing dataset source: {spec['display_name']}")
        else:
            names = ", ".join(str(path) for path in matches)
            raise SystemExit(f"Ambiguous dataset source for {spec['display_name']}: {names}")
    return found


def ensure_directories() -> None:
    for relative in [
        "raw/structured/industrial_maintenance",
        "raw/structured/steel_faults",
        "raw/structured/cnc_tool_wear",
        "raw/structured/predictive_maintenance",
        "staged/maintenance",
        "staged/quality",
        "staged/production",
        "staged/telemetry",
        "staged/alarms",
        "normalized/maintenance",
        "normalized/quality",
        "normalized/production",
        "normalized/telemetry",
        "normalized/alarms",
        "manifests",
        "reports/schema",
    ]:
        (DATASETS_ROOT / relative).mkdir(parents=True, exist_ok=True)


def write_readmes() -> None:
    readmes = {
        "raw/README.md": "# Raw datasets\n\nThis directory contains immutable copies of external source datasets. Files here preserve source-relative paths and must not be modified in place.\n",
        "staged/README.md": "# Staged datasets\n\nThis directory will later contain source-specific cleaned or intermediate representations. It is intentionally empty in the dataset organization stage.\n",
        "normalized/README.md": "# Normalized datasets\n\nThis directory will later contain ManufacturaIQ canonical domain models used by the application. No normalized data is created during the dataset organization stage.\n",
    }
    for relative, content in readmes.items():
        (DATASETS_ROOT / relative).write_text(content, encoding="utf-8")


def copy_sources(sources: dict[str, Path]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    copied: dict[str, list[dict[str, Any]]] = {}
    totals = {"copied": 0, "skipped_identical": 0, "conflicts": 0}
    for spec in DATASETS:
        canonical = spec["canonical_name"]
        source_dir = sources[canonical]
        target_dir = DATASETS_ROOT / "raw" / "structured" / canonical
        copied[canonical] = []
        for source_path in sorted(path for path in source_dir.rglob("*") if path.is_file()):
            relative = source_path.relative_to(source_dir)
            target_path = target_dir / relative
            target_path.parent.mkdir(parents=True, exist_ok=True)
            source_hash = sha256_file(source_path)
            action = "copied"
            if target_path.exists():
                if sha256_file(target_path) == source_hash:
                    action = "skipped_identical"
                    totals["skipped_identical"] += 1
                else:
                    action = "conflict"
                    totals["conflicts"] += 1
            else:
                shutil.copy2(source_path, target_path)
                totals["copied"] += 1
            copied[canonical].append(
                {
                    "relative_path": str(relative).replace("\\", "/"),
                    "source_path": str(source_path),
                    "raw_path": str(target_path),
                    "size_bytes": source_path.stat().st_size,
                    "sha256": source_hash,
                    "copy_action": action,
                }
            )
    return copied, totals


def build_reports(
    sources: dict[str, Path],
    copied_files: dict[str, list[dict[str, Any]]],
    copy_totals: dict[str, int],
) -> None:
    source_manifest: list[dict[str, Any]] = []
    file_manifest: list[dict[str, Any]] = []
    inventory_sections: list[str] = ["# Dataset Inventory", ""]
    organization_sections: list[str] = [
        "# Dataset Organization Report",
        "",
        "## Dataset Organization Summary",
        "",
        f"Generated at: {datetime.now(timezone.utc).isoformat()}",
        "",
    ]

    total_source_size = 0
    total_raw_size = 0
    schema_summary: list[str] = []

    for spec in DATASETS:
        canonical = spec["canonical_name"]
        source_dir = sources[canonical]
        raw_dir = DATASETS_ROOT / "raw" / "structured" / canonical
        source_files = sorted(path for path in source_dir.rglob("*") if path.is_file())
        source_dirs = sorted(path for path in source_dir.rglob("*") if path.is_dir())
        total_size = sum(path.stat().st_size for path in source_files)
        total_source_size += total_size
        total_raw_size += sum(path.stat().st_size for path in raw_dir.rglob("*") if path.is_file())

        inspected_files = []
        for entry in copied_files[canonical]:
            raw_path = Path(entry["raw_path"])
            inspection = inspect_file(raw_path)
            inspection.update(
                {
                    "dataset_id": spec["source_id"],
                    "canonical_name": canonical,
                    "relative_path": entry["relative_path"],
                    "source_path": entry["source_path"],
                    "raw_path": entry["raw_path"],
                    "copy_action": entry["copy_action"],
                }
            )
            inspected_files.append(inspection)
            file_manifest.append(
                {
                    "dataset_id": spec["source_id"],
                    "canonical_name": canonical,
                    "relative_path": entry["relative_path"],
                    "extension": raw_path.suffix.lower(),
                    "size_bytes": inspection["size_bytes"],
                    "sha256": inspection["sha256"],
                    "row_count": inspection["row_count"],
                    "column_count": inspection["column_count"],
                }
            )

        source_manifest.append(
            {
                "source_id": spec["source_id"],
                "display_name": spec["display_name"],
                "canonical_name": canonical,
                "source_type": "structured_dataset",
                "domain": spec["domains"],
                "source_platform": "Kaggle",
                "source_directory": str(source_dir),
                "raw_directory": str(raw_dir),
                "is_external_dataset": True,
                "is_synthetic": spec["synthetic"],
                "files": [
                    {
                        "relative_path": item["relative_path"],
                        "extension": item["extension"],
                        "size_bytes": item["size_bytes"],
                        "sha256": item["sha256"],
                    }
                    for item in inspected_files
                ],
                "total_files": len(inspected_files),
                "total_size_bytes": total_size,
                "status": "available",
            }
        )

        table_files = [item for item in inspected_files if item["format"] == "csv"]
        primary_files = sorted(table_files, key=lambda item: item["size_bytes"], reverse=True)[:3]
        inventory_sections.extend(
            [
                f"## {spec['display_name']}",
                "",
                f"- Source directory: `{source_dir}`",
                f"- Canonical raw directory: `{raw_dir}`",
                f"- Files discovered: {len(source_files)}",
                f"- Nested directories: {len(source_dirs)}",
                f"- Total size: {total_size} bytes",
                f"- Primary file(s): {', '.join(item['relative_path'] for item in primary_files) or 'None detected'}",
                f"- Potential ManufacturaIQ usage: {', '.join(spec['usage'])}",
                "",
            ]
        )
        for item in inspected_files:
            inventory_sections.extend(
                [
                    f"### {item['relative_path']}",
                    "",
                    f"- Extension: `{item['extension'] or '(none)'}`",
                    f"- Size: {item['size_bytes']} bytes",
                    f"- SHA-256: `{item['sha256']}`",
                    f"- Rows: {item['row_count']}",
                    f"- Columns: {item['column_count']}",
                    f"- CSV delimiter: `{item.get('delimiter', '')}`" if item["format"] == "csv" else "- CSV delimiter: N/A",
                    f"- CSV encoding: `{item.get('encoding')}`" if item.get("encoding") else "- CSV encoding: N/A",
                    f"- Duplicate rows: {item['duplicate_row_count']}",
                    f"- Column names: {', '.join(item['columns']) if item['columns'] else 'N/A'}",
                    f"- Data types: {json.dumps(item['inferred_types'], ensure_ascii=False)}",
                    f"- Missing values: {json.dumps(item['null_counts'], ensure_ascii=False)}",
                    "",
                ]
            )
            if item["format"] == "csv":
                schema_summary.append(
                    f"- {canonical}/{item['relative_path']}: {item['row_count']} rows, {item['column_count']} columns"
                )

        schema_lines = [f"# Schema: {spec['display_name']}", ""]
        for item in inspected_files:
            schema_lines.extend(
                [
                    f"## File: {item['relative_path']}",
                    "",
                    f"Rows: {item['row_count']}",
                    f"Columns: {item['column_count']}",
                    "",
                ]
            )
            if item["format"] != "csv":
                schema_lines.extend(["Non-tabular file; schema inspection is not applicable.", ""])
                continue
            schema_lines.extend(
                [
                    "| Column | Inferred Type | Null Count | Unique Count | Example |",
                    "|--------|---------------|------------|--------------|---------|",
                ]
            )
            for column in item["column_stats"]:
                example = str(column["example"]).replace("|", "\\|").replace("\n", " ")[:120]
                schema_lines.append(
                    f"| {column['name']} | {column['inferred_type']} | {column['null_count']} | {column['unique_count']} | {example} |"
                )
            schema_lines.extend(["", "### Potential future mapping", "", "| Source Column | Possible ManufacturaIQ Concept | Status |", "|---------------|--------------------------------|--------|"])
            for column in item["columns"]:
                schema_lines.append(f"| {column} | Source-specific evidence attribute | PROPOSED |")
            schema_lines.append("")
        (DATASETS_ROOT / "reports" / "schema" / f"{canonical}.md").write_text(
            "\n".join(schema_lines), encoding="utf-8"
        )

        organization_sections.extend(
            [
                f"### {spec['display_name']}",
                "",
                f"- Source path: `{source_dir}`",
                f"- Canonical path: `{raw_dir}`",
                f"- Files copied this run: {sum(1 for item in copied_files[canonical] if item['copy_action'] == 'copied')}",
                f"- Files skipped because identical: {sum(1 for item in copied_files[canonical] if item['copy_action'] == 'skipped_identical')}",
                f"- Conflicts: {sum(1 for item in copied_files[canonical] if item['copy_action'] == 'conflict')}",
                f"- Source file count: {len(source_files)}",
                f"- Source size: {total_size} bytes",
                "",
            ]
        )

    (DATASETS_ROOT / "manifests" / "sources.json").write_text(
        json.dumps(source_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (DATASETS_ROOT / "manifests" / "files.json").write_text(
        json.dumps(file_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (DATASETS_ROOT / "reports" / "DATASET_INVENTORY.md").write_text(
        "\n".join(inventory_sections), encoding="utf-8"
    )

    organization_sections.extend(
        [
            "## Totals",
            "",
            f"- Files copied this run: {copy_totals['copied']}",
            f"- Files skipped because identical: {copy_totals['skipped_identical']}",
            f"- Conflicts: {copy_totals['conflicts']}",
            f"- Total source size: {total_source_size} bytes",
            f"- Total canonical raw size: {total_raw_size} bytes",
            "",
            "## Validation Result",
            "",
            "Run `python validate_datasets.py` from `D:\\CMTI\\datasets` for the current validation result.",
            "",
            "## Schema Summary",
            "",
            *schema_summary,
            "",
            "## Recommended Next Stage",
            "",
            "Proceed to source-specific staging adapters only after reviewing these manifests and schema reports. Do not merge the independent datasets or normalize them until the next approved stage.",
            "",
        ]
    )
    (DATASETS_ROOT / "reports" / "DATASET_ORGANIZATION_REPORT.md").write_text(
        "\n".join(organization_sections), encoding="utf-8"
    )


def main() -> None:
    ensure_directories()
    write_readmes()
    sources = discover_sources()
    copied_files, copy_totals = copy_sources(sources)
    if copy_totals["conflicts"]:
        raise SystemExit("Conflicting destination files found; reports were not regenerated.")
    build_reports(sources, copied_files, copy_totals)
    print(json.dumps({"sources": {k: str(v) for k, v in sources.items()}, "copy_totals": copy_totals}, indent=2))


if __name__ == "__main__":
    main()
