from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


def _sha256(path: Path) -> str:
    if not path.is_file():
        return "MISSING"
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@pytest.fixture(scope="session", autouse=True)
def _guard_canonical_step03_artifacts():
    """Fail the suite if any test mutates canonical STEP 03 artifacts.

    Document-pipeline tests must operate exclusively inside ``tmp_path``;
    extraction into canonical paths is forbidden, even when it "passes".
    """

    from scripts.document_pipeline.config import (
        MANIFEST_PATH,
        METADATA_DIR,
        PAGES_DIR,
        REPORT_PATH,
    )

    guarded = [
        PAGES_DIR / "document_pages.parquet",
        METADATA_DIR / "document_metadata.parquet",
        METADATA_DIR / "candidate_headings.parquet",
        MANIFEST_PATH,
        REPORT_PATH,
    ]
    before = {str(path): _sha256(path) for path in guarded}
    yield
    for path in guarded:
        assert _sha256(path) == before[str(path)], (
            f"canonical STEP 03 artifact mutated by tests: {path}"
        )
