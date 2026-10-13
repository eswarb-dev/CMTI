from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, field_validator, model_validator

from .base import ContractModel


class QueryRequest(ContractModel):
    """User query plus optional structured filters."""

    query_id: str = Field(min_length=1)
    query: str
    machine_id: str | None = None
    product_id: str | None = None
    batch_id: str | None = None
    time_start: datetime | None = None
    time_end: datetime | None = None
    user_context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("query")
    @classmethod
    def query_must_not_be_empty(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("query must not be empty")
        return trimmed

    @field_validator("query_id")
    @classmethod
    def query_id_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query_id must not be empty")
        return value

    @model_validator(mode="after")
    def validate_time_range(self) -> "QueryRequest":
        if self.time_start and self.time_end and self.time_start > self.time_end:
            raise ValueError("time_start must be before or equal to time_end")
        return self

