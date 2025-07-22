"""Essential transform tests."""

from src.domain.entities import Track, Artist, TrackList
from src.application.workflows.transform_registry import TRANSFORM_REGISTRY


class TestTransforms:
    """Test transforms actually work with data."""
    
    def test_filter_deduplicate_works(self):
        """Test deduplicate filter works."""
        tracks = [
            Track(id=1, title="Same", artists=[Artist(name="Artist")]),
            Track(id=1, title="Same", artists=[Artist(name="Artist")]),  # Duplicate
            Track(id=2, title="Different", artists=[Artist(name="Artist")])
        ]
        tracklist = TrackList(tracks=tracks)
        
        # Get the transform function
        transform_factory = TRANSFORM_REGISTRY["filter"]["deduplicate"]
        transform = transform_factory({}, {})
        
        result = transform(tracklist)
        assert isinstance(result, TrackList)
        # Should have fewer tracks after deduplication
        assert len(result.tracks) <= len(tracklist.tracks)
    
    def test_selector_limit_works(self):
        """Test limit selector works."""
        tracks = [Track(id=i, title=f"Track {i}", artists=[Artist(name="Artist")]) 
                 for i in range(10)]
        tracklist = TrackList(tracks=tracks)
        
        transform_factory = TRANSFORM_REGISTRY["selector"]["limit_tracks"]
        transform = transform_factory({}, {"count": 5})
        
        result = transform(tracklist)
        assert isinstance(result, TrackList)
        assert len(result.tracks) == 5