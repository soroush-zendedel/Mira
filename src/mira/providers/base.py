"""Abstract base for repository providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class RepositoryProvider(ABC):
    """Common interface every provider must implement."""

    name: str = "base"

    @abstractmethod
    def list_mirrors(self, countries: list[str] | None = None) -> list[dict[str, Any]]:
        """Return mirror definitions for this provider."""
        ...

    @abstractmethod
    def check_mirror(self, mirror: dict[str, Any]) -> dict[str, Any]:
        """
        Perform protocol-aware health check.
        Must return dict with at least:
          available: bool
          valid: bool
          latency_ms: float | None
          error: str | None
        """
        ...

    @abstractmethod
    def get_current(self) -> dict[str, Any] | None:
        """Return currently configured mirror info, or None."""
        ...

    @abstractmethod
    def apply(self, mirror: dict[str, Any], *, dry_run: bool = False, **options: Any) -> dict[str, Any]:
        """
        Apply the selected mirror configuration.
        Must create backup, preserve unrelated settings.
        Returns a summary dict of what was done.
        """
        ...

    @abstractmethod
    def reset(self, *, dry_run: bool = False) -> dict[str, Any]:
        """Restore previous / default configuration."""
        ...