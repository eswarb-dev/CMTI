from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ApiDocumentContext(BaseModel):
    """Bounded document-routing context accepted from HTTP clients."""

    model_config = ConfigDict(extra="forbid")

    document_type: str | None = None
    manufacturer: str | None = None
    machine_family: str | None = None
    model: str | None = None
    document_id: str | None = None
    language: str | None = None

    def to_user_context(self) -> dict[str, str]:
        return {
            key: value
            for key, value in self.model_dump().items()
            if isinstance(value, str) and value.strip()
        }


class ApiQueryRequest(BaseModel):
    """Public HTTP query schema for STEP 16."""

    model_config = ConfigDict(extra="forbid")

    query: str
    machine_id: str | None = None
    product_id: str | None = None
    batch_id: str | None = None
    time_start: datetime | None = None
    time_end: datetime | None = None
    document_context: ApiDocumentContext | None = None

    @field_validator("query")
    @classmethod
    def query_must_not_be_empty(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("query must not be empty")
        return trimmed

    @model_validator(mode="after")
    def validate_time_range(self) -> "ApiQueryRequest":
        if self.time_start and self.time_end and self.time_start > self.time_end:
            raise ValueError("time_start must be before or equal to time_end")
        return self


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: Literal["manufacturaiq"]


class ReadyResponse(BaseModel):
    status: Literal["ready"]
    service: Literal["manufacturaiq"]
    orchestrator: Literal["available"]


class ApiErrorResponse(BaseModel):
    error: str


class AuthLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    password: str

    @field_validator("username", "password")
    @classmethod
    def auth_field_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("field must not be empty")
        return value


class AuthUserResponse(BaseModel):
    id: str
    username: str
    display_name: str
    role: str


class AuthLoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"]
    user: AuthUserResponse


ALLOWED_REGISTER_ROLES = {
    "Manufacturing Engineer",
    "Quality Engineer",
    "Maintenance Engineer",
    "Production Engineer",
    "Engineer",
    "Student / Researcher",
}
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")


class AuthRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    display_name: str
    role: str
    password: str

    @field_validator("username")
    @classmethod
    def username_is_valid(cls, value: str) -> str:
        trimmed = value.strip()
        if not USERNAME_PATTERN.fullmatch(trimmed):
            raise ValueError("username must be 3-32 characters using letters, numbers, underscore, dot, or hyphen")
        return trimmed

    @field_validator("display_name")
    @classmethod
    def display_name_is_valid(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("display name must not be empty")
        return trimmed

    @field_validator("role")
    @classmethod
    def role_is_allowed(cls, value: str) -> str:
        trimmed = value.strip()
        if trimmed not in ALLOWED_REGISTER_ROLES:
            raise ValueError("role is not supported for self-registration")
        return trimmed

    @field_validator("password")
    @classmethod
    def password_is_valid(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("password must be at least 8 characters")
        return value


class ApiQueryResponse(BaseModel):
    query_id: str
    status: Literal["needs_clarification", "pass", "human_review"]
    routing: dict[str, Any]
    evidence: dict[str, Any] | None = None
    reasoning: dict[str, Any] | None = None
    review: dict[str, Any] | None = None


class DocumentResponse(BaseModel):
    """Safe public representation of one dynamic user document."""

    document_id: str
    original_filename: str
    mime_type: str
    file_size_bytes: int
    status: Literal["PENDING", "PROCESSING", "READY", "FAILED"]
    page_count: int = 0
    chunk_count: int = 0
    created_at: str = ""
    updated_at: str = ""
    error_code: str | None = None
    error_message: str | None = None


class DocumentUploadResponse(DocumentResponse):
    duplicate: bool = False


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
    count: int


class DocumentDeleteResponse(BaseModel):
    document_id: str
    deleted: bool

