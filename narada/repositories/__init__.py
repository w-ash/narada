"""Repository layer for database operations with SQLAlchemy 2.0."""

# Re-export core components
from narada.repositories.base import BaseRepository, ModelMapper
from narada.repositories.playlist import PlaylistMapper, PlaylistRepository
from narada.repositories.repo_decorator import db_operation
from narada.repositories.track import UnifiedTrackRepository
from narada.repositories.track_core import TrackMapper, TrackRepository
from narada.repositories.track_sync import TrackSyncRepository

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
