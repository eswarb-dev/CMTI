from __future__ import annotations

from pathlib import Path

import polars as pl

from .common import read_json
from .paths import MANIFESTS_ROOT, RAW_ROOT
from .provenance import sha256_file


def assert_columns(path: Path, expected: list[str]) -> None:
    columns = pl.read_csv(path, n_rows=0).columns
    missing = [column for column in expected if column not in columns]
    if missing:
        raise ValueError(f"{path} missing expected columns: {missing}")


def validate_raw_hashes() -> None:
    sources = {entry["source_id"]: entry for entry in read_json(MANIFESTS_ROOT / "sources.json")}
    for entry in read_json(MANIFESTS_ROOT / "files.json"):
        source = sources[entry["dataset_id"]]
        raw_path = Path(source["raw_directory"]) / entry["relative_path"]
        if not raw_path.is_file():
            raise FileNotFoundError(raw_path)
        actual = sha256_file(raw_path)
        if actual != entry["sha256"]:
            raise ValueError(f"Raw hash mismatch for {raw_path}")


def validate_provenance(path: Path) -> None:
    frame = pl.read_parquet(path)
    required = [
        "source_dataset",
        "source_file",
        "source_record_id",
        "source_row_number",
        "source_domain",
        "is_external_dataset",
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"{path} missing provenance columns: {missing}")
    has_null = frame.select(
        pl.any_horizontal([pl.col(column).is_null() for column in required]).any()
    ).item()
    if has_null:
        raise ValueError(f"{path} contains null provenance values")
    if not bool(frame["is_external_dataset"].all()):
        raise ValueError(f"{path} contains non-external records")


def canonical_raw_path(canonical_name: str, file_name: str) -> Path:
    return RAW_ROOT / canonical_name / file_name

