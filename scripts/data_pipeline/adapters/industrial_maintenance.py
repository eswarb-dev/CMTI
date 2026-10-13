from __future__ import annotations

import polars as pl

from ..base import Artifact, DatasetAdapter
from ..common import null_count_by_column, value_counts_dict, write_parquet
from ..provenance import add_provenance
from ..validators import assert_columns


MAINTENANCE_COLUMNS = [
    "Location (building number)",
    "Region",
    "WorkOrder",
    "Equipment_ID",
    "OrderType",
    "WorkOrderDescription",
    "OperationDescription",
    "MaintenanceWorkCenter",
    "OperationWorkCenter",
    "Maintenance_activity_type",
    "CreatedDate",
    "ScheduledStartDate",
    "ScheduledFinishDate",
    "ActualStartDate",
    "ActualFinishDate",
    "TechnicalCompletionDate",
    "CloseData",
    "ActualWork",
    "PlannedWork",
    "OrderStatus",
]

TAG_COLUMNS = [
    "Tag_name",
    "Server_name",
    "Description",
    "Units",
    "Building",
    "Production_line",
    "Equipment_ID",
    "Equipment_type",
    "Variable_type",
]

DATE_FIELDS = {
    "CreatedDate": "created_date",
    "ScheduledStartDate": "scheduled_start_date",
    "ScheduledFinishDate": "scheduled_finish_date",
    "ActualStartDate": "actual_start_date",
    "ActualFinishDate": "actual_finish_date",
    "TechnicalCompletionDate": "technical_completion_date",
    "CloseData": "close_date",
}


class IndustrialMaintenanceAdapter(DatasetAdapter):
    dataset_id = "kaggle_industrial_maintenance_synthetic"
    canonical_name = "industrial_maintenance"
    adapter_name = "IndustrialMaintenanceAdapter"
    domain = ["maintenance", "work_orders", "equipment_metadata", "sensor_tag_catalog"]

    def inspect_source(self) -> dict[str, object]:
        return {
            "maintenance": pl.read_csv(self.raw_dir / "maintenance.csv", n_rows=0).columns,
            "sensor_tags": pl.read_csv(self.raw_dir / "sensor_tags.csv", n_rows=0).columns,
        }

    def validate_source(self) -> None:
        assert_columns(self.raw_dir / "maintenance.csv", MAINTENANCE_COLUMNS)
        assert_columns(self.raw_dir / "sensor_tags.csv", TAG_COLUMNS)

    @staticmethod
    def _date_expr(source: str, target: str) -> list[pl.Expr]:
        parsed = pl.col(source).str.strptime(pl.Date, "%Y-%m-%d", strict=False)
        return [
            pl.col(source).alias(f"{target}_raw"),
            parsed.alias(target),
            (pl.col(source).is_null() | parsed.is_not_null()).alias(f"{target}_valid"),
        ]

    def _normalize_maintenance(self) -> tuple[pl.DataFrame, dict[str, int], dict[str, int]]:
        raw = pl.read_csv(self.raw_dir / "maintenance.csv", infer_schema_length=2000).with_row_index(
            "source_row_number", offset=2
        )
        date_exprs: list[pl.Expr] = []
        for source, target in DATE_FIELDS.items():
            date_exprs.extend(self._date_expr(source, target))
        output = raw.select(
            [
                pl.col("source_row_number"),
                pl.col("Location (building number)").alias("location_building_number"),
                pl.col("Region").alias("region"),
                pl.col("WorkOrder").alias("work_order"),
                pl.col("Equipment_ID").alias("equipment_id"),
                pl.col("OrderType").alias("order_type"),
                pl.col("WorkOrderDescription").alias("work_order_description"),
                pl.col("OperationDescription").alias("operation_description"),
                pl.col("MaintenanceWorkCenter").alias("maintenance_work_center"),
                pl.col("OperationWorkCenter").alias("operation_work_center"),
                pl.col("Maintenance_activity_type").alias("maintenance_activity_type"),
                *date_exprs,
                pl.col("ActualWork").alias("actual_work_raw"),
                pl.col("ActualWork").cast(pl.Float64, strict=False).alias("actual_work_numeric"),
                pl.col("PlannedWork").alias("planned_work_raw"),
                pl.col("PlannedWork").cast(pl.Float64, strict=False).alias("planned_work_numeric"),
                pl.col("OrderStatus").alias("order_status"),
            ]
        )
        duplicate_flags = raw.select(
            pl.struct([column for column in raw.columns if column != "source_row_number"]).is_duplicated().alias("is_dup")
        )["is_dup"]
        output = output.with_columns(pl.Series("is_exact_duplicate", duplicate_flags))
        output = add_provenance(
            output,
            dataset_id=self.dataset_id,
            source_file="maintenance.csv",
            source_domain="maintenance.work_orders",
        )
        invalid_dates = {
            f"{target}_invalid_count": int(
                output.filter(pl.col(f"{target}_raw").is_not_null() & ~pl.col(f"{target}_valid")).height
            )
            for target in DATE_FIELDS.values()
        }
        numeric_failures = {
            "actual_work_numeric_parse_failures": int(
                output.filter(pl.col("actual_work_raw").is_not_null() & pl.col("actual_work_numeric").is_null()).height
            ),
            "planned_work_numeric_parse_failures": int(
                output.filter(pl.col("planned_work_raw").is_not_null() & pl.col("planned_work_numeric").is_null()).height
            ),
        }
        return output, invalid_dates, numeric_failures

    def _normalize_tags(self) -> pl.DataFrame:
        raw = pl.read_csv(self.raw_dir / "sensor_tags.csv", infer_schema_length=2000).with_row_index(
            "source_row_number", offset=2
        )
        output = raw.select(
            [
                pl.col("source_row_number"),
                pl.col("Tag_name").alias("tag_name"),
                pl.col("Server_name").alias("server_name"),
                pl.col("Description").alias("description"),
                pl.col("Units").alias("units"),
                pl.col("Building").alias("building"),
                pl.col("Production_line").alias("production_line"),
                pl.col("Equipment_ID").alias("equipment_id"),
                pl.col("Equipment_type").alias("equipment_type"),
                pl.col("Variable_type").alias("variable_type"),
            ]
        )
        duplicate_flags = raw.select(
            pl.struct([column for column in raw.columns if column != "source_row_number"]).is_duplicated().alias("is_dup")
        )["is_dup"]
        output = output.with_columns(pl.Series("is_exact_duplicate", duplicate_flags))
        return add_provenance(
            output,
            dataset_id=self.dataset_id,
            source_file="sensor_tags.csv",
            source_domain="equipment_metadata.sensor_tag_catalog",
        )

    @staticmethod
    def _equipment_overlap(maintenance: pl.DataFrame, tags: pl.DataFrame) -> dict[str, int]:
        maintenance_ids = set(maintenance["equipment_id"].drop_nulls().to_list())
        tag_ids = set(tags["equipment_id"].drop_nulls().to_list())
        return {
            "maintenance_distinct_equipment_ids": len(maintenance_ids),
            "sensor_tag_distinct_equipment_ids": len(tag_ids),
            "intersection_count": len(maintenance_ids & tag_ids),
            "maintenance_only_equipment_count": len(maintenance_ids - tag_ids),
            "sensor_tag_only_equipment_count": len(tag_ids - maintenance_ids),
        }

    def normalize(self) -> list[Artifact]:
        maintenance, invalid_dates, numeric_failures = self._normalize_maintenance()
        tags = self._normalize_tags()
        maintenance_path = self.output_dir / "maintenance_work_orders.parquet"
        tags_path = self.output_dir / "sensor_tag_catalog.parquet"
        write_parquet(maintenance, maintenance_path)
        write_parquet(tags, tags_path)
        overlap = self._equipment_overlap(maintenance, tags)
        maintenance_artifact = Artifact(
            artifact_name="maintenance_work_orders",
            path=maintenance_path,
            domain=["maintenance", "work_orders", "equipment_history"],
            rows=maintenance.height,
            columns=len(maintenance.columns),
            source_files=["maintenance.csv"],
            input_rows=maintenance.height,
            input_columns=len(MAINTENANCE_COLUMNS),
            invalid_values={**invalid_dates, **numeric_failures},
            warnings=["Malformed dates are preserved as raw text with parsed nulls and valid=false."],
            null_statistics=null_count_by_column(maintenance),
            duplicate_statistics={
                "exact_duplicate_rows": int(maintenance["is_exact_duplicate"].sum()),
                "missing_equipment_id_count": int(maintenance["equipment_id"].null_count()),
                "work_order_unique_count": int(maintenance["work_order"].n_unique()),
                "equipment_id_unique_count": int(maintenance["equipment_id"].n_unique()),
                **overlap,
            },
            derived_columns={
                "date_valid_fields": "True when source date is null or parses as yyyy-mm-dd; false for malformed non-null source dates.",
                "actual_work_numeric": "Numeric parse of ActualWork with raw value preserved.",
                "planned_work_numeric": "Numeric parse of PlannedWork with raw value preserved.",
                "is_exact_duplicate": "Exact source-row duplicate flag; rows are not removed.",
            },
        )
        tags_artifact = Artifact(
            artifact_name="sensor_tag_catalog",
            path=tags_path,
            domain=["equipment_metadata", "sensor_tag_catalog", "industrial_asset_context"],
            rows=tags.height,
            columns=len(tags.columns),
            source_files=["sensor_tags.csv"],
            input_rows=tags.height,
            input_columns=len(TAG_COLUMNS),
            invalid_values={"classification": "sensor_tags.csv is catalog metadata, not telemetry measurements"},
            warnings=["No timestamp or measurement value exists in sensor_tags.csv; no telemetry was fabricated."],
            null_statistics=null_count_by_column(tags),
            duplicate_statistics={
                "exact_duplicate_rows": int(tags["is_exact_duplicate"].sum()),
                "equipment_id_unique_count": int(tags["equipment_id"].n_unique()),
                **overlap,
            },
        )
        return [maintenance_artifact, tags_artifact]

