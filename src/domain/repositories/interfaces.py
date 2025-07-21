"""Domain repository interfaces following Clean Architecture principles.

These interfaces define the contracts for data access without depending on
infrastructure implementations, following the dependency inversion principle.
Repository interfaces belong in the domain layer according to Clean Architecture.
"""

from collections.abc import Awaitable
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    # Import domain entities for type annotations
    from src.domain.entities import (
        ConnectorTrack,
        Playlist,
        PlayRecord,
        SyncCheckpoint,
        Track,
        TrackLike,
    )


class TrackRepository(Protocol):
    """Repository interface for track persistence operations."""

    def save_track(self, track: "Track") -> Awaitable["Track"]:
        """Save track."""
        ...


class PlaylistRepository(Protocol):
    """Repository interface for playlist persistence operations."""

    def get_playlist_by_id(self, playlist_id: int) -> Awaitable["Playlist"]:
        """Get playlist by ID."""
        ...

    def save_playlist(self, playlist: "Playlist") -> Awaitable["Playlist"]:
        """Save playlist."""
        ...

    def get_playlist_by_connector(
        self, connector: str, connector_id: str, raise_if_not_found: bool = True
    ) -> Awaitable["Playlist | None"]:
        """Get playlist by connector ID."""
        ...

    def update_playlist(
        self, playlist_id: int, playlist: "Playlist"
    ) -> Awaitable["Playlist"]:
        """Update existing playlist."""
        ...


class LikeRepository(Protocol):
    """Repository interface for like persistence operations."""

    async def get_track_likes(self, track_id: int) -> list["TrackLike"]:
        """Get likes for a track."""
        ...

    async def save_track_like(self, like: "TrackLike") -> "TrackLike":
        """Save track like."""
        ...

    async def get_all_liked_tracks(
        self, service: str, is_liked: bool = True
    ) -> list["Track"]:
        """Get all liked tracks for a service."""
        ...

    async def get_unsynced_likes(
        self, service: str, limit: int = 100
    ) -> list["TrackLike"]:
        """Get unsynced likes for a service."""
        ...


class CheckpointRepository(Protocol):
    """Repository interface for sync checkpoint persistence operations."""

    async def get_sync_checkpoint(
        self, user_id: str, service: str, entity_type: str
    ) -> "SyncCheckpoint | None":
        """Get sync checkpoint."""
        ...

    async def save_sync_checkpoint(
        self, checkpoint: "SyncCheckpoint"
    ) -> "SyncCheckpoint":
        """Save sync checkpoint."""
        ...


class ConnectorRepository(Protocol):
    """Repository interface for connector track mapping operations."""

    async def find_track_by_connector(
        self, connector: str, connector_id: str
    ) -> "Track | None":
        """Find track by connector ID."""
        ...

    async def ingest_external_track(self, track: "ConnectorTrack") -> "Track":
        """Ingest external track."""
        ...

    async def map_track_to_connector(
        self, track_id: int, connector: str, connector_id: str
    ) -> None:
        """Map track to connector."""
        ...


class PlaysRepository(Protocol):
    """Repository interface for play history operations."""

    async def bulk_insert_plays(self, plays: list["PlayRecord"]) -> int:
        """Bulk insert plays."""
        ...

    async def get_recent_plays(self, limit: int = 100) -> list["PlayRecord"]:
        """Get recent plays."""
        ...


class RepositoryProvider(Protocol):
    """Consolidated repository provider interface.

    This interface provides access to all repositories in the system.
    It follows Clean Architecture by being defined in the domain layer
    while implemented in the infrastructure layer.
    """

    @property
    def core(self) -> TrackRepository:
        """Core track repository."""
        ...

    @property
    def plays(self) -> PlaysRepository:
        """Track plays repository."""
        ...

    @property
    def likes(self) -> LikeRepository:
        """Track likes repository."""
        ...

    @property
    def connector(self) -> ConnectorRepository:
        """Connector repository."""
        ...

    @property
    def checkpoints(self) -> CheckpointRepository:
        """Sync checkpoints repository."""
        ...

    @property
    def playlists(self) -> PlaylistRepository:
        """Playlist repository."""
        ...
