"""Read-only repository for production orders and deterministic metrics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from app.db.models import ProductionRecord
from app.repositories.base import DEFAULT_LIMIT, BaseRepository

_TABLE = "production_orders"


@dataclass(slots=True)
class RejectionSummary:
    """Deterministic rejection totals (no model involved)."""

    order_count: int
    total_actual_quantity: int
    total_accepted_quantity: int
    total_rejected_quantity: int
    reject_rate: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "order_count": self.order_count,
            "total_actual_quantity": self.total_actual_quantity,
            "total_accepted_quantity": self.total_accepted_quantity,
            "total_rejected_quantity": self.total_rejected_quantity,
            "reject_rate": self.reject_rate,
        }


class ProductionRepository(BaseRepository):
    """Async access to production orders.

    Time-filtered methods use ``actual_start_time`` and return records in
    DESCENDING order (most recent first), with ``production_id`` DESC as a
    deterministic tie-breaker.
    """

    async def get_by_production_id(self, production_id: str) -> ProductionRecord | None:
        row = await self._fetch_one(
            f"SELECT * FROM {_TABLE} WHERE production_id = ?", (production_id,)
        )
        return ProductionRecord.from_row(row) if row else None

    async def get_by_batch_id(self, batch_id: str) -> ProductionRecord | None:
        row = await self._fetch_one(
            f"SELECT * FROM {_TABLE} WHERE batch_id = ?", (batch_id,)
        )
        return ProductionRecord.from_row(row) if row else None

    async def list_by_machine(
        self,
        machine_id: str,
        start_time: datetime | date | str | None = None,
        end_time: datetime | date | str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> list[ProductionRecord]:
        parameters: list[object] = [machine_id]
        clause = self._time_range("actual_start_time", start_time, end_time, parameters)
        rows = await self._fetch_all(
            f"SELECT * FROM {_TABLE} WHERE machine_id = ?{clause} "
            "ORDER BY actual_start_time DESC, production_id DESC LIMIT ?",
            (*parameters, self._bounded_limit(limit)),
        )
        return [ProductionRecord.from_row(row) for row in rows]

    async def list_by_product(
        self,
        product_id: str,
        start_time: datetime | date | str | None = None,
        end_time: datetime | date | str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> list[ProductionRecord]:
        parameters: list[object] = [product_id]
        clause = self._time_range("actual_start_time", start_time, end_time, parameters)
        rows = await self._fetch_all(
            f"SELECT * FROM {_TABLE} WHERE product_id = ?{clause} "
            "ORDER BY actual_start_time DESC, production_id DESC LIMIT ?",
            (*parameters, self._bounded_limit(limit)),
        )
        return [ProductionRecord.from_row(row) for row in rows]

    async def list_by_machine_and_product(
        self,
        machine_id: str,
        product_id: str,
        start_time: datetime | date | str | None = None,
        end_time: datetime | date | str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> list[ProductionRecord]:
        parameters: list[object] = [machine_id, product_id]
        clause = self._time_range("actual_start_time", start_time, end_time, parameters)
        rows = await self._fetch_all(
            f"SELECT * FROM {_TABLE} WHERE machine_id = ? AND product_id = ?{clause} "
            "ORDER BY actual_start_time DESC, production_id DESC LIMIT ?",
            (*parameters, self._bounded_limit(limit)),
        )
        return [ProductionRecord.from_row(row) for row in rows]

    async def summarize_rejections(
        self,
        machine_id: str | None = None,
        product_id: str | None = None,
        start_time: datetime | date | str | None = None,
        end_time: datetime | date | str | None = None,
    ) -> RejectionSummary:
        """Aggregate accepted/rejected quantities with SQL only.

        ``reject_rate`` is ``None`` (never infinity) when the denominator is 0.
        """

        parameters: list[object] = []
        where = " WHERE 1 = 1"
        where += self._optional_filter("machine_id", machine_id, parameters)
        where += self._optional_filter("product_id", product_id, parameters)
        where += self._time_range("actual_start_time", start_time, end_time, parameters)
        row = await self._fetch_one(
            f"""
            SELECT COUNT(*) AS order_count,
                   COALESCE(SUM(actual_quantity), 0) AS total_actual_quantity,
                   COALESCE(SUM(accepted_quantity), 0) AS total_accepted_quantity,
                   COALESCE(SUM(rejected_quantity), 0) AS total_rejected_quantity
            FROM {_TABLE}{where}
            """,
            tuple(parameters),
        )
        total_actual = int(row["total_actual_quantity"]) if row else 0
        total_rejected = int(row["total_rejected_quantity"]) if row else 0
        reject_rate = (total_rejected / total_actual) if total_actual else None
        return RejectionSummary(
            order_count=int(row["order_count"]) if row else 0,
            total_actual_quantity=total_actual,
            total_accepted_quantity=int(row["total_accepted_quantity"]) if row else 0,
            total_rejected_quantity=total_rejected,
            reject_rate=reject_rate,
        )
