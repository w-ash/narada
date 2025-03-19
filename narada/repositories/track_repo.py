"""Track repository implementation for database operations.

This module provides a unified API for track operations by combining
functionality from the core track repository and sync repository.
"""

from collections.abc import Callable
from functools import wraps
import inspect
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from narada.repositories.track_core import TrackRepository
from narada.repositories.track_sync import TrackSyncRepository

T = TypeVar("T")
AsyncFunc = Callable[..., Any]  # Type for async functions


class RepositoryComposer:
    """Utility class for composing multiple repositories dynamically."""

    def __init__(
        self, repositories: dict[str, Any], name: str = "ComposedRepository"
    ) -> None:
        """Initialize with a dictionary of repositories.

        Args:
            repositories: Dictionary mapping namespace to repository instance
            name: Optional name for the composed repository
        """
        self._repositories = repositories
        self._name = name
        self._method_cache: dict[str, Callable] = {}
        self._namespace_methods: dict[str, set[str]] = {
            ns: self._get_public_methods(repo) for ns, repo in repositories.items()
        }

    @staticmethod
    def _get_public_methods(obj: Any) -> set[str]:
        """Get all public methods from an object."""
        return {
            name
            for name, _ in inspect.getmembers(obj, inspect.ismethod)
            if not name.startswith("_")
        }

    def __getattr__(self, name: str) -> Callable:
        """Dynamically dispatch method calls to the appropriate repository."""
        # Check cache first
        if name in self._method_cache:
            return self._method_cache[name]

        # Find which repository has this method
        for namespace, methods in self._namespace_methods.items():
            if name in methods:
                repo = self._repositories[namespace]
                method = getattr(repo, name)

                # Create a wrapper that preserves docstrings and type hints
                # Explicitly bind method to avoid late binding issues
                def create_wrapper(bound_method: Callable) -> Callable:
                    @wraps(bound_method)
                    async def wrapper(*args: Any, **kwargs: Any) -> Any:
                        return await bound_method(*args, **kwargs)
                    return wrapper
                
                # Create and cache the wrapper with bound method
                bound_wrapper = create_wrapper(method)
                self._method_cache[name] = bound_wrapper
                return bound_wrapper

        # If method not found in any repository
        raise AttributeError(f"{self._name} has no attribute '{name}'")


class UnifiedTrackRepository:
    """Combined repository that provides access to all track operations.

    This implementation uses dynamic composition to eliminate the need
    for manual method forwarding.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize all repositories with the provided session."""
        # Create the component repositories
        self.core = TrackRepository(session)
        self.sync = TrackSyncRepository(session)
        self.session = session

        # Create the dynamic composer with namespaces
        repositories = {"core": self.core, "sync": self.sync}
        self._composer = RepositoryComposer(repositories, "UnifiedTrackRepository")

    def __getattr__(self, name: str) -> Any:
        """Dynamically dispatch to the appropriate repository."""
        return getattr(self._composer, name)

    # Optional: Explicitly define the most commonly used methods for better IDE support
    # These are delegated to the composer but provide proper IDE hints

    async def get_track(self, *args: Any, **kwargs: Any) -> Any:
        """Get track by any identifier type."""
        return await self._composer.get_track(*args, **kwargs)

    async def find_track(self, *args: Any, **kwargs: Any) -> Any:
        """Find track by identifier, returning None if not found."""
        return await self._composer.find_track(*args, **kwargs)

    async def save_track(self, *args: Any, **kwargs: Any) -> Any:
        """Save track and mappings efficiently."""
        return await self._composer.save_track(*args, **kwargs)

    async def get_track_likes(self, *args: Any, **kwargs: Any) -> Any:
        """Get likes for a track across services."""
        return await self._composer.get_track_likes(*args, **kwargs)


# Note: Individual repositories (TrackRepository, TrackSyncRepository)
# are still available for direct use, but UnifiedTrackRepository should
# be preferred for most operations
