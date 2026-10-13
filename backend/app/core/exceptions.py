from __future__ import annotations


class ManufacturaIQError(Exception):
    """Base exception for ManufacturaIQ backend errors."""


class ConfigurationError(ManufacturaIQError):
    """Configuration is invalid or incomplete."""


class ContractValidationError(ManufacturaIQError):
    """Shared contract validation failed."""


class ProviderUnavailableError(ManufacturaIQError):
    """A future external provider is unavailable."""


class RetrievalError(ManufacturaIQError):
    """Future retrieval operation failed."""


class AgentExecutionError(ManufacturaIQError):
    """Future agent execution failed."""


class DatabaseError(ManufacturaIQError):
    """Operational database access failed."""


class DatabaseInitializationError(DatabaseError):
    """Database initialization/import failed and was rolled back."""


class DatabaseValidationError(DatabaseError):
    """Database validation found blocking violations."""


class RepositoryError(DatabaseError):
    """A repository operation failed."""


class SqlSafetyError(ManufacturaIQError):
    """A SQL statement rejected by the read-only safety validator."""

