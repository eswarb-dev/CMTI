"""Read-only repository for the products table."""

from __future__ import annotations

from app.db.models import ProductRecord
from app.repositories.base import BaseRepository

_TABLE = "products"


class ProductRepository(BaseRepository):
    """Async access to product master data."""

    async def get_by_id(self, product_id: str) -> ProductRecord | None:
        row = await self._fetch_one(
            f"SELECT * FROM {_TABLE} WHERE product_id = ?", (product_id,)
        )
        return ProductRecord.from_row(row) if row else None

    async def list_all(self) -> list[ProductRecord]:
        """Return all products ordered by ``product_id`` ascending."""

        rows = await self._fetch_all(f"SELECT * FROM {_TABLE} ORDER BY product_id ASC")
        return [ProductRecord.from_row(row) for row in rows]

    async def exists(self, product_id: str) -> bool:
        row = await self._fetch_one(
            f"SELECT 1 FROM {_TABLE} WHERE product_id = ?", (product_id,)
        )
        return row is not None
