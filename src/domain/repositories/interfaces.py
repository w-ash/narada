"""Domain repository interfaces following Clean Architecture principles.

These interfaces define the contracts for data access without depending on
infrastructure implementations, following the dependency inversion principle.
Repository interfaces belong in the domain layer according to Clean Architecture.
"""

from typing import Any, Protocol

# Import domain entities to properly type the interfaces
# Note: Using Any for now to avoid circular imports, but should be properly typed


class TrackRepository(Protocol):
    """Repository interface for track persistence operations."""

    async def get_by_id(self, track_id: int) -> Any:
        """Get track by ID."""
        ...

    async def save(self, track: Any) -> Any:
        """Save track."""
        ...

    async def find_by_metadata(self, **kwargs) -> list[Any]:
        """Find tracks by metadata criteria."""
        ...


class PlaylistRepository(Protocol):
    """Repository interface for playlist persistence operations."""

    async def get_by_id(self, playlist_id: int) -> Any:
        """Get playlist by ID."""
        ...

    async def save(self, playlist: Any) -> Any:
        """Save playlist."""
        ...

    async def find_by_name(self, name: str) -> Any:
        """Find playlist by name."""
        ...


class LikeRepository(Protocol):
    """Repository interface for like persistence operations."""

    async def get_track_likes(self, track_id: int) -> list[Any]:
        """Get likes for a track."""
        ...

    async def save_track_like(self, like: Any) -> Any:
        """Save track like."""
        ...

    async def get_all_liked_tracks(
        self, service: str, is_liked: bool = True
    ) -> list[Any]:
        """Get all liked tracks for a service."""
        ...

    async def get_unsynced_likes(self, service: str, limit: int = 100) -> list[Any]:
        """Get unsynced likes for a service."""
        ...


class CheckpointRepository(Protocol):
    """Repository interface for sync checkpoint persistence operations."""

    async def get_sync_checkpoint(
        self, user_id: str, service: str, entity_type: str
    ) -> Any:
        """Get sync checkpoint."""
        ...

    async def save_sync_checkpoint(self, checkpoint: Any) -> Any:
        """Save sync checkpoint."""
        ...


class ConnectorRepository(Protocol):
    """Repository interface for connector track mapping operations."""

    async def find_track_by_connector(self, connector: str, connector_id: str) -> Any:
        """Find track by connector ID."""
        ...

    async def ingest_external_track(self, track: Any) -> Any:
        """Ingest external track."""
        ...

    async def map_track_to_connector(
        self, track_id: int, connector: str, connector_id: str
    ) -> None:
        """Map track to connector."""
        ...


class PlaysRepository(Protocol):
    """Repository interface for play history operations."""

    async def bulk_insert_plays(self, plays: list[Any]) -> Any:
        """Bulk insert plays."""
        ...

    async def get_recent_plays(self, limit: int = 100) -> list[Any]:
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
