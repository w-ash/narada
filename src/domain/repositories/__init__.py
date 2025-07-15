"""Domain repository interfaces following Clean Architecture principles.

These interfaces define the contracts for data access without depending on
infrastructure implementations, following the dependency inversion principle.
"""

from .interfaces import (
    CheckpointRepository,
    ConnectorRepository,
    LikeRepository,
    PlaylistRepository,
    RepositoryProvider,
    TrackRepository,
)

__all__ = [
    "CheckpointRepository",
    "ConnectorRepository",
    "LikeRepository",
    "PlaylistRepository",
    "RepositoryProvider",
    "TrackRepository",
]
