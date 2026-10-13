from __future__ import annotations

import re

import polars as pl

from ..base import Artifact, DatasetAdapter
from ..common import null_count_by_column, value_counts_dict, write_parquet
from ..provenance import add_provenance
from ..validators import assert_columns


TRAIN_COLUMNS = [
    "No",
    "material",
    "feedrate",
    "clamp_pressure",
    "tool_condition",
    "machining_finalized",
    "passed_visual_inspection",
]


class CNCToolWearAdapter(DatasetAdapter):
    dataset_id = "kaggle_cnc_mill_tool_wear"
    canonical_name = "cnc_tool_wear"
    adapter_name = "CNCToolWearAdapter"
    domain = ["maintenance", "production", "telemetry_like_ordered_samples"]

    def experiment_files(self) -> list[str]:
        return sorted(path.name for path in self.raw_dir.glob("experiment_*.csv"))

    def read_experiment_csv(self, file_name: str) -> pl.DataFrame:
        path = self.raw_dir / file_name
        sample = path.read_bytes()[:4096]
        eol_char = "\r" if b"\r" in sample and b"\n" not in sample else "\n"
        return pl.read_csv(path, eol_char=eol_char)

    @staticmethod
    def experiment_id(file_name: str) -> int:
        match = re.search(r"experiment_(\d+)\.csv$", file_name)
        if not match:
            raise ValueError(f"Cannot derive experiment_id from {file_name}")
        return int(match.group(1))

    def inspect_source(self) -> dict[str, object]:
        return {"experiment_files": self.experiment_files(), "train": "train.csv"}

    def validate_source(self) -> None:
        assert_columns(self.raw_dir / "train.csv", TRAIN_COLUMNS)
        ids_from_files = {self.experiment_id(name) for name in self.experiment_files()}
        train_ids = set(pl.read_csv(self.raw_dir / "train.csv")["No"].cast(pl.Int64).to_list())
        if ids_from_files != train_ids:
            raise ValueError(f"CNC experiment/train mapping mismatch: files={ids_from_files}, train={train_ids}")

    def normalize(self) -> list[Artifact]:
        train = pl.read_csv(self.raw_dir / "train.csv").with_row_index("source_row_number", offset=2)
        metadata = train.rename({"No": "experiment_id"})
        metadata = add_provenance(
            metadata,
            dataset_id=self.dataset_id,
            source_file="train.csv",
            source_domain="production.experiment_metadata",
        )
        metadata_path = self.output_dir / "experiment_metadata.parquet"
        write_parquet(metadata, metadata_path)

        sample_frames: list[pl.DataFrame] = []
        duplicate_by_experiment: dict[str, int] = {}
        rows_by_experiment: dict[str, int] = {}
        process_distribution: dict[str, int] = {}
        for file_name in self.experiment_files():
            experiment_id = self.experiment_id(file_name)
            raw = self.read_experiment_csv(file_name).with_row_index("source_row_number", offset=2)
            measurement_columns = [column for column in raw.columns if column != "source_row_number"]
            duplicate_flags = raw.select(pl.struct(measurement_columns).is_duplicated().alias("is_dup"))[
                "is_dup"
            ]
            duplicate_by_experiment[str(experiment_id)] = int(duplicate_flags.sum())
            rows_by_experiment[str(experiment_id)] = raw.height
            sample = raw.with_columns(
                [
                    pl.lit(experiment_id).alias("experiment_id"),
                    (pl.col("source_row_number") - 2).alias("sample_index"),
                    pl.Series("is_exact_duplicate", duplicate_flags),
                ]
            )
            sample = add_provenance(
                sample,
                dataset_id=self.dataset_id,
                source_file=file_name,
                source_domain="production.ordered_experiment_samples",
            )
            sample_frames.append(sample)
        samples = pl.concat(sample_frames, how="vertical")
        process_distribution = value_counts_dict(samples, "Machining_Process")
        samples_path = self.output_dir / "experiment_samples.parquet"
        write_parquet(samples, samples_path)

        artifacts = [
            Artifact(
                artifact_name="experiment_metadata",
                path=metadata_path,
                domain=["maintenance", "production"],
                rows=metadata.height,
                columns=len(metadata.columns),
                source_files=["train.csv"],
                input_rows=train.height,
                input_columns=len(train.columns) - 1,
                null_statistics=null_count_by_column(metadata),
                duplicate_statistics={"source_duplicate_rows": int(train.drop("source_row_number").is_duplicated().sum())},
                invalid_values={
                    "mapping_validation": "train.csv No values match experiment_NN.csv file ids",
                    "tool_condition_distribution": value_counts_dict(metadata, "tool_condition"),
                    "machining_finalized_distribution": value_counts_dict(metadata, "machining_finalized"),
                    "passed_visual_inspection_null_count": int(metadata["passed_visual_inspection"].null_count()),
                },
            ),
            Artifact(
                artifact_name="experiment_samples",
                path=samples_path,
                domain=["production", "telemetry_like_ordered_samples"],
                rows=samples.height,
                columns=len(samples.columns),
                source_files=self.experiment_files(),
                input_rows=sum(rows_by_experiment.values()),
                input_columns=48,
                null_statistics=null_count_by_column(samples),
                duplicate_statistics={
                    "rows_per_experiment": rows_by_experiment,
                    "duplicate_rows_per_experiment": duplicate_by_experiment,
                    "total_duplicate_rows": sum(duplicate_by_experiment.values()),
                },
                derived_columns={
                    "experiment_id": "Derived from experiment_NN.csv filename after validating train.csv No mapping.",
                    "sample_index": "Derived from source row order; not a wall-clock timestamp.",
                    "is_exact_duplicate": "Flags exact duplicate measurement rows within each experiment file.",
                },
                invalid_values={"Machining_Process_distribution": process_distribution},
            ),
        ]
        return artifacts

