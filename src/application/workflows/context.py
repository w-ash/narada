"""WorkflowContext implementation for dependency injection.

Provides concrete implementations of all workflow dependencies following
Clean Architecture principles.
"""

from dataclasses import dataclass
from typing import Any

from src.config import get_logger
from src.infrastructure.connectors import CONNECTORS, discover_connectors
from src.infrastructure.persistence.database.db_connection import get_session
from src.infrastructure.persistence.repositories.playlist import PlaylistRepositories
from src.infrastructure.persistence.repositories.track import TrackRepositories

from .protocols import (
    ConfigProvider,
    ConnectorRegistry,
    DatabaseSessionProvider,
    LoggerProvider,
    RepositoryProvider,
    WorkflowContext,
)


class ConfigProviderImpl:
    """Configuration provider implementation."""

    def __init__(self):
        """Initialize configuration provider."""
        from src.config import get_config as _get_config

        self._get_config = _get_config

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value by key."""
        return self._get_config(key, default)


class LoggerProviderImpl:
    """Logger provider implementation."""

    def __init__(self, name: str = __name__):
        """Initialize logger provider."""
        self._logger = get_logger(name)

    def info(self, message: str, **kwargs: Any) -> None:
        """Log info message."""
        self._logger.info(message, **kwargs)

    def debug(self, message: str, **kwargs: Any) -> None:
        """Log debug message."""
        self._logger.debug(message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        """Log warning message."""
        self._logger.warning(message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        """Log error message."""
        self._logger.error(message, **kwargs)


class ConnectorRegistryImpl:
    """Connector registry implementation."""

    def __init__(self):
        """Initialize connector registry."""
        # Ensure connectors are discovered
        discover_connectors()
        self._connectors = CONNECTORS

    def get_connector(self, name: str):
        """Get connector by name."""
        if name not in self._connectors:
            raise ValueError(f"Unknown connector: {name}")

        connector_config = self._connectors[name]
        # Create instance using factory with empty config
        return connector_config["factory"]({})

    def list_connectors(self) -> list[str]:
        """List available connector names."""
        return list(self._connectors.keys())


class DatabaseSessionProviderImpl:
    """Database session provider implementation."""

    def get_session(self):
        """Get database session."""
        return get_session()


class RepositoryProviderImpl:
    """Repository provider implementation."""

    def __init__(self, session):
        """Initialize repository provider with session."""
        self._session = session
        self._track_repos = None
        self._playlist_repos = None

    @property
    def core(self):
        """Core track repository."""
        if self._track_repos is None:
            self._track_repos = TrackRepositories(self._session)
        return self._track_repos.core

    @property
    def plays(self):
        """Track plays repository."""
        if self._track_repos is None:
            self._track_repos = TrackRepositories(self._session)
        return self._track_repos.plays

    @property
    def likes(self):
        """Track likes repository."""
        if self._track_repos is None:
            self._track_repos = TrackRepositories(self._session)
        return self._track_repos.likes

    @property
    def connector(self):
        """Connector repository."""
        if self._track_repos is None:
            self._track_repos = TrackRepositories(self._session)
        return self._track_repos.connector

    @property
    def checkpoints(self):
        """Sync checkpoints repository."""
        if self._track_repos is None:
            self._track_repos = TrackRepositories(self._session)
        return self._track_repos.checkpoints

    @property
    def playlists(self):
        """Playlist repository."""
        if self._playlist_repos is None:
            self._playlist_repos = PlaylistRepositories(self._session)
        return self._playlist_repos


@dataclass
class ConcreteWorkflowContext:
    """Concrete implementation of WorkflowContext."""

    config: ConfigProvider
    logger: LoggerProvider
    connectors: ConnectorRegistry
    repositories: RepositoryProvider
    session_provider: DatabaseSessionProvider


def create_workflow_context() -> WorkflowContext:
    """Create a WorkflowContext with real dependencies wired up."""
    config = ConfigProviderImpl()
    logger = LoggerProviderImpl()
    connectors = ConnectorRegistryImpl()
    session_provider = DatabaseSessionProviderImpl()

    # For repositories, we'll create a placeholder that gets the session when needed
    # This is a bit of a hack but works for the current design
    class LazyRepositoryProvider:
        """Repository provider that creates repos with fresh sessions."""

        @property
        def core(self) -> Any:
            """Core track repository."""
            # Return a mock or placeholder - this is for workflow context
            return None

        @property
        def plays(self) -> Any:
            """Track plays repository."""
            return None

        @property
        def likes(self) -> Any:
            """Track likes repository."""
            return None

        @property
        def connector(self) -> Any:
            """Connector repository."""
            return None

        @property
        def checkpoints(self) -> Any:
            """Sync checkpoints repository."""
            return None

        @property
        def playlists(self) -> Any:
            """Playlist repository."""
            return None

        async def get_track_repos(self):
            """Get track repositories with fresh session."""
            async with get_session() as session:
                return TrackRepositories(session)

        async def get_playlist_repos(self):
            """Get playlist repositories with fresh session."""
            async with get_session() as session:
                return PlaylistRepositories(session)

    repositories = LazyRepositoryProvider()

    return ConcreteWorkflowContext(
        config=config,
        logger=logger,
        connectors=connectors,
        repositories=repositories,
        session_provider=session_provider,
    )
