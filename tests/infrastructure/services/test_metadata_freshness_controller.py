"""Tests for MetadataFreshnessController service."""

import pytest
from datetime import datetime, timedelta, UTC
from unittest.mock import AsyncMock, Mock, patch

from src.infrastructure.services.metadata_freshness_controller import MetadataFreshnessController
from src.infrastructure.persistence.repositories.track import TrackRepositories


@pytest.fixture
def mock_track_repos():
    """Create mock track repositories."""
    repos = Mock(spec=TrackRepositories)
    repos.connector = AsyncMock()
    return repos


@pytest.fixture
def freshness_controller(mock_track_repos):
    """Create MetadataFreshnessController instance."""
    return MetadataFreshnessController(mock_track_repos)


class TestMetadataFreshnessController:
    """Test cases for MetadataFreshnessController service."""

    @pytest.mark.asyncio
    async def test_get_stale_tracks_with_stale_metadata(self, freshness_controller, mock_track_repos):
        """Test identifying stale tracks based on timestamp."""
        # Setup: Current time and cutoff time (2 hours ago)
        current_time = datetime.now(UTC)
        max_age_hours = 2.0
        cutoff_time = current_time - timedelta(hours=max_age_hours)
        
        # Mock metadata with timestamps
        metadata_with_timestamps = {
            1: {"last_updated": current_time - timedelta(hours=3)},  # Stale (3 hours old)
            2: {"last_updated": current_time - timedelta(hours=1)},  # Fresh (1 hour old)
            3: {"last_updated": current_time - timedelta(hours=5)},  # Stale (5 hours old)
            4: {"last_updated": None},  # No timestamp (considered stale)
        }
        mock_track_repos.connector.get_connector_metadata_with_timestamps.return_value = metadata_with_timestamps

        # Execute
        with patch('src.infrastructure.services.metadata_freshness_controller.datetime') as mock_datetime:
            mock_datetime.now.return_value = current_time
            
            stale_tracks = await freshness_controller.get_stale_tracks(
                [1, 2, 3, 4], "lastfm", max_age_hours
            )

        # Verify: Tracks 1, 3, and 4 should be stale
        assert set(stale_tracks) == {1, 3, 4}

    @pytest.mark.asyncio
    async def test_get_stale_tracks_all_fresh(self, freshness_controller, mock_track_repos):
        """Test when all tracks have fresh metadata."""
        current_time = datetime.now(UTC)
        max_age_hours = 2.0
        
        # All metadata is fresh (within 2 hours)
        metadata_with_timestamps = {
            1: {"last_updated": current_time - timedelta(minutes=30)},
            2: {"last_updated": current_time - timedelta(hours=1)},
            3: {"last_updated": current_time - timedelta(minutes=90)},
        }
        mock_track_repos.connector.get_connector_metadata_with_timestamps.return_value = metadata_with_timestamps

        # Execute
        with patch('src.infrastructure.services.metadata_freshness_controller.datetime') as mock_datetime:
            mock_datetime.now.return_value = current_time
            
            stale_tracks = await freshness_controller.get_stale_tracks(
                [1, 2, 3], "lastfm", max_age_hours
            )

        # Verify: No tracks should be stale
        assert stale_tracks == []

    @pytest.mark.asyncio
    async def test_get_stale_tracks_no_existing_metadata(self, freshness_controller, mock_track_repos):
        """Test when tracks have no existing metadata."""
        # Setup: No metadata exists for any tracks
        mock_track_repos.connector.get_connector_metadata_with_timestamps.return_value = {}

        # Execute
        stale_tracks = await freshness_controller.get_stale_tracks(
            [1, 2, 3], "lastfm", 1.0
        )

        # Verify: All tracks should be considered stale
        assert set(stale_tracks) == {1, 2, 3}

    @pytest.mark.asyncio
    async def test_get_stale_tracks_timezone_handling(self, freshness_controller, mock_track_repos):
        """Test proper handling of timezone-naive timestamps."""
        current_time = datetime.now(UTC)
        max_age_hours = 1.0
        
        # Mix of timezone-aware and naive timestamps
        # Use a naive timestamp that's definitely old (2 hours ago)
        naive_timestamp = datetime(2025, 7, 18, 4, 0, 0)  # Naive datetime, old
        aware_timestamp = current_time - timedelta(minutes=30)  # Aware datetime, recent
        
        metadata_with_timestamps = {
            1: {"last_updated": naive_timestamp},  # Naive - should be converted to UTC and be stale
            2: {"last_updated": aware_timestamp},  # Aware - should work as-is and be fresh
        }
        mock_track_repos.connector.get_connector_metadata_with_timestamps.return_value = metadata_with_timestamps

        # Execute
        with patch('src.infrastructure.services.metadata_freshness_controller.datetime') as mock_datetime:
            mock_datetime.now.return_value = current_time
            
            stale_tracks = await freshness_controller.get_stale_tracks(
                [1, 2], "lastfm", max_age_hours
            )

        # Verify: Naive timestamp should be handled properly
        # Track 1 (naive, old) should be stale, Track 2 (aware, recent) should be fresh
        assert 1 in stale_tracks  # Old naive timestamp
        assert 2 not in stale_tracks  # Recent aware timestamp

    @pytest.mark.asyncio
    async def test_get_stale_tracks_edge_case_exact_cutoff(self, freshness_controller, mock_track_repos):
        """Test behavior when timestamp exactly matches cutoff time."""
        current_time = datetime.now(UTC)
        max_age_hours = 2.0
        exact_cutoff_time = current_time - timedelta(hours=max_age_hours)
        
        metadata_with_timestamps = {
            1: {"last_updated": exact_cutoff_time},  # Exactly at cutoff
            2: {"last_updated": exact_cutoff_time + timedelta(seconds=1)},  # Just fresh
            3: {"last_updated": exact_cutoff_time - timedelta(seconds=1)},  # Just stale
        }
        mock_track_repos.connector.get_connector_metadata_with_timestamps.return_value = metadata_with_timestamps

        # Execute
        with patch('src.infrastructure.services.metadata_freshness_controller.datetime') as mock_datetime:
            mock_datetime.now.return_value = current_time
            
            stale_tracks = await freshness_controller.get_stale_tracks(
                [1, 2, 3], "lastfm", max_age_hours
            )

        # Verify: Only tracks strictly before cutoff should be stale (< cutoff, not <= cutoff)
        assert set(stale_tracks) == {3}  # Only track 3 (1 second before cutoff)
        assert 1 not in stale_tracks  # Track 1 (exactly at cutoff) is fresh
        assert 2 not in stale_tracks  # Track 2 (after cutoff) is fresh

    @pytest.mark.asyncio
    async def test_get_stale_tracks_empty_track_list(self, freshness_controller, mock_track_repos):
        """Test with empty track list."""
        stale_tracks = await freshness_controller.get_stale_tracks(
            [], "lastfm", 1.0
        )

        assert stale_tracks == []
        mock_track_repos.connector.get_connector_metadata_with_timestamps.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_stale_tracks_zero_max_age(self, freshness_controller, mock_track_repos):
        """Test with zero max age (all tracks should be stale)."""
        current_time = datetime.now(UTC)
        
        # Even very recent metadata should be stale with max_age=0
        metadata_with_timestamps = {
            1: {"last_updated": current_time - timedelta(seconds=1)},
            2: {"last_updated": current_time},  # Even current time should be stale
        }
        mock_track_repos.connector.get_connector_metadata_with_timestamps.return_value = metadata_with_timestamps

        # Execute
        with patch('src.infrastructure.services.metadata_freshness_controller.datetime') as mock_datetime:
            mock_datetime.now.return_value = current_time
            
            stale_tracks = await freshness_controller.get_stale_tracks(
                [1, 2], "lastfm", 0.0
            )

        # Verify: Only track 1 should be stale (track 2 exactly at current time is fresh)
        assert set(stale_tracks) == {1}

    @pytest.mark.asyncio
    async def test_get_stale_tracks_with_config_override(self, freshness_controller, mock_track_repos):
        """Test using configuration for different connectors."""
        # This test verifies the freshness controller uses the max_age_hours parameter
        # rather than looking up connector-specific config (that's the caller's responsibility)
        
        current_time = datetime.now(UTC)
        
        metadata_with_timestamps = {
            1: {"last_updated": current_time - timedelta(hours=2)},  # 2 hours old
        }
        mock_track_repos.connector.get_connector_metadata_with_timestamps.return_value = metadata_with_timestamps

        # Execute with different max_age values
        with patch('src.infrastructure.services.metadata_freshness_controller.datetime') as mock_datetime:
            mock_datetime.now.return_value = current_time
            
            # With 3 hour limit - should be fresh
            fresh_result = await freshness_controller.get_stale_tracks([1], "lastfm", 3.0)
            
            # With 1 hour limit - should be stale
            stale_result = await freshness_controller.get_stale_tracks([1], "lastfm", 1.0)

        # Verify: Same track, different results based on max_age parameter
        assert fresh_result == []
        assert stale_result == [1]