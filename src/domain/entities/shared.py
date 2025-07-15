"""Shared utilities and helper functions for domain entities.

Pure utility functions with zero external dependencies.
"""

from datetime import UTC, datetime


def ensure_utc(dt: datetime | None) -> datetime | None:
    """Ensure datetime is timezone-aware with UTC."""
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt