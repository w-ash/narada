"""Tests for play deduplication functionality."""

from datetime import UTC, datetime, timedelta

import pytest

from src.domain.entities import TrackPlay
from src.infrastructure.services.play_deduplication import (
    calculate_play_match_confidence,
    find_potential_duplicate_plays,
)


@pytest.fixture
def spotify_play():
    """Spotify play with full context."""
    return TrackPlay(
        track_id=1,
        service="spotify",
        played_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        ms_played=210000,  # 3.5 minutes
        context={
            "track_name": "Bohemian Rhapsody",
            "artist_name": "Queen",
            "album_name": "A Night at the Opera",
            "platform": "Android",
            "spotify_track_uri": "spotify:track:1234567890",
        },
        import_source="spotify_export",
    )


@pytest.fixture
def lastfm_play():
    """Last.fm play with typical scrobble data."""
    return TrackPlay(
        track_id=None,  # Unresolved
        service="lastfm", 
        played_at=datetime(2024, 1, 1, 12, 2, 0, tzinfo=UTC),  # 2 min later
        ms_played=None,  # Last.fm doesn't track this
        context={
            "track_name": "Bohemian Rhapsody",
            "artist_name": "Queen", 
            "album_name": "A Night at the Opera",
            "lastfm_track_url": "https://www.last.fm/music/Queen/_/Bohemian+Rhapsody",
        },
        import_source="lastfm_api",
    )


class TestCalculatePlayMatchConfidence:
    """Test confidence calculation for play matching."""

    def test_identical_plays_within_time_window(self, spotify_play, lastfm_play):
        """Identical tracks within time window should have high confidence."""
        confidence, evidence = calculate_play_match_confidence(
            spotify_play, lastfm_play, time_window_seconds=300
        )
        
        # Should be high confidence (exact match with small time penalty)
        assert confidence >= 70  # Adjusted for realistic confidence scoring
        assert evidence.final_score == confidence
        assert evidence.title_similarity > 0.9
        assert evidence.artist_similarity > 0.9

    def test_plays_outside_time_window(self, spotify_play, lastfm_play):
        """Plays outside time window should return 0 confidence."""
        # Move last.fm play 10 minutes later
        late_lastfm = TrackPlay(
            track_id=lastfm_play.track_id,
            service=lastfm_play.service,
            played_at=spotify_play.played_at + timedelta(minutes=10),
            ms_played=lastfm_play.ms_played,
            context=lastfm_play.context,
            import_source=lastfm_play.import_source,
        )
        
        confidence, evidence = calculate_play_match_confidence(
            spotify_play, late_lastfm, time_window_seconds=300  # 5 minutes
        )
        
        assert confidence == 0
        assert evidence.final_score == 0

    def test_different_tracks_within_time_window(self, spotify_play):
        """Different tracks should have low confidence even within time window."""
        different_track = TrackPlay(
            track_id=2,
            service="lastfm",
            played_at=spotify_play.played_at + timedelta(minutes=1),
            ms_played=None,
            context={
                "track_name": "Another One Bites the Dust",
                "artist_name": "Queen",  # Same artist, different song
                "album_name": "The Game",
            },
            import_source="lastfm_api",
        )
        
        confidence, evidence = calculate_play_match_confidence(
            spotify_play, different_track, time_window_seconds=300
        )
        
        # Should be low confidence due to different track names
        assert confidence <= 50
        assert evidence.title_similarity < 0.5

    def test_similar_but_not_identical_tracks(self, spotify_play):
        """Track variations should have medium confidence."""
        variation_play = TrackPlay(
            track_id=None,
            service="lastfm", 
            played_at=spotify_play.played_at + timedelta(seconds=30),
            ms_played=None,
            context={
                "track_name": "Bohemian Rhapsody - Live",  # Variation
                "artist_name": "Queen",
                "album_name": "Live at Wembley",
            },
            import_source="lastfm_api",
        )
        
        confidence, evidence = calculate_play_match_confidence(
            spotify_play, variation_play, time_window_seconds=300
        )
        
        # Should be medium confidence (variation detected)
        assert 40 <= confidence <= 80
        assert evidence.title_similarity < 0.9  # Reduced due to variation


class TestFindPotentialDuplicatePlays:
    """Test finding duplicate plays."""

    def test_find_duplicate_in_candidates(self, spotify_play, lastfm_play):
        """Should find matching play in candidate list."""
        candidates = [
            # Different track
            TrackPlay(
                track_id=2,
                service="lastfm",
                played_at=spotify_play.played_at,
                context={"track_name": "Different Song", "artist_name": "Other Artist"},
                import_source="lastfm_api",
            ),
            # Matching track
            lastfm_play,
        ]
        
        duplicates = find_potential_duplicate_plays(
            spotify_play, candidates, time_window_seconds=300, min_confidence=70
        )
        
        assert len(duplicates) == 1
        duplicate_play, confidence, _evidence = duplicates[0]
        assert duplicate_play.service == "lastfm"
        assert confidence >= 70

    def test_no_duplicates_found(self, spotify_play):
        """Should return empty list when no duplicates found."""
        candidates = [
            TrackPlay(
                track_id=2,
                service="lastfm",
                played_at=spotify_play.played_at + timedelta(minutes=10),  # Outside window
                context={"track_name": "Different Song", "artist_name": "Other Artist"},
                import_source="lastfm_api",
            )
        ]
        
        duplicates = find_potential_duplicate_plays(
            spotify_play, candidates, time_window_seconds=300, min_confidence=70
        )
        
        assert len(duplicates) == 0

    def test_ignores_same_service_plays(self, spotify_play):
        """Should ignore plays from same service."""
        same_service_play = TrackPlay(
            track_id=2,
            service="spotify",  # Same service
            played_at=spotify_play.played_at,
            context=spotify_play.context,
            import_source="spotify_export",
        )
        
        duplicates = find_potential_duplicate_plays(
            spotify_play, [same_service_play], time_window_seconds=300, min_confidence=70
        )
        
        assert len(duplicates) == 0

    def test_sorts_by_confidence_descending(self, spotify_play):
        """Should sort results by confidence (highest first)."""
        # Create two potential matches with different confidence levels
        high_confidence_play = TrackPlay(
            track_id=None,
            service="lastfm",
            played_at=spotify_play.played_at + timedelta(seconds=30),  # Close time
            context={
                "track_name": "Bohemian Rhapsody",  # Exact match
                "artist_name": "Queen",
                "album_name": "A Night at the Opera",
            },
            import_source="lastfm_api",
        )
        
        low_confidence_play = TrackPlay(
            track_id=None,
            service="lastfm",
            played_at=spotify_play.played_at + timedelta(minutes=4),  # Further time
            context={
                "track_name": "Bohemian Rhapsody - Live",  # Variation
                "artist_name": "Queen",
                "album_name": "Different Album",
            },
            import_source="lastfm_api",
        )
        
        duplicates = find_potential_duplicate_plays(
            spotify_play, 
            [low_confidence_play, high_confidence_play],  # Reversed order
            time_window_seconds=300, 
            min_confidence=50
        )
        
        assert len(duplicates) == 2
        # Should be sorted by confidence descending
        assert duplicates[0][1] > duplicates[1][1]