"""Repository layer for database operations with SQLAlchemy 2.0."""

# Re-export core components
from narada.repositories.base_repo import (
    BaseModelMapper,
    BaseRepository,
    ModelMapper,
    filter_active,
)
from narada.repositories.playlist_repo import PlaylistMapper, PlaylistRepository
from narada.repositories.repo_decorator import db_operation
from narada.repositories.track import (
    SyncCheckpointRepository,
    TrackConnectorRepository,
    TrackLikeRepository,
    TrackMetricsRepository,
    TrackRepositories,
    TrackRepository,
)
from narada.repositories.track.mapper import TrackMapper

# Define public API
__all__ = [
    "BaseModelMapper",
    "BaseRepository",
    "ModelMapper",
    "PlaylistMapper",
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
