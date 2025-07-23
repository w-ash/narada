"""Integration tests for rate limiting and cached metadata fallback.

These tests verify that the LastFM rate limiting fixes work correctly and 
preserve data when fresh fetches fail. They test the core issue where tracks
were losing metadata during rate limiting scenarios.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.entities.track import Artist, Track
from src.domain.matching.types import MatchResult
from src.infrastructure.services.connector_metadata_manager import (
    ConnectorMetadataManager,
)


class TestRateLimitingFallback:
    """Test rate limiting behavior and cached metadata fallback."""

    @pytest.fixture
    def mock_track_repos(self):
        """Create mock track repositories."""
        repos = MagicMock()
        repos.connector = AsyncMock()
        repos.metrics = AsyncMock() 
        repos.core = AsyncMock()
        return repos

    @pytest.fixture
    def metadata_manager(self, mock_track_repos):
        """Create metadata manager instance."""
        return ConnectorMetadataManager(track_repos=mock_track_repos)

    @pytest.fixture
    def sample_tracks(self):
        """Create sample tracks for testing."""
        return [
            Track(id=1, title="Track 1", artists=[Artist(name="Artist 1")]),
            Track(id=2, title="Track 2", artists=[Artist(name="Artist 2")]), 
            Track(id=3, title="Track 3", artists=[Artist(name="Artist 3")]),
            Track(id=4, title="Track 4", artists=[Artist(name="Artist 4")]),
            Track(id=5, title="Track 5", artists=[Artist(name="Artist 5")]),
        ]

    @pytest.fixture
    def identity_mappings(self, sample_tracks):
        """Create identity mappings for tracks."""
        return {
            track.id: MatchResult(
                track=track,
                success=True,
                connector_id=f"lastfm_track_{track.id}",
                confidence=90,
                match_method="artist_title",
                service_data={}
            )
            for track in sample_tracks
        }

    async def test_partial_fetch_failure_preserves_cached_data(
        self, metadata_manager, identity_mappings, mock_track_repos
    ):
        """Test that partial fresh fetch failures preserve cached metadata."""
        track_ids = [1, 2, 3, 4, 5]
        
        # Mock existing cached metadata for all tracks
        cached_metadata = {
            1: {"lastfm_user_playcount": 10, "lastfm_global_playcount": 1000},
            2: {"lastfm_user_playcount": 5, "lastfm_global_playcount": 500}, 
            3: {"lastfm_user_playcount": 15, "lastfm_global_playcount": 1500},
            4: {"lastfm_user_playcount": 8, "lastfm_global_playcount": 800},
            5: {"lastfm_user_playcount": 12, "lastfm_global_playcount": 1200},
        }
        mock_track_repos.connector.get_connector_metadata.return_value = cached_metadata
        
        # Mock partial success: tracks 1,2 succeed, tracks 3,4,5 fail due to rate limiting
        fresh_metadata_partial = {
            1: {"lastfm_user_playcount": 20, "lastfm_global_playcount": 2000},
            2: {"lastfm_user_playcount": 25, "lastfm_global_playcount": 2500},
        }
        
        with patch.object(
            metadata_manager, '_fetch_direct_metadata_by_connector_ids', 
            return_value=fresh_metadata_partial
        ):
            # Call fetch_fresh_metadata 
            fresh_metadata, failed_track_ids = await metadata_manager.fetch_fresh_metadata(
                identity_mappings,
                "lastfm", 
                MagicMock(),
                track_ids
            )
            
            # Verify fresh fetch results
            assert fresh_metadata == fresh_metadata_partial
            assert failed_track_ids == {3, 4, 5}  # These failed fresh fetch
            
            # Now test get_all_metadata with fallback
            all_metadata = await metadata_manager.get_all_metadata(
                track_ids, "lastfm", fresh_metadata, failed_track_ids
            )
            
            # Verify all tracks have metadata (no data loss)
            assert len(all_metadata) == 5
            
            # Verify fresh data is used for successful tracks
            assert all_metadata[1]["lastfm_user_playcount"] == 20  # Fresh data
            assert all_metadata[2]["lastfm_user_playcount"] == 25  # Fresh data
            
            # Verify cached data is preserved for failed tracks 
            assert all_metadata[3]["lastfm_user_playcount"] == 15  # Cached data
            assert all_metadata[4]["lastfm_user_playcount"] == 8   # Cached data
            assert all_metadata[5]["lastfm_user_playcount"] == 12  # Cached data

    async def test_complete_fresh_fetch_failure_uses_all_cached(
        self, metadata_manager, identity_mappings, mock_track_repos
    ):
        """Test that complete fresh fetch failure falls back to all cached metadata."""
        track_ids = [1, 2, 3]
        
        # Mock existing cached metadata
        cached_metadata = {
            1: {"lastfm_user_playcount": 10, "lastfm_global_playcount": 1000},
            2: {"lastfm_user_playcount": 5, "lastfm_global_playcount": 500}, 
            3: {"lastfm_user_playcount": 15, "lastfm_global_playcount": 1500},
        }
        mock_track_repos.connector.get_connector_metadata.return_value = cached_metadata
        
        # Mock complete failure (empty fresh metadata)
        with patch.object(
            metadata_manager, '_fetch_direct_metadata_by_connector_ids', 
            return_value={}
        ):
            fresh_metadata, failed_track_ids = await metadata_manager.fetch_fresh_metadata(
                identity_mappings,
                "lastfm",
                MagicMock(), 
                track_ids
            )
            
            # Verify all tracks failed fresh fetch
            assert fresh_metadata == {}
            assert failed_track_ids == {1, 2, 3}
            
            # Test fallback to cached metadata
            all_metadata = await metadata_manager.get_all_metadata(
                track_ids, "lastfm", fresh_metadata, failed_track_ids
            )
            
            # Verify all cached data is preserved
            assert all_metadata == cached_metadata
            assert len(all_metadata) == 3

    async def test_no_cached_data_for_failed_tracks(
        self, metadata_manager, identity_mappings, mock_track_repos
    ):
        """Test behavior when failed tracks have no cached metadata."""
        track_ids = [1, 2, 3]
        
        # Mock cached metadata for only some tracks
        cached_metadata = {
            1: {"lastfm_user_playcount": 10, "lastfm_global_playcount": 1000},
            # Track 2 and 3 have no cached data
        }
        mock_track_repos.connector.get_connector_metadata.return_value = cached_metadata
        
        # Mock partial success: only track 1 succeeds fresh fetch
        fresh_metadata_partial = {
            1: {"lastfm_user_playcount": 20, "lastfm_global_playcount": 2000},
        }
        
        with patch.object(
            metadata_manager, '_fetch_direct_metadata_by_connector_ids',
            return_value=fresh_metadata_partial
        ):
            fresh_metadata, failed_track_ids = await metadata_manager.fetch_fresh_metadata(
                identity_mappings,
                "lastfm",
                MagicMock(),
                track_ids
            )
            
            # Verify results
            assert failed_track_ids == {2, 3}
            
            all_metadata = await metadata_manager.get_all_metadata(
                track_ids, "lastfm", fresh_metadata, failed_track_ids
            )
            
            # Should have fresh data for track 1, no data for tracks 2,3
            assert len(all_metadata) == 1
            assert 1 in all_metadata
            assert all_metadata[1]["lastfm_user_playcount"] == 20  # Fresh data
            assert 2 not in all_metadata  # No cached or fresh data
            assert 3 not in all_metadata  # No cached or fresh data

