"""Repository layer for database operations with SQLAlchemy 2.0."""

# Re-export core components
from narada.repositories.base_repo import BaseRepository, ModelMapper
from narada.repositories.playlist_repo import PlaylistMapper, PlaylistRepository
from narada.repositories.repo_decorator import db_operation
from narada.repositories.track_core_repo import TrackMapper, TrackRepository
from narada.repositories.track_repo import UnifiedTrackRepository
from narada.repositories.track_sync_repo import TrackSyncRepository

# Define public API
__all__ = [
    "BaseRepository",
    "ModelMapper",
    "PlaylistMapper",
    "PlaylistRepository",
    "TrackMapper",
    "TrackRepository",
    "TrackSyncRepository",
    "UnifiedTrackRepository",
    "db_operation",
]
