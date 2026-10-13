from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any


SECRET_TOKENS = ("api_key", "authorization", "token", "secret", "password")


def redact_mapping(values: Mapping[str, Any]) -> dict[str, Any]:
    """Return a shallow copy with obvious secret-bearing keys redacted."""

    redacted: dict[str, Any] = {}
    for key, value in values.items():
        if any(token in key.lower() for token in SECRET_TOKENS):
            redacted[key] = "[REDACTED]"
        else:
            redacted[key] = value
    return redacted


def configure_logging(level: str = "INFO") -> None:
    """Configure minimal application logging."""

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

