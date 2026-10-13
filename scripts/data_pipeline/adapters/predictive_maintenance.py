from __future__ import annotations

import polars as pl

from ..base import Artifact, DatasetAdapter
from ..common import null_count_by_column, value_counts_dict, write_parquet
from ..provenance import add_provenance
from ..validators import assert_columns


class PredictiveMaintenanceAdapter(DatasetAdapter):
    dataset_id = "kaggle_ai4i_predictive_maintenance"
    canonical_name = "predictive_maintenance"
    adapter_name = "PredictiveMaintenanceAdapter"
    domain = ["maintenance", "machine_condition", "telemetry_like_observations"]

    source_file = "predictive_maintenance.csv"
    expected_columns = [
        "UDI",
        "Product ID",
        "Type",
        "Air temperature [K]",
        "Process temperature [K]",
        "Rotational speed [rpm]",
        "Torque [Nm]",
        "Tool wear [min]",
        "Target",
        "Failure Type",
    ]

    def inspect_source(self) -> dict[str, object]:
        frame = pl.read_csv(self.raw_dir / self.source_file)
        return {"rows": frame.height, "columns": frame.columns}

    def validate_source(self) -> None:
        assert_columns(self.raw_dir / self.source_file, self.expected_columns)

    def normalize(self) -> list[Artifact]:
        frame = pl.read_csv(self.raw_dir / self.source_file).with_row_index("source_row_number", offset=2)
        output = frame.rename(
            {
                "UDI": "udi",
                "Product ID": "product_id",
                "Type": "product_type",
                "Air temperature [K]": "air_temperature_k",
                "Process temperature [K]": "process_temperature_k",
                "Rotational speed [rpm]": "rotational_speed_rpm",
                "Torque [Nm]": "torque_nm",
                "Tool wear [min]": "tool_wear_min",
                "Target": "failure_target",
                "Failure Type": "failure_type",
            }
        )
        output = add_provenance(
            output,
            dataset_id=self.dataset_id,
            source_file=self.source_file,
            source_domain="maintenance.machine_condition",
        )
        path = self.output_dir / "machine_condition_observations.parquet"
        write_parquet(output, path)
        artifact = Artifact(
            artifact_name="machine_condition_observations",
            path=path,
            domain=self.domain,
            rows=output.height,
            columns=len(output.columns),
            source_files=[self.source_file],
            input_rows=frame.height,
            input_columns=len(frame.columns) - 1,
            null_statistics=null_count_by_column(output),
            duplicate_statistics={"source_duplicate_rows": int(frame.drop("source_row_number").is_duplicated().sum())},
        )
        artifact.invalid_values = {
            "udi_unique": frame["UDI"].n_unique() == frame.height,
            "type_distribution": value_counts_dict(output, "product_type"),
            "target_distribution": value_counts_dict(output, "failure_target"),
            "failure_type_distribution": value_counts_dict(output, "failure_type"),
            "ranges": {
                column: {
                    "min": output[column].min(),
                    "max": output[column].max(),
                }
                for column in [
                    "air_temperature_k",
                    "process_temperature_k",
                    "rotational_speed_rpm",
                    "torque_nm",
                    "tool_wear_min",
                ]
            },
        }
        return [artifact]

