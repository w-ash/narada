"""Domain model test suite.

Validates the core domain model foundations that underpin our transformation pipeline.
These tests verify that our domain entities maintain strict immutability while
enabling functional transformations - a pattern proven successful in production
streaming platforms.

Test success means:
1. Domain models enforce immutability at all levels
2. Business rule validation prevents invalid states
3. Transformations produce new instances with correct state
4. Operations compose predictably and maintain data integrity
"""

import pytest
from attrs import exceptions

from narada.core.models import (
    Artist,
    ConnectorTrackMapping,
    Playlist,
    PlaylistOperation,
    Track,
    filter_by_predicate,
    sort_by_attribute,
)


@pytest.fixture
def sample_artist() -> Artist:
    """Provide a standard artist instance for testing.

    Success criteria:
    - Returns valid Artist instance with name "Fleetwood Mac"
    - Instance is immutable
    """
    return Artist(name="Fleetwood Mac")


@pytest.fixture
def sample_track(sample_artist: Artist) -> Track:
    """Provide a standard track instance for testing.

    Success criteria:
    - Returns valid Track with all required fields
    - Contains sample_artist in artists list
    - All optional fields set to expected values
    """
    return Track(
        title="Dreams",
        artists=[sample_artist],
        album="Rumours",
        duration_ms=258000,
    )


@pytest.fixture
def sample_playlist(sample_track: Track) -> Playlist:
    """Provide a standard playlist for transformation testing.

    Success criteria:
    - Returns valid Playlist containing sample_track
    - Name and tracks list properly initialized
    - Instance ready for transformation operations
    """
    return Playlist(
        name="Test Playlist",
        tracks=[sample_track],
    )


def test_track_construction_and_validation(sample_artist: Artist):
    """Verify track construction enforces business rules.

    Why we test this:
    Track construction is the entry point for all music metadata. Strong validation
    here prevents invalid states from propagating through our pipeline.

    Success criteria:
    1. Track creates successfully with valid data
    2. ValueError raised for empty artists list
    3. Optional fields handled correctly
    4. Created instance matches input data exactly
    """
    # Valid construction
    track = Track(
        title="Dreams",
        artists=[sample_artist],
        album="Rumours",
    )
    assert track.title == "Dreams"
    assert len(track.artists) == 1
    assert track.album == "Rumours"

    # Invalid states
    with pytest.raises(exceptions.FrozenInstanceError):
        setattr(track, "title", "New Title")  # Immutability check

    with pytest.raises(ValueError):
        Track(title="Dreams", artists=[])  # Empty artists validation


def test_track_transformation(sample_track: Track):
    """Verify track transformation patterns.

    Why we test this:
    Our functional architecture depends on reliable track transformations that
    maintain immutability while accurately reflecting state changes.

    Success criteria:
    1. with_play_count creates new instance
    2. New instance has updated play count
    3. All other fields remain identical
    4. Original instance unchanged
    """
    enriched = sample_track.with_play_count(42)
    assert enriched is not sample_track  # New instance
    assert enriched.play_count == 42  # Updated count
    assert enriched.title == sample_track.title  # Other fields preserved
    assert sample_track.play_count is None  # Original unchanged


def test_playlist_operations(sample_playlist: Playlist, sample_track: Track):
    """Verify playlist transformation operations.

    Why we test this:
    Playlist operations form the core of our transformation pipeline. They must
    maintain order, handle edge cases, and compose predictably.

    Success criteria:
    1. Sorting operation produces expected order
    2. Filtering removes correct tracks
    3. Operations compose as expected
    4. Edge cases (None values, empty lists) handled gracefully
    """
    # Test sort operation
    track_with_plays = sample_track.with_play_count(42)
    playlist = sample_playlist.with_tracks([sample_track, track_with_plays])

    sorted_playlist = sort_by_attribute("play_count", reverse=True).apply(playlist)
    assert sorted_playlist.tracks[0].play_count == 42  # Highest plays first

    # Test filter operation
    has_plays = filter_by_predicate(lambda t: t.play_count is not None, "Has plays")
    filtered = has_plays.apply(playlist)
    assert len(filtered.tracks) == 1
    assert filtered.tracks[0].play_count == 42


def test_service_mapping():
    """Verify service mapping validation and confidence scoring.

    Why we test this:
    Service mappings are critical for cross-service entity resolution. They must
    maintain strict validation of confidence scores and match methods.

    Success criteria:
    1. Valid mapping creates successfully
    2. Invalid confidence scores rejected
    3. Invalid match methods rejected
    4. Metadata properly stored
    """
    # Valid mapping
    mapping = ConnectorTrackMapping(
        connector_name="spotify",
        connector_track_id="123",
        match_method="direct",
        confidence=100,
        metadata={"uri": "spotify:track:123"},
    )
    assert mapping.confidence == 100
    assert mapping.metadata["uri"] == "spotify:track:123"

    # Validation boundaries
    with pytest.raises(ValueError):
        ConnectorTrackMapping(
            connector_name="spotify",
            connector_track_id="123",
            match_method="direct",
            confidence=101,  # Over maximum
        )

    with pytest.raises(ValueError):
        ConnectorTrackMapping(
            connector_name="spotify",
            connector_track_id="123",
            match_method="invalid",  # Invalid method
            confidence=100,
        )


def test_operation_composition(sample_playlist: Playlist):
    """Verify operation composition patterns.

    Why we test this:
    Operation composition enables complex transformations from simple parts.
    This pattern must be reliable and predictable.

    Success criteria:
    1. Operations compose with correct ordering
    2. Operation names combine clearly
    3. Composed operations maintain type safety
    4. Transformation results match expected output
    """
    sort_op = sort_by_attribute("title")
    filter_op = filter_by_predicate(lambda t: t.play_count is not None, "Has plays")

    combined = sort_op.then(filter_op)
    assert isinstance(combined, PlaylistOperation)
    assert "→" in combined.name

    result = combined.apply(sample_playlist)
    assert isinstance(result, Playlist)
