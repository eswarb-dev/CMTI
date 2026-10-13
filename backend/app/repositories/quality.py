"""Read-only repository for quality inspections and deterministic summaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from app.db.models import QualityRecord
from app.repositories.base import DEFAULT_LIMIT, BaseRepository

_TABLE = "quality_inspections"


@dataclass(slots=True)
class ParameterSummary:
    """Deterministic per-measurement-parameter statistics."""

    parameter: str | None
    inspection_count: int
    pass_count: int
    fail_count: int
    failure_rate: float | None
    min_measurement: float | None
    max_measurement: float | None
    mean_measurement: float | None


@dataclass(slots=True)
class QualitySummary:
    """Aggregate inspection outcomes; parameters are never mixed in one mean."""

    inspection_count: int
    pass_count: int
    fail_count: int
    failure_rate: float | None
    min_measurement: float | None = None
    max_measurement: float | None = None
    mean_measurement: float | None = None
    parameters: list[ParameterSummary] = field(default_factory=list)


class QualityRepository(BaseRepository):
    """Async access to quality inspections.

    Time-filtered methods use ``timestamp`` and return records in DESCENDING
    order (most recent first) with ``inspection_id`` DESC as tie-breaker.
    """

    async def get_by_id(self, inspection_id: str) -> QualityRecord | None:
        row = await self._fetch_one(
            f"SELECT * FROM {_TABLE} WHERE inspection_id = ?", (inspection_id,)
        )
        return QualityRecord.from_row(row) if row else None

    async def list_by_machine(
        self,
        machine_id: str,
        start_time: datetime | date | str | None = None,
        end_time: datetime | date | str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> list[QualityRecord]:
        parameters: list[object] = [machine_id]
        clause = self._time_range("timestamp", start_time, end_time, parameters)
        rows = await self._fetch_all(
            f"SELECT * FROM {_TABLE} WHERE machine_id = ?{clause} "
            "ORDER BY timestamp DESC, inspection_id DESC LIMIT ?",
            (*parameters, self._bounded_limit(limit)),
        )
        return [QualityRecord.from_row(row) for row in rows]

    async def list_by_product(
        self,
        product_id: str,
        start_time: datetime | date | str | None = None,
        end_time: datetime | date | str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> list[QualityRecord]:
        parameters: list[object] = [product_id]
        clause = self._time_range("timestamp", start_time, end_time, parameters)
        rows = await self._fetch_all(
            f"SELECT * FROM {_TABLE} WHERE product_id = ?{clause} "
            "ORDER BY timestamp DESC, inspection_id DESC LIMIT ?",
            (*parameters, self._bounded_limit(limit)),
        )
        return [QualityRecord.from_row(row) for row in rows]

    async def list_by_batch(
        self, batch_id: str, limit: int = DEFAULT_LIMIT
    ) -> list[QualityRecord]:
        rows = await self._fetch_all(
            f"SELECT * FROM {_TABLE} WHERE batch_id = ? "
            "ORDER BY timestamp DESC, inspection_id DESC LIMIT ?",
            (batch_id, self._bounded_limit(limit)),
        )
        return [QualityRecord.from_row(row) for row in rows]

    async def list_by_machine_and_time_range(
        self,
        machine_id: str,
        start_time: datetime | date | str | None = None,
        end_time: datetime | date | str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> list[QualityRecord]:
        return await self.list_by_machine(machine_id, start_time, end_time, limit)

    async def list_failures(
        self,
        machine_id: str | None = None,
        product_id: str | None = None,
        batch_id: str | None = None,
        parameter: str | None = None,
        start_time: datetime | date | str | None = None,
        end_time: datetime | date | str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> list[QualityRecord]:
        """Inspections whose recorded result is FAIL (newest first)."""

        parameters: list[object] = []
        where = " WHERE result = 'FAIL'"
        where += self._optional_filter("machine_id", machine_id, parameters)
        where += self._optional_filter("product_id", product_id, parameters)
        where += self._optional_filter("batch_id", batch_id, parameters)
        where += self._optional_filter("parameter", parameter, parameters)
        where += self._time_range("timestamp", start_time, end_time, parameters)
        rows = await self._fetch_all(
            f"SELECT * FROM {_TABLE}{where} "
            "ORDER BY timestamp DESC, inspection_id DESC LIMIT ?",
            (*parameters, self._bounded_limit(limit)),
        )
        return [QualityRecord.from_row(row) for row in rows]

    async def summarize_results(
        self,
        machine_id: str | None = None,
        product_id: str | None = None,
        batch_id: str | None = None,
        parameter: str | None = None,
        start_time: datetime | date | str | None = None,
        end_time: datetime | date | str | None = None,
    ) -> QualitySummary:
        """Deterministic pass/fail and measurement statistics.

        Statistics are grouped per measurement parameter; unrelated parameters
        are never averaged together.  The top-level min/max/mean are only
        populated when exactly one parameter is involved.
        """

        parameters: list[object] = []
        where = " WHERE 1 = 1"
        where += self._optional_filter("machine_id", machine_id, parameters)
        where += self._optional_filter("product_id", product_id, parameters)
        where += self._optional_filter("batch_id", batch_id, parameters)
        where += self._optional_filter("parameter", parameter, parameters)
        where += self._time_range("timestamp", start_time, end_time, parameters)

        rows = await self._fetch_all(
            f"""
            SELECT parameter,
                   COUNT(*) AS inspection_count,
                   SUM(CASE WHEN UPPER(result) = 'PASS' THEN 1 ELSE 0 END) AS pass_count,
                   SUM(CASE WHEN UPPER(result) = 'FAIL' THEN 1 ELSE 0 END) AS fail_count,
                   MIN(measured_value) AS min_measurement,
                   MAX(measured_value) AS max_measurement,
                   AVG(measured_value) AS mean_measurement
            FROM {_TABLE}{where}
            GROUP BY parameter
            ORDER BY parameter ASC
            """,
            tuple(parameters),
        )

        summaries: list[ParameterSummary] = []
        inspection_count = 0
        pass_count = 0
        fail_count = 0
        for row in rows:
            count = int(row["inspection_count"])
            passed = int(row["pass_count"] or 0)
            failed = int(row["fail_count"] or 0)
            inspection_count += count
            pass_count += passed
            fail_count += failed
            summaries.append(
                ParameterSummary(
                    parameter=row["parameter"],
                    inspection_count=count,
                    pass_count=passed,
                    fail_count=failed,
                    failure_rate=(failed / count) if count else None,
                    min_measurement=row["min_measurement"],
                    max_measurement=row["max_measurement"],
                    mean_measurement=row["mean_measurement"],
                )
            )

        failure_rate = (fail_count / inspection_count) if inspection_count else None
        summary = QualitySummary(
            inspection_count=inspection_count,
            pass_count=pass_count,
            fail_count=fail_count,
            failure_rate=failure_rate,
            parameters=summaries,
        )
        if len(summaries) == 1:
            only = summaries[0]
            summary.min_measurement = only.min_measurement
            summary.max_measurement = only.max_measurement
            summary.mean_measurement = only.mean_measurement
        return summary
