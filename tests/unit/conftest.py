"""Unit test fixtures - Import domain fixtures for application layer tests.

Application layer unit tests need access to domain entities for testing
use case orchestration with mocked dependencies.
"""

# Import all domain fixtures to make them available to unit tests
from tests.domain.conftest import (
    artist,
    track,
    tracks,
    tracks_with_metadata,
    tracklist,
    tracklist_with_metrics,
    playlist,
    empty_playlist,
    test_timestamp,
)

# Re-export for pytest discovery
__all__ = [
    "artist",
    "track", 
    "tracks",
    "tracks_with_metadata",
    "tracklist",
    "tracklist_with_metrics",
    "playlist",
    "empty_playlist",
    "test_timestamp",
]