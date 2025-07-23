"""TDD tests for enricher key types - focused on the actual bug.

This test is designed to fail initially, showing that the enricher
stores metrics with string keys instead of integer keys.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from src.application.workflows.node_factories import create_enricher_node
from src.domain.entities.track import Artist, Track, TrackList


class TestEnricherKeyTypes:
    """Test that enricher stores metrics with correct key types."""

    @patch("src.infrastructure.persistence.database.db_connection.get_session")
    @patch("src.infrastructure.services.track_metadata_enricher.TrackMetadataEnricher")
    async def test_enricher_stores_integer_keys_not_string_keys(self, mock_enricher_class, mock_get_session):
        """Test that enricher stores metrics with integer keys, not string keys.
        
        This test should FAIL initially because the enricher currently
        stores string keys instead of integer keys.
        """
        # Mock database session
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__.return_value = mock_session
        mock_get_session.return_value.__aexit__.return_value = None
        
        # Create test tracks with integer IDs
        track1 = Track(id=1, title="Track 1", artists=[Artist(name="Artist 1")])
        track2 = Track(id=2, title="Track 2", artists=[Artist(name="Artist 2")])
        tracklist = TrackList(tracks=[track1, track2])
        
        # Create enriched tracklist with integer keys (what we expect)
        enriched_tracklist = TrackList(
            tracks=[track1, track2],
            metadata={
                "metrics": {
                    "lastfm_user_playcount": {
                        1: 75,   # Integer key
                        2: 125,  # Integer key
                    }
                }
            }
        )
        
        # Mock the enricher to return the expected result
        mock_enricher = AsyncMock()
        mock_enricher.enrich_tracks.return_value = (
            enriched_tracklist,
            {"lastfm_user_playcount": {1: 75, 2: 125}}
        )
        mock_enricher_class.return_value = mock_enricher
        
        # Create enricher node
        enricher_node = create_enricher_node({
            "connector": "lastfm",
            "attributes": ["lastfm_user_playcount"],
        })
        
        # Execute enricher (context, node_config) with shared session
        from src.application.workflows.context import create_workflow_context
        
        mock_session = MagicMock()
        workflow_context = create_workflow_context()
        context = {
            "tracklist": tracklist, 
            "shared_session": mock_session,
            "workflow_context": workflow_context
        }
        result = await enricher_node(context, {})
        
        # Check that metrics were stored
        enriched_tracklist = result["tracklist"]
        assert "metrics" in enriched_tracklist.metadata, "Enricher should store metrics"
        assert "lastfm_user_playcount" in enriched_tracklist.metadata["metrics"], "Should have user playcount"
        
        # Get the metrics dictionary
        user_playcount_metrics = enriched_tracklist.metadata["metrics"]["lastfm_user_playcount"]
        
        # Check that keys are integers (this should FAIL initially)
        keys = list(user_playcount_metrics.keys())
        assert len(keys) > 0, "Should have some metrics"
        
        # This is the critical test that should FAIL
        assert isinstance(keys[0], int), f"Metrics keys should be integers, got {type(keys[0])}: {keys[0]}"
        
        # Test that integer keys work for lookup
        assert user_playcount_metrics[1] == 75, "Track 1 should have 75 plays"
        assert user_playcount_metrics[2] == 125, "Track 2 should have 125 plays"
        
        # Test that string keys don't work (as they shouldn't)
        assert "1" not in user_playcount_metrics, "String keys should not exist"
        assert "2" not in user_playcount_metrics, "String keys should not exist"

    @patch("src.infrastructure.persistence.database.db_connection.get_session")
    @patch("src.infrastructure.services.track_metadata_enricher.TrackMetadataEnricher")
    async def test_enricher_with_string_keys_shows_bug(self, mock_enricher_class, mock_get_session):
        """Test that shows the bug when enricher returns string keys instead of integers.
        
        This simulates the actual bug in the system where track_id comes as a string
        from enricher, which then gets stored as a string key in the metrics.
        """
        # Mock database session
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__.return_value = mock_session
        mock_get_session.return_value.__aexit__.return_value = None
        
        # Create test tracks with integer IDs
        track1 = Track(id=1, title="Track 1", artists=[Artist(name="Artist 1")])
        track2 = Track(id=2, title="Track 2", artists=[Artist(name="Artist 2")])
        tracklist = TrackList(tracks=[track1, track2])
        
        # Create enriched tracklist with STRING keys (this is the bug!)
        enriched_tracklist = TrackList(
            tracks=[track1, track2],
            metadata={
                "metrics": {
                    "lastfm_user_playcount": {
                        "1": 75,   # STRING key (this is the bug!)
                        "2": 125,  # STRING key (this is the bug!)
                    }
                }
            }
        )
        
        # Mock the enricher to return the buggy result
        mock_enricher = AsyncMock()
        mock_enricher.enrich_tracks.return_value = (
            enriched_tracklist,
            {"lastfm_user_playcount": {"1": 75, "2": 125}}
        )
        mock_enricher_class.return_value = mock_enricher
        
        # Create enricher node
        enricher_node = create_enricher_node({
            "connector": "lastfm",
            "attributes": ["lastfm_user_playcount"],
        })
        
        # Execute enricher with shared session
        from src.application.workflows.context import create_workflow_context
        
        mock_session = MagicMock()
        workflow_context = create_workflow_context()
        context = {
            "tracklist": tracklist, 
            "shared_session": mock_session,
            "workflow_context": workflow_context
        }
        result = await enricher_node(context, {})
        
        # Check that metrics were stored
        enriched_tracklist = result["tracklist"]
        user_playcount_metrics = enriched_tracklist.metadata["metrics"]["lastfm_user_playcount"]
        
        # This exposes the bug - keys are strings, not integers
        keys = list(user_playcount_metrics.keys())
        assert len(keys) > 0, "Should have some metrics"
        
        # The bug: keys are strings when they should be integers
        # This causes the sorter to fail because it looks for integer keys
        assert isinstance(keys[0], str), f"Bug: keys are strings: {keys[0]} ({type(keys[0])})"
        
        # The sorter will fail because it tries to access metrics with integer track IDs
        # but metrics are stored with string keys
        assert user_playcount_metrics["1"] == 75, "Can access with string key"
        assert user_playcount_metrics["2"] == 125, "Can access with string key"
        
        # But integer keys don't work (this is the problem!)
        assert 1 not in user_playcount_metrics, "Integer keys don't work - this is the bug!"
        assert 2 not in user_playcount_metrics, "Integer keys don't work - this is the bug!"

    @patch("src.infrastructure.persistence.database.db_connection.get_session")
    @patch("src.infrastructure.services.track_metadata_enricher.TrackMetadataEnricher")
    async def test_enricher_with_none_track_id(self, mock_enricher_class, mock_get_session):
        """Test that enricher handles tracks with None ID gracefully."""
        # Mock database session
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__.return_value = mock_session
        mock_get_session.return_value.__aexit__.return_value = None
        
        # Create test tracks with None ID
        track1 = Track(id=None, title="Track 1", artists=[Artist(name="Artist 1")])
        track2 = Track(id=2, title="Track 2", artists=[Artist(name="Artist 2")])
        tracklist = TrackList(tracks=[track1, track2])
        
        # Create enriched tracklist with data for track 2 only
        enriched_tracklist = TrackList(
            tracks=[track1, track2],
            metadata={
                "metrics": {
                    "lastfm_user_playcount": {
                        2: 125,  # Only track 2 has data
                    }
                }
            }
        )
        
        # Mock the enricher to return data for track 2 only
        mock_enricher = AsyncMock()
        mock_enricher.enrich_tracks.return_value = (
            enriched_tracklist,
            {"lastfm_user_playcount": {2: 125}}
        )
        mock_enricher_class.return_value = mock_enricher
        
        # Create enricher node
        enricher_node = create_enricher_node({
            "connector": "lastfm",
            "attributes": ["lastfm_user_playcount"],
        })
        
        # Execute enricher (context, node_config) with shared session
        from src.application.workflows.context import create_workflow_context
        
        mock_session = MagicMock()
        workflow_context = create_workflow_context()
        context = {
            "tracklist": tracklist, 
            "shared_session": mock_session,
            "workflow_context": workflow_context
        }
        result = await enricher_node(context, {})
        
        # Check that metrics were stored for track 2 only
        enriched_tracklist = result["tracklist"]
        user_playcount_metrics = enriched_tracklist.metadata["metrics"]["lastfm_user_playcount"]
        assert 2 in user_playcount_metrics, "Track 2 should have metrics"
        assert user_playcount_metrics[2] == 125, "Track 2 should have 125 plays"
        
        # Track 1 (None ID) should not have metrics
        assert None not in user_playcount_metrics, "None ID should not be in metrics"