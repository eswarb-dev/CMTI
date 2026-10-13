from __future__ import annotations

from enum import StrEnum


class Domain(StrEnum):
    DOCUMENTATION = "DOCUMENTATION"
    MAINTENANCE = "MAINTENANCE"
    QUALITY = "QUALITY"
    PRODUCTION = "PRODUCTION"
    MULTI_DOMAIN = "MULTI_DOMAIN"
    UNKNOWN = "UNKNOWN"


class AgentName(StrEnum):
    DOCUMENT = "DOCUMENT"
    MAINTENANCE = "MAINTENANCE"
    QUALITY = "QUALITY"
    PRODUCTION = "PRODUCTION"


class EvidenceSourceType(StrEnum):
    MANUAL = "MANUAL"
    SOP = "SOP"
    SAFETY = "SAFETY"
    MAINTENANCE = "MAINTENANCE"
    QUALITY = "QUALITY"
    PRODUCTION = "PRODUCTION"
    TELEMETRY = "TELEMETRY"
    ALARM = "ALARM"
    EXTERNAL_DATASET = "EXTERNAL_DATASET"


class SourceKind(StrEnum):
    DOCUMENT = "DOCUMENT"
    DEMO_FACTORY = "DEMO_FACTORY"
    EXTERNAL_DATASET = "EXTERNAL_DATASET"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ReviewAction(StrEnum):
    PASS = "PASS"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class ProviderStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FALLBACK = "FALLBACK"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"

