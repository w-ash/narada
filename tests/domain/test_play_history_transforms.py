"""Fast unit tests for play history transform functions."""

from datetime import UTC, datetime, timedelta

import pytest

from src.domain.entities.track import Artist, Track, TrackList
from src.domain.transforms.core import filter_by_play_history, time_range_predicate


class TestTimeRangePredicate:
    """Test time range predicate creation."""

    def test_days_back_predicate(self):
        """Test predicate with days_back parameter."""
        predicate = time_range_predicate(days_back=30)
        
        recent_date = datetime.now(UTC) - timedelta(days=15)
        old_date = datetime.now(UTC) - timedelta(days=60)
        
        assert predicate(recent_date) is True
        assert predicate(old_date) is False

    def test_absolute_date_predicate(self):
        """Test predicate with absolute dates."""
        start_date = datetime(2024, 1, 1, tzinfo=UTC)
        end_date = datetime(2024, 3, 31, tzinfo=UTC)
        predicate = time_range_predicate(after_date=start_date, before_date=end_date)
        
        in_range = datetime(2024, 2, 15, tzinfo=UTC)
        before_range = datetime(2023, 12, 15, tzinfo=UTC)
        
        assert predicate(in_range) is True
        assert predicate(before_range) is False


class TestFilterByPlayHistory:
    """Test unified play history filtering."""

    def test_min_plays_filter(self):
        """Test filtering by minimum play count."""
        tracks = [
            Track(id=1, title="Popular", artists=[Artist(name="Artist 1")]),
            Track(id=2, title="Unpopular", artists=[Artist(name="Artist 2")]),
        ]
        
        metadata = {"total_plays": {1: 10, 2: 3}}
        tracklist = TrackList(tracks=tracks, metadata=metadata)
        
        result = filter_by_play_history(min_plays=5, tracklist=tracklist)
        
        assert len(result.tracks) == 1
        assert result.tracks[0].id == 1

    def test_play_count_range_filter(self):
        """Test filtering by play count range."""
        tracks = [
            Track(id=1, title="Low", artists=[Artist(name="Artist 1")]),
            Track(id=2, title="Medium", artists=[Artist(name="Artist 2")]),
            Track(id=3, title="High", artists=[Artist(name="Artist 3")]),
        ]
        
        metadata = {"total_plays": {1: 2, 2: 5, 3: 15}}
        tracklist = TrackList(tracks=tracks, metadata=metadata)
        
        result = filter_by_play_history(min_plays=3, max_plays=10, tracklist=tracklist)
        
        assert len(result.tracks) == 1
        assert result.tracks[0].id == 2

    def test_constraint_validation(self):
        """Test that at least one constraint is required."""
        tracks = [Track(id=1, title="Test", artists=[Artist(name="Artist")])]
        tracklist = TrackList(tracks=tracks, metadata={})
        
        with pytest.raises(ValueError, match="Must specify at least one constraint"):
            filter_by_play_history(tracklist=tracklist)

    def test_curry_partial_application(self):
        """Test currying works correctly."""
        popular_filter = filter_by_play_history(min_plays=10)
        assert callable(popular_filter)
        
        tracks = [Track(id=1, title="Popular", artists=[Artist(name="Artist")])]
        metadata = {"total_plays": {1: 15}}
        tracklist = TrackList(tracks=tracks, metadata=metadata)
        
        result = popular_filter(tracklist)
        assert len(result.tracks) == 1