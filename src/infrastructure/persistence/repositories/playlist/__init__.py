"""Playlist repositories package.

This package provides repositories for playlist operations, allowing consumers
to import only what they need or use the PlaylistRepositories class which provides
access to all repositories via a single interface using a shared database session.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities import Playlist
from src.infrastructure.persistence.database.db_models import DBPlaylistMapping
from src.infrastructure.persistence.repositories.playlist.connector import (
    ConnectorPlaylistRepository,
    PlaylistConnectorRepository,
)
from src.infrastructure.persistence.repositories.playlist.core import PlaylistRepository
from src.infrastructure.persistence.repositories.playlist.mapper import (
    PlaylistMappingRepository,
)
from src.infrastructure.persistence.repositories.repo_decorator import db_operation


class PlaylistRepositories:
    """Provides access to all playlist repositories with a shared session.

    This class is a lightweight grouping of repositories that doesn't rely on complex
    dynamic dispatch, but instead provides direct access to the underlying repositories
    through clearly named attributes.

    Example usage:
        repo = PlaylistRepositories(session)

        # Access individual repositories
        playlist = await repo.core.get_playlist_by_id(123)
        connector_playlist = await repo.connector.find_playlist_by_connector("spotify", "xyz")
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with a shared session for all repositories.

        Args:
            session: SQLAlchemy async session
        """
        self.session = session

        # Initialize all repositories with the shared session
        self.core = PlaylistRepository(session)
        self.connector = PlaylistConnectorRepository(session)
        self.connector_repo = ConnectorPlaylistRepository(session)
        self.mapping_repo = PlaylistMappingRepository(session)

        # Import connectors registry for potential use
        from src.infrastructure.connectors import CONNECTORS

        self.connectors_config = CONNECTORS

    async def get_playlist(self, id_type: str, id_value: str) -> Playlist:
        """Get a playlist by any identifier type.

        This convenience method checks both core and connector repositories.

        Args:
            id_type: ID type (internal, spotify, etc.)
            id_value: ID value

        Returns:
            Playlist if found

        Raises:
            ValueError if playlist not found
        """
        # Try internal ID first
        if id_type in ("internal", "id"):
            try:
                playlist_id = int(id_value)
                return await self.core.get_by_id(playlist_id)
            except (ValueError, TypeError) as err:
                raise ValueError(f"Invalid playlist ID format: {id_value}") from err

        # Otherwise, try connector repository
        playlist = await self.connector.find_playlist_by_connector(id_type, id_value)

        if not playlist:
            raise ValueError(f"Playlist with {id_type}={id_value} not found")

        return playlist

    async def find_playlist(self, id_type: str, id_value: str) -> Playlist | None:
        """Find a playlist by any identifier type, returning None if not found.

        This convenience method checks both core and connector repositories.

        Args:
            id_type: ID type (internal, spotify, etc.)
            id_value: ID value

        Returns:
            Playlist if found, None otherwise
        """
        try:
            return await self.get_playlist(id_type, id_value)
        except ValueError:
            return None

    @db_operation("count_playlists")
    async def count_playlists(self, connector: str | None = None) -> int:
        """Count playlists, optionally filtered by connector."""
        stmt = select(func.count(self.core.model_class.id)).where(
            self.core.model_class.is_deleted == False  # noqa: E712
        )

        if connector:
            # Add join and filter for connector
            stmt = stmt.join(
                DBPlaylistMapping,
                self.core.model_class.id == DBPlaylistMapping.playlist_id,
            ).where(
                DBPlaylistMapping.connector_name == connector,
                DBPlaylistMapping.is_deleted == False,  # noqa: E712
            )

        result = await self.session.scalar(stmt)
        return result or 0


# Export individual repositories for direct import
__all__ = [
    "ConnectorPlaylistRepository",
    "PlaylistConnectorRepository",
    "PlaylistMappingRepository",
    "PlaylistRepositories",
    "PlaylistRepository",
]
