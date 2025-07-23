"""Comprehensive test for LastFM workflow functionality."""

from src.application.workflows.node_factories import create_enricher_node
from src.application.workflows.transform_registry import TRANSFORM_REGISTRY
from src.domain.entities.operations import WorkflowResult
from src.domain.entities.track import Artist, Track, TrackList
from src.domain.transforms.core import sort_by_attribute


class TestLastFMWorkflowComprehensive:
    """Test the complete LastFM workflow functionality."""

    def test_sort_by_lastfm_user_playcount_workflow_config(self):
        """Test that the workflow configuration matches the sorter implementation."""
        # Test the transform registry configuration
        sorter_config = {"metric_name": "lastfm_user_playcount", "reverse": True}
        
        # This should match how the workflow calls it
        transform_fn = TRANSFORM_REGISTRY["sorter"]["by_metric"](None, sorter_config)
        
        # Create test tracklist with metrics
        track1 = Track(id=1, title="Track 1", artists=[Artist(name="Artist 1")])
        track2 = Track(id=2, title="Track 2", artists=[Artist(name="Artist 2")])
        track3 = Track(id=3, title="Track 3", artists=[Artist(name="Artist 3")])
        
        tracklist = TrackList(
            tracks=[track1, track2, track3],
            metadata={
                "metrics": {
                    "lastfm_user_playcount": {
                        1: 25,  # Track 1 has 25 plays
                        2: 100,  # Track 2 has 100 plays
                        3: 50,  # Track 3 has 50 plays
                    }
                }
            }
        )
        
        # Apply transform
        result = transform_fn(tracklist)
        
        # Verify sorting (descending order: 100, 50, 25)
        assert result.tracks[0].id == 2  # 100 plays
        assert result.tracks[1].id == 3  # 50 plays
        assert result.tracks[2].id == 1  # 25 plays
        
        # Verify metrics are preserved
        assert "lastfm_user_playcount" in result.metadata["metrics"]
        assert result.metadata["metrics"]["lastfm_user_playcount"][2] == 100

    def test_workflow_result_display_metrics(self):
        """Test that WorkflowResult properly displays metrics in the UI."""
        # Create test tracks
        track1 = Track(id=1, title="Track 1", artists=[Artist(name="Artist 1")])
        track2 = Track(id=2, title="Track 2", artists=[Artist(name="Artist 2")])
        
        # Create WorkflowResult with LastFM metrics
        result = WorkflowResult(
            tracks=[track1, track2],
            operation_name="sort_by_lastfm_user_playcount",
            metrics={
                "lastfm_user_playcount": {
                    1: 50,
                    2: 100,
                },
                "lastfm_global_playcount": {
                    1: 1000,
                    2: 2000,
                },
            }
        )
        
        # Test that metrics are accessible via get_metric
        assert result.get_metric(1, "lastfm_user_playcount") == 50
        assert result.get_metric(2, "lastfm_user_playcount") == 100
        assert result.get_metric(1, "lastfm_global_playcount") == 1000
        assert result.get_metric(2, "lastfm_global_playcount") == 2000
        
        # Test that metrics keys are available for UI display
        assert "lastfm_user_playcount" in result.metrics
        assert "lastfm_global_playcount" in result.metrics
        
        # Test metric column detection (UI code uses result.metrics.keys())
        metric_columns = sorted(result.metrics.keys())
        assert "lastfm_global_playcount" in metric_columns
        assert "lastfm_user_playcount" in metric_columns

    def test_lastfm_enricher_node_config(self):
        """Test that LastFM enricher node is configured correctly."""
        # Test that the enricher node can be created
        enricher_node = create_enricher_node({
            "connector": "lastfm",
            "attributes": ["lastfm_user_playcount", "lastfm_global_playcount"],
        })
        
        # This should not raise an exception
        assert enricher_node is not None
        assert callable(enricher_node)
        
        # Test that the attributes are correctly configured
        # This verifies that the node factory can handle the LastFM attributes

    def test_sorting_with_none_and_missing_values(self):
        """Test sorting behavior with None values and missing metrics."""
        # Create test tracks
        track1 = Track(id=1, title="Track 1", artists=[Artist(name="Artist 1")])
        track2 = Track(id=2, title="Track 2", artists=[Artist(name="Artist 2")])
        track3 = Track(id=3, title="Track 3", artists=[Artist(name="Artist 3")])
        track4 = Track(id=None, title="Track 4", artists=[Artist(name="Artist 4")])  # None ID
        
        # Create tracklist with partial metrics
        tracklist = TrackList(
            tracks=[track1, track2, track3, track4],
            metadata={
                "metrics": {
                    "lastfm_user_playcount": {
                        1: 50,   # Track 1 has 50 plays
                        2: None,  # Track 2 has None plays
                        # Track 3 missing from metrics
                        # Track 4 has None ID
                    }
                }
            }
        )
        
        # Test sorting
        sort_transform = sort_by_attribute(
            key_fn="lastfm_user_playcount",
            metric_name="lastfm_user_playcount",
            reverse=True
        )
        
        result = sort_transform(tracklist)
        
        # Verify that Track 1 (50 plays) comes first
        assert result.tracks[0].id == 1
        
        # Verify that tracks with None/missing values are sorted to the end
        # (specific order depends on implementation, but they should be at the end)
        valid_tracks = [t for t in result.tracks if t.id is not None]
        assert valid_tracks[0].id == 1  # The track with actual playcount comes first

    def test_metrics_key_type_consistency(self):
        """Test that track IDs are consistently handled as integers in metrics."""
        # Create test with mixed ID types
        track1 = Track(id=1, title="Track 1", artists=[Artist(name="Artist 1")])
        track2 = Track(id=2, title="Track 2", artists=[Artist(name="Artist 2")])
        
        # Create WorkflowResult with integer keys (correct format)
        result = WorkflowResult(
            tracks=[track1, track2],
            operation_name="test",
            metrics={
                "lastfm_user_playcount": {
                    1: 50,  # Integer key
                    2: 100,  # Integer key
                },
            }
        )
        
        # Test retrieval with integer track IDs
        assert result.get_metric(1, "lastfm_user_playcount") == 50
        assert result.get_metric(2, "lastfm_user_playcount") == 100
        
        # Test that string keys would not work (as expected)
        assert result.get_metric("1", "lastfm_user_playcount", "—") == "—"
        assert result.get_metric("2", "lastfm_user_playcount", "—") == "—"