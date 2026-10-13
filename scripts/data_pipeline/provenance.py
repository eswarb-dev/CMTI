from __future__ import annotations

import hashlib
from pathlib import Path

import polars as pl


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_record_id(dataset_id: str, source_file: str, row_number: int) -> str:
    payload = f"{dataset_id}|{source_file}|{row_number}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def add_provenance(
    frame: pl.DataFrame,
    *,
    dataset_id: str,
    source_file: str,
    source_domain: str,
    row_number_column: str = "source_row_number",
) -> pl.DataFrame:
    if row_number_column not in frame.columns:
        frame = frame.with_row_index(row_number_column, offset=2)
    ids = [
        stable_record_id(dataset_id, source_file, int(row_number))
        for row_number in frame[row_number_column].to_list()
    ]
    return frame.with_columns(
        [
            pl.lit(dataset_id).alias("source_dataset"),
            pl.lit(source_file).alias("source_file"),
            pl.Series("source_record_id", ids),
            pl.col(row_number_column).cast(pl.Int64),
            pl.lit(source_domain).alias("source_domain"),
            pl.lit(True).alias("is_external_dataset"),
        ]
    )

