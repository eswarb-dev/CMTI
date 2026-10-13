from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import polars as pl

from .common import ensure_dir, now_utc
from .paths import NORMALIZED_ROOT, RAW_ROOT, STAGED_ROOT
from .provenance import sha256_file


ADAPTER_VERSION = "step01.v1"


@dataclass
class Artifact:
    artifact_name: str
    path: Path
    domain: list[str]
    rows: int
    columns: int
    source_files: list[str]
    input_rows: int
    input_columns: int
    invalid_values: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    derived_columns: dict[str, str] = field(default_factory=dict)
    duplicate_statistics: dict[str, Any] = field(default_factory=dict)
    null_statistics: dict[str, Any] = field(default_factory=dict)


class DatasetAdapter(ABC):
    dataset_id: str
    canonical_name: str
    adapter_name: str
    domain: list[str]

    def __init__(self) -> None:
        self.raw_dir = RAW_ROOT / self.canonical_name
        self.staged_dir = STAGED_ROOT / self.canonical_name
        self.output_dir = NORMALIZED_ROOT / self.canonical_name
        ensure_dir(self.staged_dir)
        ensure_dir(self.output_dir)

    @abstractmethod
    def inspect_source(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def validate_source(self) -> None:
        raise NotImplementedError

    def stage(self) -> None:
        (self.staged_dir / "README.md").write_text(
            "No full staged data copy is generated in STEP 01. Raw CSV files are transformed directly into normalized external Parquet artifacts.\n",
            encoding="utf-8",
        )

    @abstractmethod
    def normalize(self) -> list[Artifact]:
        raise NotImplementedError

    def validate_output(self, artifacts: list[Artifact]) -> None:
        from .validators import validate_provenance

        for artifact in artifacts:
            frame = pl.read_parquet(artifact.path)
            if frame.height != artifact.rows:
                raise ValueError(f"{artifact.path} row count mismatch")
            validate_provenance(artifact.path)

    def build_statistics(self, artifacts: list[Artifact]) -> dict[str, Any]:
        return {"artifacts": [artifact.__dict__ | {"path": str(artifact.path)} for artifact in artifacts]}

    def build_manifest_entries(self, artifacts: list[Artifact]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        transformations = []
        normalized = []
        generated_at = now_utc()
        for artifact in artifacts:
            raw_hashes = {
                source_file: sha256_file(self.raw_dir / source_file)
                for source_file in artifact.source_files
            }
            transformations.append(
                {
                    "transformation_id": f"{self.canonical_name}.{artifact.artifact_name}.{ADAPTER_VERSION}",
                    "source_dataset": self.dataset_id,
                    "source_files": artifact.source_files,
                    "adapter_name": self.adapter_name,
                    "adapter_version": ADAPTER_VERSION,
                    "destination_file": str(artifact.path),
                    "input_rows": artifact.input_rows,
                    "output_rows": artifact.rows,
                    "input_columns": artifact.input_columns,
                    "output_columns": artifact.columns,
                    "invalid_values": artifact.invalid_values,
                    "warnings": artifact.warnings,
                    "generated_at": generated_at,
                    "raw_source_hashes": raw_hashes,
                }
            )
            normalized.append(
                {
                    "dataset_id": self.dataset_id,
                    "artifact_name": artifact.artifact_name,
                    "path": str(artifact.path),
                    "format": "parquet",
                    "domain": artifact.domain,
                    "rows": artifact.rows,
                    "columns": artifact.columns,
                    "source_dataset": self.dataset_id,
                    "source_files": artifact.source_files,
                    "is_external_dataset": True,
                    "schema_version": "external.step01.v1",
                    "adapter_version": ADAPTER_VERSION,
                }
            )
        return transformations, normalized

    def run(self) -> list[Artifact]:
        self.validate_source()
        self.stage()
        artifacts = self.normalize()
        self.validate_output(artifacts)
        return artifacts

