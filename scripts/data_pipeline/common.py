from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def normalize_name(name: str) -> str:
    text = name.strip()
    text = text.replace("[", "").replace("]", "")
    text = text.replace("(", "").replace(")", "")
    text = re.sub(r"[^0-9A-Za-z]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_").lower()
    return text


def null_count_by_column(frame: pl.DataFrame) -> dict[str, int]:
    return {name: int(frame[name].null_count()) for name in frame.columns}


def duplicate_count(frame: pl.DataFrame, columns: list[str] | None = None) -> int:
    subset = frame.select(columns) if columns else frame
    return int(subset.is_duplicated().sum())


def value_counts_dict(frame: pl.DataFrame, column: str) -> dict[str, int]:
    counts = frame.group_by(column).len().sort(column)
    return {
        str(row[column]): int(row["len"])
        for row in counts.to_dicts()
    }


def write_parquet(frame: pl.DataFrame, path: Path) -> None:
    ensure_dir(path.parent)
    if path.exists():
        path.unlink()
    frame.write_parquet(path)

