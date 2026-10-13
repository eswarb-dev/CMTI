from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASETS_ROOT = PROJECT_ROOT / "datasets"
RAW_ROOT = DATASETS_ROOT / "raw" / "structured"
STAGED_ROOT = DATASETS_ROOT / "staged"
NORMALIZED_ROOT = DATASETS_ROOT / "normalized" / "external"
MANIFESTS_ROOT = DATASETS_ROOT / "manifests"
REPORTS_ROOT = DATASETS_ROOT / "reports"

