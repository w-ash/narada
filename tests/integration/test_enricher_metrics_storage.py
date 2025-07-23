"""Tests for enricher metrics storage focusing on key contracts.

These tests verify that the enricher properly stores metrics with integer keys
and handles various data format scenarios correctly.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.entities.track import Artist, Track, TrackList
from src.infrastructure.services.track_metadata_enricher import TrackMetadataEnricher


class TestEnricherMetricsStorage:
    """Test enricher metrics storage with focus on data contracts."""

    @pytest.fixture
    def mock_track_repos(self):
        """Create mock track repositories."""
        repos = MagicMock()
        repos.track = AsyncMock()
        repos.connector = AsyncMock()
        repos.metrics = AsyncMock()
        repos.likes = AsyncMock()
        repos.plays = AsyncMock()
        repos.sync = AsyncMock()
        return repos

    @pytest.fixture
    def sample_tracks(self):
        """Create sample tracks for testing."""
        track1 = Track(id=1, title="Track 1", artists=[Artist(name="Artist 1")])
        track2 = Track(id=2, title="Track 2", artists=[Artist(name="Artist 2")])
        return [track1, track2]

    @pytest.fixture
    def sample_tracklist(self, sample_tracks):
        """Create sample tracklist for testing."""
        return TrackList(tracks=sample_tracks)

    async def test_enricher_stores_metrics_with_integer_keys(self, mock_track_repos, sample_tracklist):
        """Test that enricher stores metrics with integer track IDs as keys."""
        # Create enricher instance
        enricher = TrackMetadataEnricher(mock_track_repos)
        
        # Mock connector instance with expected interface
        mock_connector = AsyncMock()
        
        # Use actual LastFM extractors that can handle MatchResult objects
        from src.infrastructure.connectors.lastfm import get_connector_config
        lastfm_config = get_connector_config()
        extractors = {
            "lastfm_user_playcount": lastfm_config["extractors"]["lastfm_user_playcount"],
            "lastfm_global_playcount": lastfm_config["extractors"]["lastfm_global_playcount"],
        }
        
        # Mock the track metadata enricher dependencies
        with patch.object(enricher, 'identity_resolver') as mock_resolver, \
             patch.object(enricher, 'freshness_controller') as mock_freshness, \
             patch.object(enricher, 'metadata_manager') as mock_metadata_mgr:
            
            # Setup identity resolution mock - tracks already have identities
            from src.domain.matching.types import MatchResult
            track1, track2 = sample_tracklist.tracks
            mock_resolver.resolve_track_identities = AsyncMock(return_value={
                1: MatchResult(
                    track=track1,
                    success=True,
                    connector_id="lastfm_track_1",
                    confidence=95,
                    match_method="direct",
                    service_data={"lastfm_user_playcount": 75, "lastfm_global_playcount": 1500},
                    evidence={}
                ),
                2: MatchResult(
                    track=track2,
                    success=True,
                    connector_id="lastfm_track_2",
                    confidence=95,
                    match_method="direct",
                    service_data={"lastfm_user_playcount": 125, "lastfm_global_playcount": 2500},
                    evidence={}
                )
            })
            
            # Mock freshness controller - all tracks need refresh
            mock_freshness.get_stale_tracks = AsyncMock(return_value=[1, 2])
            
            # Mock metadata manager - return fresh metadata (tuple of dict and set)
            mock_metadata_mgr.fetch_fresh_metadata = AsyncMock(return_value=({
                1: {"lastfm_user_playcount": 75, "lastfm_global_playcount": 1500},
                2: {"lastfm_user_playcount": 125, "lastfm_global_playcount": 2500}
            }, set()))
            mock_metadata_mgr.get_all_metadata = AsyncMock(return_value={
                1: {"lastfm_user_playcount": 75, "lastfm_global_playcount": 1500},
                2: {"lastfm_user_playcount": 125, "lastfm_global_playcount": 2500}
            })
            
            # Execute enrichment
            _enriched_tracklist, metrics = await enricher.enrich_tracks(
                sample_tracklist,
                "lastfm", 
                mock_connector,
                extractors,
                max_age_hours=1.0
            )
            
            # Verify metrics are returned with integer keys
            assert "lastfm_user_playcount" in metrics, "Should have user playcount metrics"
            assert "lastfm_global_playcount" in metrics, "Should have global playcount metrics"
            
            # CRITICAL: Test that keys are integers, not strings
            user_playcount_metrics = metrics["lastfm_user_playcount"]
            global_playcount_metrics = metrics["lastfm_global_playcount"]
            
            assert isinstance(next(iter(user_playcount_metrics.keys())), int), \
                "Metrics keys should be integers, not strings"
            assert isinstance(next(iter(global_playcount_metrics.keys())), int), \
                "Metrics keys should be integers, not strings"
            
            # Test that integer keys work for lookup
            assert user_playcount_metrics[1] == 75, "Track 1 should have 75 user plays"
            assert user_playcount_metrics[2] == 125, "Track 2 should have 125 user plays"
            assert global_playcount_metrics[1] == 1500, "Track 1 should have 1500 global plays"
            assert global_playcount_metrics[2] == 2500, "Track 2 should have 2500 global plays"

    async def test_enricher_handles_missing_metrics_gracefully(self, mock_track_repos, sample_tracks):
        """Test that enricher handles tracks with missing metrics properly."""
        # Create tracklist with tracks that will have mixed results
        tracklist = TrackList(tracks=sample_tracks)
        enricher = TrackMetadataEnricher(mock_track_repos)
        
        mock_connector = AsyncMock()
        from src.infrastructure.connectors.lastfm import get_connector_config
        lastfm_config = get_connector_config()
        extractors = {"lastfm_user_playcount": lastfm_config["extractors"]["lastfm_user_playcount"]}
        
        with patch.object(enricher, 'identity_resolver') as mock_resolver, \
             patch.object(enricher, 'freshness_controller') as mock_freshness, \
             patch.object(enricher, 'metadata_manager') as mock_metadata_mgr:
            
            # Setup identity resolution - track 1 has data, track 2 doesn't
            from src.domain.matching.types import MatchResult
            track1, track2 = sample_tracks
            mock_resolver.resolve_track_identities = AsyncMock(return_value={
                1: MatchResult(
                    track=track1, success=True, connector_id="lastfm_track_1",
                    confidence=95, match_method="direct",
                    service_data={"lastfm_user_playcount": 75}, evidence={}
                ),
                2: MatchResult(
                    track=track2, success=True, connector_id="lastfm_track_2", 
                    confidence=95, match_method="direct",
                    service_data={}, evidence={}  # No metrics data
                )
            })
            
            mock_freshness.get_stale_tracks = AsyncMock(return_value=[1, 2])
            mock_metadata_mgr.fetch_fresh_metadata = AsyncMock(return_value=({
                1: {"lastfm_user_playcount": 75},
                # Track 2 has no metadata
            }, set()))
            mock_metadata_mgr.get_all_metadata = AsyncMock(return_value={
                1: {"lastfm_user_playcount": 75},
            })
            
            # Execute enrichment
            _enriched_tracklist, metrics = await enricher.enrich_tracks(
                tracklist, "lastfm", mock_connector, extractors, max_age_hours=1.0
            )
            
            # Should have metrics for track 1 only
            assert "lastfm_user_playcount" in metrics
            user_playcount_metrics = metrics["lastfm_user_playcount"]
            
            # Track 1 should have data
            assert 1 in user_playcount_metrics, "Track 1 should have metrics"
            assert user_playcount_metrics[1] == 75, "Track 1 should have 75 plays"
            
            # Track 2 should not have data
            assert 2 not in user_playcount_metrics, "Track 2 should not have metrics"

    async def test_enricher_preserves_existing_metrics(self, mock_track_repos):
        """Test that enricher preserves existing metrics while adding new ones."""
        # Create tracklist with existing metrics
        track = Track(id=1, title="Track 1", artists=[Artist(name="Artist 1")])
        tracklist = TrackList(
            tracks=[track],
            metadata={"metrics": {"existing_metric": {1: "existing_value"}}}
        )
        
        enricher = TrackMetadataEnricher(mock_track_repos)
        mock_connector = AsyncMock()
        from src.infrastructure.connectors.lastfm import get_connector_config
        lastfm_config = get_connector_config()
        extractors = {"lastfm_user_playcount": lastfm_config["extractors"]["lastfm_user_playcount"]}
        
        with patch.object(enricher, 'identity_resolver') as mock_resolver, \
             patch.object(enricher, 'freshness_controller') as mock_freshness, \
             patch.object(enricher, 'metadata_manager') as mock_metadata_mgr:
            
            from src.domain.matching.types import MatchResult
            mock_resolver.resolve_track_identities = AsyncMock(return_value={
                1: MatchResult(
                    track=track, success=True, connector_id="lastfm_track_1",
                    confidence=95, match_method="direct",
                    service_data={"lastfm_user_playcount": 75}, evidence={}
                )
            })
            
            mock_freshness.get_stale_tracks = AsyncMock(return_value=[1])
            mock_metadata_mgr.fetch_fresh_metadata = AsyncMock(return_value=({
                1: {"lastfm_user_playcount": 75}
            }, set()))
            mock_metadata_mgr.get_all_metadata = AsyncMock(return_value={
                1: {"lastfm_user_playcount": 75}
            })
            
            # Execute enrichment
            enriched_tracklist, metrics = await enricher.enrich_tracks(
                tracklist, "lastfm", mock_connector, extractors, max_age_hours=1.0
            )
            
            # Should preserve existing metrics in tracklist
            assert "existing_metric" in enriched_tracklist.metadata["metrics"], \
                "Should preserve existing metrics"
            assert enriched_tracklist.metadata["metrics"]["existing_metric"][1] == "existing_value", \
                "Should preserve existing metric values"
            
            # Should add new metrics to returned metrics dict
            assert "lastfm_user_playcount" in metrics, "Should add new LastFM metrics"
            assert metrics["lastfm_user_playcount"][1] == 75, "Should add new metric values"