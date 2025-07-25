"""Tests for MetadataFreshnessController service."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.domain.repositories.interfaces import ConnectorRepositoryProtocol
from src.infrastructure.services.metadata_freshness_controller import (
    MetadataFreshnessController,
)


@pytest.fixture
def mock_connector_repo():
    """Create mock connector repository."""
    return AsyncMock(spec=ConnectorRepositoryProtocol)


@pytest.fixture
def freshness_controller(mock_connector_repo):
    """Create MetadataFreshnessController instance."""
    return MetadataFreshnessController(mock_connector_repo)


class TestMetadataFreshnessController:
    """Test cases for MetadataFreshnessController service."""

    @pytest.mark.asyncio
    async def test_get_stale_tracks_with_stale_metadata(self, freshness_controller, mock_connector_repo):
        """Test identifying stale tracks based on metrics timestamp."""
        # Setup: Current time and cutoff time (2 hours ago)
        current_time = datetime.now(UTC)
        max_age_hours = 2.0
        current_time - timedelta(hours=max_age_hours)
        
        # Mock metrics timestamps (now used for freshness checking)
        metrics_timestamps = {
            1: current_time - timedelta(hours=3),  # Stale (3 hours old)
            2: current_time - timedelta(hours=1),  # Fresh (1 hour old)  
            3: current_time - timedelta(hours=5),  # Stale (5 hours old)
            # Track 4 has no metrics timestamp (considered stale)
        }
        
        # Mock the connector repository's get_metadata_timestamps method
        mock_connector_repo.get_metadata_timestamps = AsyncMock(return_value=metrics_timestamps)
        
        with patch('src.infrastructure.services.metadata_freshness_controller.datetime') as mock_datetime:
            mock_datetime.now.return_value = current_time
            
            stale_tracks = await freshness_controller.get_stale_tracks(
                [1, 2, 3, 4], "lastfm", max_age_hours
            )

        # Verify: Tracks 1, 3, and 4 should be stale
        assert set(stale_tracks) == {1, 3, 4}

    @pytest.mark.asyncio
    async def test_get_stale_tracks_all_fresh(self, freshness_controller, mock_connector_repo):
        """Test when all tracks have fresh metrics."""
        current_time = datetime.now(UTC)
        max_age_hours = 2.0
        
        # All metrics are fresh (within 2 hours)
        metrics_timestamps = {
            1: current_time - timedelta(minutes=30),
            2: current_time - timedelta(hours=1),
            3: current_time - timedelta(minutes=90),
        }
        
        # Mock the connector repository's get_metadata_timestamps method
        mock_connector_repo.get_metadata_timestamps = AsyncMock(return_value=metrics_timestamps)
        with patch('src.infrastructure.services.metadata_freshness_controller.datetime') as mock_datetime:
                mock_datetime.now.return_value = current_time
                
                stale_tracks = await freshness_controller.get_stale_tracks(
                    [1, 2, 3], "lastfm", max_age_hours
                )

        # Verify: No tracks should be stale
        assert stale_tracks == []

    @pytest.mark.asyncio
    async def test_get_stale_tracks_no_existing_metadata(self, freshness_controller, mock_connector_repo):
        """Test when tracks have no existing metrics."""
        # Setup: No metrics exist for any tracks
        metrics_timestamps = {}
        
        # Mock the connector repository's get_metadata_timestamps method
        mock_connector_repo.get_metadata_timestamps = AsyncMock(return_value=metrics_timestamps)
        
        stale_tracks = await freshness_controller.get_stale_tracks(
            [1, 2, 3], "lastfm", 1.0
        )

        # Verify: All tracks should be considered stale
        assert set(stale_tracks) == {1, 2, 3}

    @pytest.mark.asyncio
    async def test_get_stale_tracks_timezone_handling(self, freshness_controller, mock_connector_repo):
        """Test proper handling of timezone-naive metrics timestamps."""
        current_time = datetime.now(UTC)
        max_age_hours = 1.0
        
        # Mix of timezone-aware and naive timestamps
        # Use a naive timestamp that's definitely old (2 hours ago)
        naive_timestamp = datetime(2025, 7, 18, 4, 0, 0)  # Naive datetime, old
        aware_timestamp = current_time - timedelta(minutes=30)  # Aware datetime, recent
        
        metrics_timestamps = {
            1: naive_timestamp,  # Naive - should be converted to UTC and be stale
            2: aware_timestamp,  # Aware - should work as-is and be fresh
        }
        
        # Mock the connector repository's get_metadata_timestamps method
        mock_connector_repo.get_metadata_timestamps = AsyncMock(return_value=metrics_timestamps)
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
    async def test_get_stale_tracks_edge_case_exact_cutoff(self, freshness_controller, mock_connector_repo):
        """Test behavior when metrics timestamp exactly matches cutoff time."""
        current_time = datetime.now(UTC)
        max_age_hours = 2.0
        exact_cutoff_time = current_time - timedelta(hours=max_age_hours)
        
        metrics_timestamps = {
            1: exact_cutoff_time,  # Exactly at cutoff
            2: exact_cutoff_time + timedelta(seconds=1),  # Just fresh
            3: exact_cutoff_time - timedelta(seconds=1),  # Just stale
        }
        
        # Mock the connector repository's get_metadata_timestamps method
        mock_connector_repo.get_metadata_timestamps = AsyncMock(return_value=metrics_timestamps)
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
    async def test_get_stale_tracks_empty_track_list(self, freshness_controller, mock_connector_repo):
        """Test with empty track list."""
        stale_tracks = await freshness_controller.get_stale_tracks(
            [], "lastfm", 1.0
        )

        assert stale_tracks == []

    @pytest.mark.asyncio
    async def test_get_stale_tracks_zero_max_age(self, freshness_controller, mock_connector_repo):
        """Test with zero max age (all tracks should be stale)."""
        current_time = datetime.now(UTC)
        
        # Even very recent metrics should be stale with max_age=0
        metrics_timestamps = {
            1: current_time - timedelta(seconds=1),
            2: current_time,  # Even current time should be stale
        }
        
        # Mock the connector repository's get_metadata_timestamps method
        mock_connector_repo.get_metadata_timestamps = AsyncMock(return_value=metrics_timestamps)
        with patch('src.infrastructure.services.metadata_freshness_controller.datetime') as mock_datetime:
                mock_datetime.now.return_value = current_time
                
                stale_tracks = await freshness_controller.get_stale_tracks(
                    [1, 2], "lastfm", 0.0
                )

        # Verify: Only track 1 should be stale (track 2 exactly at current time is fresh)
        assert set(stale_tracks) == {1}

    @pytest.mark.asyncio
    async def test_get_stale_tracks_with_config_override(self, freshness_controller, mock_connector_repo):
        """Test using configuration for different connectors."""
        # This test verifies the freshness controller uses the max_age_hours parameter
        # rather than looking up connector-specific config (that's the caller's responsibility)
        
        current_time = datetime.now(UTC)
        
        metrics_timestamps = {
            1: current_time - timedelta(hours=2),  # 2 hours old
        }
        
        # Mock the connector repository's get_metadata_timestamps method for both calls
        mock_connector_repo.get_metadata_timestamps = AsyncMock(return_value=metrics_timestamps)
        with patch('src.infrastructure.services.metadata_freshness_controller.datetime') as mock_datetime:
                mock_datetime.now.return_value = current_time
                
                # With 3 hour limit - should be fresh
                fresh_result = await freshness_controller.get_stale_tracks([1], "lastfm", 3.0)
                
                # With 1 hour limit - should be stale
                stale_result = await freshness_controller.get_stale_tracks([1], "lastfm", 1.0)

        # Verify: Same track, different results based on max_age parameter
        assert fresh_result == []
        assert stale_result == [1]