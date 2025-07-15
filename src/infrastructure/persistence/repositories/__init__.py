"""Repository layer for database operations with SQLAlchemy 2.0."""

# Re-export core components
from src.infrastructure.persistence.repositories.base_repo import (
    BaseModelMapper,
    BaseRepository,
    ModelMapper,
    filter_active,
)
from src.infrastructure.persistence.repositories.playlist import PlaylistRepositories
from src.infrastructure.persistence.repositories.playlist.core import PlaylistRepository
from src.infrastructure.persistence.repositories.playlist.mapper import PlaylistMapper
from src.infrastructure.persistence.repositories.repo_decorator import db_operation
from src.infrastructure.persistence.repositories.sync import SyncCheckpointRepository
from src.infrastructure.persistence.repositories.track import (
    TrackConnectorRepository,
    TrackLikeRepository,
    TrackMetricsRepository,
    TrackRepositories,
    TrackRepository,
)
from src.infrastructure.persistence.repositories.track.mapper import TrackMapper

# Define public API
__all__ = [
    "BaseModelMapper",
    "BaseRepository",
    "ModelMapper",
    "PlaylistMapper",
    "PlaylistRepositories",
    "PlaylistRepository",
    "SyncCheckpointRepository",
    "TrackConnectorRepository",
    "TrackLikeRepository",
    "TrackMapper",
    "TrackMetricsRepository",
    "TrackRepositories",
    "TrackRepository",
    "db_operation",
    "filter_active",
]
