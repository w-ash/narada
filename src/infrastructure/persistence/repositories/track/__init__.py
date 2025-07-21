"""Track repositories package.

This package provides repositories for track operations, allowing consumers
to import only what they need or use the TrackRepositories class which provides
access to all repositories via a single interface using a shared database session.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.persistence.repositories.sync import SyncCheckpointRepository
from src.infrastructure.persistence.repositories.track.connector import (
    TrackConnectorRepository,
)
from src.infrastructure.persistence.repositories.track.core import TrackRepository
from src.infrastructure.persistence.repositories.track.likes import TrackLikeRepository
from src.infrastructure.persistence.repositories.track.metrics import (
    TrackMetricsRepository,
)
from src.infrastructure.persistence.repositories.track.plays import TrackPlayRepository


class TrackRepositories:
    """Provides access to all track repositories with a shared session.

    This class is a lightweight grouping of repositories that doesn't rely on complex
    dynamic dispatch, but instead provides direct access to the underlying repositories
    through clearly named attributes.

    Example usage:
        repo = TrackRepositories(session)

        # Access individual repositories
        track = await repo.core.get_track("spotify", "123")
        mappings = await repo.connector.get_connector_mappings([track.id])
        metrics = await repo.metrics.get_track_metrics([track.id])
        likes = await repo.likes.get_track_likes(track.id)
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with a shared session for all repositories.

        Args:
            session: SQLAlchemy async session
        """
        self.session = session

        # Initialize all repositories with the shared session
        self.core = TrackRepository(session)
        self.connector = TrackConnectorRepository(session)
        self.metrics = TrackMetricsRepository(session)
        self.likes = TrackLikeRepository(session)
        self.plays = TrackPlayRepository(session)
        self.checkpoints = SyncCheckpointRepository(session)

        # Import connectors registry for metric mappings
        from src.infrastructure.connectors import CONNECTORS

        self.connectors_config = CONNECTORS

    @property
    def playlists(self):
        """Playlist repository for compatibility with RepositoryProvider protocol."""
        from src.infrastructure.persistence.repositories.playlist import (
            PlaylistRepositories,
        )

        return PlaylistRepositories(self.session)

    async def get_track(self, id_type: str, id_value: str):
        """Get a track by any identifier type.

        This convenience method checks both core and connector repositories.

        Args:
            id_type: ID type (internal, spotify, isrc, musicbrainz, lastfm, etc.)
            id_value: ID value

        Returns:
            Track if found

        Raises:
            ValueError if track not found
        """
        # Try core repository first (handles internal, spotify, isrc, musicbrainz)
        if id_type in TrackRepository._TRACK_ID_TYPES:
            return await self.core.get_track(id_type, id_value)

        # Otherwise, try connector repository (handles other services)
        track = await self.connector.find_track_by_connector(id_type, id_value)

        if not track:
            raise ValueError(f"Track with {id_type}={id_value} not found")

        return track

    async def find_track(self, id_type: str, id_value: str):
        """Find a track by any identifier type, returning None if not found.

        This convenience method checks both core and connector repositories.

        Args:
            id_type: ID type (internal, spotify, isrc, musicbrainz, lastfm, etc.)
            id_value: ID value

        Returns:
            Track if found, None otherwise
        """
        # Try core repository first
        if id_type in TrackRepository._TRACK_ID_TYPES:
            return await self.core.find_track(id_type, id_value)

        # Otherwise, try connector repository
        return await self.connector.find_track_by_connector(id_type, id_value)


# Export individual repositories for direct import
__all__ = [
    "SyncCheckpointRepository",
    "TrackConnectorRepository",
    "TrackLikeRepository",
    "TrackMetricsRepository",
    "TrackPlayRepository",
    "TrackRepositories",
    "TrackRepository",
]
