"""Core domain models and business logic for music entity management.

This package contains the central domain models, transformation functions,
and business logic that power Narada's music integration capabilities.
"""

# Import matcher functionality
from narada.core.matcher import MatchResult, batch_match_tracks

# Import core domain models
from narada.core.models import Artist, ConnectorTrackMapping, Playlist, Track, TrackList

# Import transform functions
from narada.core.transforms import (  # Type definitions; Core pipeline functions; Filtering functions; Sorting functions; Selection functions; Combination functions; Playlist operations
    Transform,
    concatenate,
    create_pipeline,
    exclude_artists,
    exclude_tracks,
    filter_by_date_range,
    filter_by_predicate,
    filter_duplicates,
    interleave,
    limit,
    rename,
    sample_random,
    select_by_method,
    set_description,
    sort_by_attribute,
    take_last,
)

# Import repository classes
from narada.repositories import BaseRepository, PlaylistRepository, UnifiedTrackRepository

# Define explicit public API
__all__ = [
    "Artist",
    "BaseRepository",
    "ConnectorTrackMapping",
    "MatchResult",
    "Playlist",
    "PlaylistRepository",
    "Track",
    "TrackList",
    "UnifiedTrackRepository",
    "Transform",
    "batch_match_tracks",
    "concatenate",
    "create_pipeline",
    "exclude_artists",
    "exclude_tracks",
    "filter_by_date_range",
    "filter_by_predicate",
    "filter_duplicates",
    "interleave",
    "limit",
    "rename",
    "sample_random",
    "select_by_method",
    "set_description",
    "sort_by_attribute",
    "take_last",
]
