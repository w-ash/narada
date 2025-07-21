"""WorkflowContext implementation for dependency injection.

Provides concrete implementations of all workflow dependencies following
Clean Architecture principles.
"""

from dataclasses import dataclass
from typing import Any

from src.config import get_logger
from src.domain.repositories.interfaces import PlaylistRepository, TrackRepository
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
    UseCaseProvider,
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


class SharedSessionProvider:
    """Shared session provider for workflow-scoped database access.

    This provider manages a single AsyncSession that is shared across
    all workflow tasks to prevent SQLite database locks caused by
    concurrent sessions.
    """

    def __init__(self, session):
        """Initialize with a shared session."""
        self._session = session

    def get_session(self):
        """Get the shared session (already opened)."""
        return self._session

    async def __aenter__(self):
        """Async context manager entry - session already opened."""
        return self._session

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - do nothing, session managed by workflow."""


class UseCaseProviderImpl:
    """Use case provider implementation with dependency injection."""

    def __init__(self, shared_session=None):
        """Initialize with optional shared session."""
        self._shared_session = shared_session

    async def get_save_playlist_use_case(self):
        """Get SavePlaylistUseCase with injected dependencies."""
        from src.application.use_cases.save_playlist import SavePlaylistUseCase

        if self._shared_session:
            # Use the shared session from workflow context
            track_repos = TrackRepositories(self._shared_session)
            playlist_repos = PlaylistRepositories(self._shared_session)

            return SavePlaylistUseCase(
                track_repo=track_repos.core, playlist_repo=playlist_repos.core
            )
        else:
            # Fallback to individual session (for non-workflow usage)
            async with get_session() as session:
                track_repos = TrackRepositories(session)
                playlist_repos = PlaylistRepositories(session)

                return SavePlaylistUseCase(
                    track_repo=track_repos.core, playlist_repo=playlist_repos.core
                )

    async def get_update_playlist_use_case(self):
        """Get UpdatePlaylistUseCase with injected dependencies."""
        from src.application.use_cases.update_playlist import UpdatePlaylistUseCase

        if self._shared_session:
            # Use the shared session from workflow context
            playlist_repos = PlaylistRepositories(self._shared_session)

            return UpdatePlaylistUseCase(playlist_repo=playlist_repos.core)
        else:
            # Fallback to individual session (for non-workflow usage)
            async with get_session() as session:
                playlist_repos = PlaylistRepositories(session)

                return UpdatePlaylistUseCase(playlist_repo=playlist_repos.core)


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
    use_cases: UseCaseProvider
    session_provider: DatabaseSessionProvider
    repositories: RepositoryProvider  # Legacy compatibility


def create_workflow_context(shared_session=None) -> WorkflowContext:
    """Create a WorkflowContext with real dependencies wired up."""
    config = ConfigProviderImpl()
    logger = LoggerProviderImpl()
    connectors = ConnectorRegistryImpl()
    session_provider = DatabaseSessionProviderImpl()
    use_cases = UseCaseProviderImpl(shared_session)

    # Create proper repository provider implementation (legacy compatibility)
    class ProperRepositoryProvider:
        """Repository provider that implements the RepositoryProvider interface properly."""

        # For now, return None for properties we don't need yet
        # These will be implemented when needed
        @property
        def core(self) -> Any:
            return None

        @property
        def plays(self) -> Any:
            return None

        @property
        def likes(self) -> Any:
            return None

        @property
        def connector(self) -> Any:
            return None

        @property
        def checkpoints(self) -> Any:
            return None

        @property
        def playlists(self) -> Any:
            return None

        async def create_repos_with_shared_session(
            self,
        ) -> tuple[TrackRepository, PlaylistRepository, Any]:
            """Create track and playlist repositories sharing a single session.

            This ensures both repositories operate within the same transaction,
            preventing database locking and ensuring ACID properties.

            Returns:
                Tuple of (track_repo, playlist_repo, session_context)
            """
            session = get_session()
            session_ctx = await session.__aenter__()

            track_repos = TrackRepositories(session_ctx)
            playlist_repos = PlaylistRepositories(session_ctx)

            return track_repos.core, playlist_repos.core, session

        async def create_playlist_repo_with_session(
            self,
        ) -> tuple[PlaylistRepository, Any]:
            """Create playlist repository with session for UpdatePlaylistUseCase.

            Returns:
                Tuple of (playlist_repo, session_context)
            """
            session = get_session()
            session_ctx = await session.__aenter__()
            playlist_repos = PlaylistRepositories(session_ctx)
            return playlist_repos.core, session

    repositories = ProperRepositoryProvider()

    return ConcreteWorkflowContext(
        config=config,
        logger=logger,
        connectors=connectors,
        use_cases=use_cases,
        session_provider=session_provider,
        repositories=repositories,  # Legacy compatibility
    )
