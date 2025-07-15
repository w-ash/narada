"""Core domain entities representing music concepts."""

# Track-related entities
# Operation-related entities
from .operations import (
    OperationResult,
    PlayRecord,
    SyncCheckpoint,
    TrackContextFields,
    TrackPlay,
    WorkflowResult,
    create_lastfm_play_record,
)

# Playlist-related entities
from .playlist import (
    ConnectorPlaylist,
    ConnectorPlaylistItem,
    Playlist,
    PlaylistTrack,
)

# Shared utilities
from .shared import ensure_utc
from .track import (
    Artist,
    ConnectorTrack,
    ConnectorTrackMapping,
    Track,
    TrackLike,
    TrackList,
    TrackMetric,
)

__all__ = [
    # Track entities
    "Artist",
    "Track", 
    "TrackLike",
    "TrackMetric",
    "ConnectorTrack",
    "ConnectorTrackMapping",
    "TrackList",
    # Playlist entities
    "ConnectorPlaylistItem",
    "Playlist",
    "ConnectorPlaylist", 
    "PlaylistTrack",
    # Operation entities
    "SyncCheckpoint",
    "TrackContextFields",
    "PlayRecord",
    "TrackPlay",
    "OperationResult",
    "WorkflowResult",
    "create_lastfm_play_record",
    # Shared utilities
    "ensure_utc",
]