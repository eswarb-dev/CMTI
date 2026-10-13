from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent

EXPECTED_DATASETS = {
    "kaggle_industrial_maintenance_synthetic": "industrial_maintenance",
    "kaggle_faulty_steel_plates": "steel_faults",
    "kaggle_cnc_mill_tool_wear": "cnc_tool_wear",
    "kaggle_ai4i_predictive_maintenance": "predictive_maintenance",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fail(message: str, failures: list[str]) -> None:
    print(f"FAIL: {message}")
    failures.append(message)


def ok(message: str) -> None:
    print(f"OK: {message}")


def main() -> int:
    failures: list[str] = []
    raw_root = ROOT / "raw" / "structured"
    sources_path = ROOT / "manifests" / "sources.json"
    files_path = ROOT / "manifests" / "files.json"

    for canonical in EXPECTED_DATASETS.values():
        path = raw_root / canonical
        if path.is_dir():
            ok(f"canonical dataset folder exists: {path}")
        else:
            fail(f"missing canonical dataset folder: {path}", failures)

    if sources_path.is_file():
        ok(f"source manifest exists: {sources_path}")
    else:
        fail(f"missing source manifest: {sources_path}", failures)

    if files_path.is_file():
        ok(f"file manifest exists: {files_path}")
    else:
        fail(f"missing file manifest: {files_path}", failures)

    if failures:
        return 1

    sources = json.loads(sources_path.read_text(encoding="utf-8"))
    files = json.loads(files_path.read_text(encoding="utf-8"))
    source_by_id = {entry["source_id"]: entry for entry in sources}

    for dataset_id, canonical in EXPECTED_DATASETS.items():
        if dataset_id in source_by_id:
            ok(f"expected dataset id exists: {dataset_id}")
        else:
            fail(f"missing expected dataset id: {dataset_id}", failures)
            continue
        raw_dir = Path(source_by_id[dataset_id]["raw_directory"])
        source_dir = Path(source_by_id[dataset_id]["source_directory"])
        if raw_dir == raw_root / canonical:
            ok(f"raw directory matches expected canonical path for {dataset_id}")
        else:
            fail(f"unexpected raw directory for {dataset_id}: {raw_dir}", failures)
        if source_dir.is_dir():
            ok(f"source directory exists for {dataset_id}")
        else:
            fail(f"source directory missing for {dataset_id}: {source_dir}", failures)

    for entry in files:
        dataset_id = entry["dataset_id"]
        source_entry = source_by_id.get(dataset_id)
        if not source_entry:
            fail(f"file references unknown dataset id: {dataset_id}", failures)
            continue
        relative_path = Path(entry["relative_path"])
        raw_path = Path(source_entry["raw_directory"]) / relative_path
        source_path = Path(source_entry["source_directory"]) / relative_path

        if not raw_path.is_file():
            fail(f"copied raw file missing: {raw_path}", failures)
            continue
        if raw_path.stat().st_size == 0:
            fail(f"unexpected zero-byte raw file: {raw_path}", failures)
        if raw_path.stat().st_size != entry["size_bytes"]:
            fail(f"raw file size changed: {raw_path}", failures)
        current_raw_hash = sha256_file(raw_path)
        if current_raw_hash != entry["sha256"]:
            fail(f"raw file hash changed: {raw_path}", failures)
        if not source_path.is_file():
            fail(f"original source file missing: {source_path}", failures)
            continue
        if source_path.stat().st_size != raw_path.stat().st_size:
            fail(f"source/raw size mismatch: {source_path} -> {raw_path}", failures)
        current_source_hash = sha256_file(source_path)
        if current_source_hash != current_raw_hash:
            fail(f"source/raw hash mismatch: {source_path} -> {raw_path}", failures)

    if failures:
        print("")
        print(f"Validation failed with {len(failures)} issue(s).")
        return 1

    print("")
    print(f"Validation passed for {len(files)} copied raw file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
