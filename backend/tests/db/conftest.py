from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as parquet
import pytest

from app.core.config import get_settings
from app.db.initializer import initialize_database
from app.db.schema import TABLE_ORDER


@pytest.fixture(scope="session")
def demo_source_dir() -> Path:
    return Path(get_settings().demo_factory_root)


@pytest.fixture(scope="session")
def source_row_counts(demo_source_dir: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name in TABLE_ORDER:
        counts[name] = parquet.read_metadata(demo_source_dir / f"{name}.parquet").num_rows
    return counts


@pytest.fixture(scope="session")
def initialized_database(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("operational") / "manufacturaiq.db"
    initialize_database(path)
    return path
