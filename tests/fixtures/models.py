"""Essential test fixtures for domain models and common patterns."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from src.domain.entities import Artist, Track
from src.infrastructure.persistence.database.db_models import DBPlaylist, DBTrack


@pytest.fixture
def track():
    """Basic track for most tests."""
    return Track(
        id=1,
        title="Test Track",
        artists=[Artist(name="Test Artist")],
        duration_ms=200000,
    )


@pytest.fixture
def tracks():
    """Three basic tracks for collection tests."""
    return [
        Track(
            id=i,
            title=f"Track {i}",
            artists=[Artist(name="Test Artist")],
            duration_ms=200000,
        )
        for i in range(1, 4)
    ]


@pytest.fixture
def artist():
    """Standard test artist."""
    return Artist(name="Test Artist")


@pytest.fixture
def test_timestamp():
    """UTC timestamp for tests."""
    return datetime.now(UTC)


@pytest.fixture
def mock_track_repos():
    """Pre-configured mock repository with common methods."""
    mock = AsyncMock()
    mock.likes.get_unsynced_likes.return_value = []
    mock.connector.get_connector_mappings.return_value = {}
    mock.core.find_tracks_by_ids.return_value = {}
    return mock


@pytest.fixture
def db_track():
    """Database track for repository tests."""
    db_track = DBTrack(
        id=1,
        title="Test Track",
        artists={"names": ["Test Artist"]},
        duration_ms=200000,
        release_date=None,
        isrc=None,
        spotify_id=None,
        mbid=None,
    )
    # Set required relationships
    db_track.mappings = []
    db_track.likes = []
    return db_track


@pytest.fixture
def db_tracks():
    """Multiple database tracks for repository tests."""
    db_tracks = []
    for i in range(1, 4):
        db_track = DBTrack(
            id=i,
            title=f"Track {i}",
            artists={"names": ["Test Artist"]},
            duration_ms=200000,
            release_date=None,
            isrc=None,
            spotify_id=None,
            mbid=None,
        )
        # Set required relationships
        db_track.mappings = []
        db_track.likes = []
        db_tracks.append(db_track)
    return db_tracks


@pytest.fixture
def db_playlist():
    """Database playlist for repository tests."""
    db_playlist = DBPlaylist(
        id=1,
        name="Test Playlist",
        description="Test playlist description",
        spotify_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    # Set required relationships
    db_playlist.tracks = []  # Using 'tracks' instead of 'playlist_tracks'
    return db_playlist
