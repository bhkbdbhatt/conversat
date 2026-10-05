"""Exception hierarchy shared by every conversat subsystem."""

from __future__ import annotations

from typing import Any


class ConversatError(Exception):
    """Base class for every error raised by conversat."""


class ConfigError(ConversatError):
    """Raised when a suite/connector/assertion definition is invalid."""


class SuiteParseError(ConfigError):
    """Raised when a YAML suite cannot be read or does not validate."""

    def __init__(self, message: str, *, path: str | None = None, location: str | None = None):
        self.path = path
        self.location = location
        detail = message
        if path:
            detail = f"{path}: {detail}"
        if location:
            detail = f"{detail} (at {location})"
        super().__init__(detail)
        self.message = message


class ConnectorError(ConversatError):
    """Raised when a connector cannot be created or fails to talk to the bot."""

    def __init__(self, message: str, *, connector: str | None = None, cause: Any = None):
        self.connector = connector
        self.cause = cause
        prefix = f"[{connector}] " if connector else ""
        super().__init__(f"{prefix}{message}")


class ConnectorTimeoutError(ConnectorError):
    """Raised when a turn does not complete within the configured timeout."""


class AssertionError_(ConversatError):
    """Raised when assertion evaluation itself blows up (not when it fails)."""

    def __init__(self, message: str, *, strategy: str | None = None):
        self.strategy = strategy
        prefix = f"[{strategy}] " if strategy else ""
        super().__init__(f"{prefix}{message}")


class CrawlError(ConversatError):
    """Raised when the crawler cannot start or overruns its budget."""


class RegistryError(ConversatError):
    """Raised for unknown connector/assertion/formatter names."""
