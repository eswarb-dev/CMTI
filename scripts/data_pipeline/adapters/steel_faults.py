from __future__ import annotations

import polars as pl

from ..base import Artifact, DatasetAdapter
from ..common import normalize_name, null_count_by_column, value_counts_dict, write_parquet
from ..provenance import add_provenance
from ..validators import assert_columns


FAULT_COLUMNS = ["Pastry", "Z_Scratch", "K_Scatch", "Stains", "Dirtiness", "Bumps", "Other_Faults"]


class SteelFaultsAdapter(DatasetAdapter):
    dataset_id = "kaggle_faulty_steel_plates"
    canonical_name = "steel_faults"
    adapter_name = "SteelFaultsAdapter"
    domain = ["quality", "defect_analysis"]
    source_file = "faults.csv"

    def inspect_source(self) -> dict[str, object]:
        frame = pl.read_csv(self.raw_dir / self.source_file)
        return {"rows": frame.height, "columns": frame.columns}

    def validate_source(self) -> None:
        assert_columns(self.raw_dir / self.source_file, FAULT_COLUMNS)

    def normalize(self) -> list[Artifact]:
        source = pl.read_csv(self.raw_dir / self.source_file).with_row_index("source_row_number", offset=2)
        renamed = source.rename({column: normalize_name(column) for column in source.columns if column != "source_row_number"})
        fault_cols = [normalize_name(column) for column in FAULT_COLUMNS]
        labels = [normalize_name(column) for column in FAULT_COLUMNS]
        active_count = pl.sum_horizontal([pl.col(column).cast(pl.Int64) for column in fault_cols])
        fault_class_expr = pl.when(active_count == 1).then(
            pl.coalesce(
                [
                    pl.when(pl.col(column) == 1).then(pl.lit(label)).otherwise(None)
                    for column, label in zip(fault_cols, labels)
                ]
            )
        ).otherwise(None)
        status_expr = (
            pl.when(active_count == 0)
            .then(pl.lit("no_active_label"))
            .when(active_count > 1)
            .then(pl.lit("multiple_active_labels"))
            .otherwise(pl.lit("single_active_label"))
        )
        output = renamed.with_columns(
            [
                fault_class_expr.alias("fault_class"),
                status_expr.alias("fault_label_status"),
            ]
        )
        output = add_provenance(
            output,
            dataset_id=self.dataset_id,
            source_file=self.source_file,
            source_domain="quality.defect_analysis",
        )
        path = self.output_dir / "quality_fault_records.parquet"
        write_parquet(output, path)
        status_counts = value_counts_dict(output, "fault_label_status")
        artifact = Artifact(
            artifact_name="quality_fault_records",
            path=path,
            domain=self.domain,
            rows=output.height,
            columns=len(output.columns),
            source_files=[self.source_file],
            input_rows=source.height,
            input_columns=len(source.columns) - 1,
            null_statistics=null_count_by_column(output),
            duplicate_statistics={"source_duplicate_rows": int(source.drop("source_row_number").is_duplicated().sum())},
            derived_columns={
                "fault_class": "Derived only from the seven verified one-hot fault indicator columns.",
                "fault_label_status": "single_active_label, no_active_label, or multiple_active_labels.",
            },
            invalid_values={
                "single_active_label": status_counts.get("single_active_label", 0),
                "zero_active_label": status_counts.get("no_active_label", 0),
                "multiple_active_labels": status_counts.get("multiple_active_labels", 0),
                "fault_class_distribution": value_counts_dict(output, "fault_class"),
            },
        )
        return [artifact]

