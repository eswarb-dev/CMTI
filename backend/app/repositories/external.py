"""Read-only access to normalized external Parquet datasets.

STEP 05 boundary: external datasets are NEVER imported into the operational
SQLite database and are NEVER linked to demo factory machines such as
CNC-01/CNC-03/CNC-05.  Callers can only address whitelisted dataset IDs and
artifact names — arbitrary filesystem paths are impossible by construction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.exceptions import RepositoryError

MAX_SAMPLE_LIMIT = 100
DEFAULT_SAMPLE_LIMIT = 5


@dataclass(frozen=True, slots=True)
class ExternalDatasetSpec:
    """Whitelist entry: one dataset ID and its allowed artifacts."""

    dataset_id: str
    directory: str
    artifacts: tuple[str, ...]


EXTERNAL_DATASETS: dict[str, ExternalDatasetSpec] = {
    spec.dataset_id: spec
    for spec in (
        ExternalDatasetSpec(
            dataset_id="predictive_maintenance",
            directory="predictive_maintenance",
            artifacts=("machine_condition_observations",),
        ),
        ExternalDatasetSpec(
            dataset_id="cnc_tool_wear",
            directory="cnc_tool_wear",
            artifacts=("experiment_metadata", "experiment_samples"),
        ),
        ExternalDatasetSpec(
            dataset_id="steel_faults",
            directory="steel_faults",
            artifacts=("quality_fault_records",),
        ),
        ExternalDatasetSpec(
            dataset_id="industrial_maintenance",
            directory="industrial_maintenance",
            artifacts=("maintenance_work_orders", "sensor_tag_catalog"),
        ),
    )
}


@dataclass(slots=True)
class ExternalArtifactInfo:
    artifact_name: str
    rows: int
    columns: int
    file_name: str


@dataclass(slots=True)
class ExternalDatasetInfo:
    dataset_id: str
    directory: str
    artifacts: list[ExternalArtifactInfo] = field(default_factory=list)


def _require_parquet():
    try:
        import pyarrow.parquet as parquet
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise RepositoryError("pyarrow is required for external dataset access") from exc
    return parquet


class ExternalDatasetRepository:
    """Whitelisted, read-only metadata/sample access to external artifacts."""

    def __init__(self, external_root: str | Path | None = None) -> None:
        settings = get_settings()
        self._root = (
            Path(external_root) if external_root is not None else Path(settings.external_data_root)
        )

    @property
    def root(self) -> Path:
        return self._root

    def _spec(self, dataset_id: str) -> ExternalDatasetSpec:
        spec = EXTERNAL_DATASETS.get(dataset_id)
        if spec is None:
            raise RepositoryError(
                f"unknown external dataset_id {dataset_id!r}; "
                f"allowed: {sorted(EXTERNAL_DATASETS)}"
            )
        return spec

    def _artifact_path(self, dataset_id: str, artifact_name: str) -> Path:
        spec = self._spec(dataset_id)
        if artifact_name not in spec.artifacts:
            raise RepositoryError(
                f"artifact {artifact_name!r} is not whitelisted for dataset {dataset_id!r}; "
                f"allowed: {list(spec.artifacts)}"
            )
        if any(token in artifact_name for token in ("/", "\\", "..")):
            raise RepositoryError("path traversal characters are not allowed")
        root = self._root.resolve()
        path = (root / spec.directory / f"{artifact_name}.parquet").resolve()
        if root not in path.parents:
            raise RepositoryError("resolved artifact path escaped the external data root")
        if not path.is_file():
            raise RepositoryError(f"external artifact missing: {path.name}")
        return path

    async def list_datasets(self) -> list[ExternalDatasetInfo]:
        """List whitelisted external datasets with per-artifact row counts."""

        infos: list[ExternalDatasetInfo] = []
        for dataset_id in sorted(EXTERNAL_DATASETS):
            infos.append(await self.get_dataset_metadata(dataset_id))
        return infos

    async def get_dataset_metadata(self, dataset_id: str) -> ExternalDatasetInfo:
        """Return row/column metadata for every allowed artifact."""

        spec = self._spec(dataset_id)
        parquet = _require_parquet()
        artifacts: list[ExternalArtifactInfo] = []
        for artifact_name in spec.artifacts:
            path = self._artifact_path(dataset_id, artifact_name)
            metadata = parquet.read_metadata(path)
            artifacts.append(
                ExternalArtifactInfo(
                    artifact_name=artifact_name,
                    rows=metadata.num_rows,
                    columns=metadata.num_columns,
                    file_name=path.name,
                )
            )
        return ExternalDatasetInfo(
            dataset_id=dataset_id, directory=spec.directory, artifacts=artifacts
        )

    async def get_schema(self, dataset_id: str, artifact_name: str) -> list[dict[str, Any]]:
        """Return the Parquet schema of one whitelisted artifact."""

        path = self._artifact_path(dataset_id, artifact_name)
        parquet = _require_parquet()
        schema = parquet.read_schema(path)
        return [
            {"name": schema_field.name, "type": str(schema_field.type), "nullable": schema_field.nullable}
            for schema_field in schema
        ]

    async def sample_records(
        self,
        dataset_id: str,
        artifact_name: str,
        limit: int = DEFAULT_SAMPLE_LIMIT,
    ) -> list[dict[str, Any]]:
        """Return at most ``limit`` sample rows from a whitelisted artifact."""

        if limit < 1:
            limit = 1
        limit = min(int(limit), MAX_SAMPLE_LIMIT)
        path = self._artifact_path(dataset_id, artifact_name)
        parquet = _require_parquet()
        parquet_file = parquet.ParquetFile(path)
        for batch in parquet_file.iter_batches(batch_size=limit):
            records = batch.slice(0, limit).to_pylist()
            return _jsonable(records)
        return []


def _jsonable(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert non-JSON primitives (dates etc.) to strings for safe transport."""

    cleaned: list[dict[str, Any]] = []
    for record in records:
        row: dict[str, Any] = {}
        for key, value in record.items():
            if value is None or isinstance(value, (str, int, float, bool)):
                row[key] = value
            else:
                row[key] = str(value)
        cleaned.append(row)
    return cleaned
