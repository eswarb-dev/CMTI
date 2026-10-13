"""Read-only repository for machine telemetry."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from app.db.models import TelemetryRecord
from app.repositories.base import DEFAULT_LIMIT, BaseRepository

_TABLE = "telemetry"
DEFAULT_TELEMETRY_LIMIT = 500

METRIC_COLUMNS: tuple[str, ...] = (
    "rpm",
    "vibration_mm_s",
    "temperature_c",
    "current_a",
    "load_pct",
    "spindle_power_kw",
)


@dataclass(slots=True)
class MetricStats:
    """Deterministic aggregate for one telemetry metric (no interpretation)."""

    count: int
    min: float | None
    max: float | None
    mean: float | None
    first: float | None = None
    last: float | None = None


@dataclass(slots=True)
class TelemetrySummary:
    """Summary of telemetry samples inside a time window."""

    machine_id: str
    start_time: str | None
    end_time: str | None
    sample_count: int
    metrics: dict[str, MetricStats] = field(default_factory=dict)


class TelemetryRepository(BaseRepository):
    """Async access to telemetry samples.

    Time-filtered methods use ``timestamp`` and return records in ASCENDING
    order (oldest first) for time-series consumption, with ``telemetry_id``
    ASC as tie-breaker; :meth:`latest_for_machine` is the exception and
    returns the single newest sample.
    """

    async def get_by_id(self, telemetry_id: str) -> TelemetryRecord | None:
        row = await self._fetch_one(
            f"SELECT * FROM {_TABLE} WHERE telemetry_id = ?", (telemetry_id,)
        )
        return TelemetryRecord.from_row(row) if row else None

    async def list_by_machine_and_time_range(
        self,
        machine_id: str,
        start_time: datetime | date | str | None = None,
        end_time: datetime | date | str | None = None,
        limit: int = DEFAULT_TELEMETRY_LIMIT,
    ) -> list[TelemetryRecord]:
        parameters: list[object] = [machine_id]
        clause = self._time_range("timestamp", start_time, end_time, parameters)
        rows = await self._fetch_all(
            f"SELECT * FROM {_TABLE} WHERE machine_id = ?{clause} "
            "ORDER BY timestamp ASC, telemetry_id ASC LIMIT ?",
            (*parameters, self._bounded_limit(limit, default=DEFAULT_TELEMETRY_LIMIT)),
        )
        return [TelemetryRecord.from_row(row) for row in rows]

    async def latest_for_machine(self, machine_id: str) -> TelemetryRecord | None:
        """Newest telemetry sample for a machine (``None`` when absent)."""

        row = await self._fetch_one(
            f"SELECT * FROM {_TABLE} WHERE machine_id = ? "
            "ORDER BY timestamp DESC, telemetry_id DESC LIMIT 1",
            (machine_id,),
        )
        return TelemetryRecord.from_row(row) if row else None

    async def summarize(
        self,
        machine_id: str,
        start_time: datetime | date | str | None = None,
        end_time: datetime | date | str | None = None,
    ) -> TelemetrySummary:
        """Count/min/max/mean/first/last for every present metric column."""

        parameters: list[object] = [machine_id]
        clause = self._time_range("timestamp", start_time, end_time, parameters)

        info_rows = await self._fetch_all("SELECT name FROM pragma_table_info(?)", (_TABLE,))
        present_columns = {row["name"] for row in info_rows}
        metrics = [name for name in METRIC_COLUMNS if name in present_columns]

        aggregates = ", ".join(
            f"COUNT({name}) AS {name}_count, MIN({name}) AS {name}_min, "
            f"MAX({name}) AS {name}_max, AVG({name}) AS {name}_mean"
            for name in metrics
        )
        select_list = ", ".join(metrics) if metrics else "telemetry_id"
        row = await self._fetch_one(
            f"SELECT COUNT(*) AS sample_count{', ' + aggregates if aggregates else ''} "
            f"FROM {_TABLE} WHERE machine_id = ?{clause}",
            tuple(parameters),
        )
        sample_count = int(row["sample_count"]) if row else 0

        first_row = await self._fetch_one(
            f"SELECT {select_list} FROM {_TABLE} WHERE machine_id = ?{clause} "
            "ORDER BY timestamp ASC, telemetry_id ASC LIMIT 1",
            tuple(parameters),
        )
        last_row = await self._fetch_one(
            f"SELECT {select_list} FROM {_TABLE} WHERE machine_id = ?{clause} "
            "ORDER BY timestamp DESC, telemetry_id DESC LIMIT 1",
            tuple(parameters),
        )

        metric_stats: dict[str, MetricStats] = {}
        for name in metrics:
            metric_stats[name] = MetricStats(
                count=int(row[f"{name}_count"]) if row else 0,
                min=row[f"{name}_min"] if row else None,
                max=row[f"{name}_max"] if row else None,
                mean=row[f"{name}_mean"] if row else None,
                first=first_row[name] if first_row else None,
                last=last_row[name] if last_row else None,
            )

        return TelemetrySummary(
            machine_id=machine_id,
            start_time=self._timestamp_text(start_time),
            end_time=self._timestamp_text(end_time),
            sample_count=sample_count,
            metrics=metric_stats,
        )
