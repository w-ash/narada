"""Repository layer for database operations with SQLAlchemy 2.0."""

# Re-export core components
from narada.repositories.base import BaseRepository, ModelMapper
from narada.repositories.playlist import PlaylistMapper, PlaylistRepository
from narada.repositories.repo_decorator import db_operation
from narada.repositories.track import TrackMapper, TrackRepository

# Define public API
__all__ = [
    "BaseRepository",
    "ModelMapper",
    "PlaylistMapper",
    "PlaylistRepository",
    "TrackMapper",
    "TrackRepository",
    "db_operation",
]
