"""Tests for LastfmImportService."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest

from src.domain.entities import (
    Artist,
    OperationResult,
    PlayRecord,
    SyncCheckpoint,
    Track,
    TrackPlay,
)
from src.infrastructure.services.lastfm_import import LastfmImportService


class TestLastfmImportService:
    """Test suite for LastfmImportService."""

    @pytest.fixture
    def mock_repositories(self):
        """Mock track repositories."""
        repositories = Mock()
        repositories.plays = AsyncMock()
        repositories.plays.bulk_insert_plays = AsyncMock(return_value=5)
        repositories.core = AsyncMock()
        repositories.connector = AsyncMock()
        repositories.checkpoints = AsyncMock()
        repositories.checkpoints.get_sync_checkpoint = AsyncMock(return_value=None)
        repositories.checkpoints.save_sync_checkpoint = AsyncMock()
        return repositories

    @pytest.fixture
    def mock_lastfm_connector(self):
        """Mock Last.fm connector."""
        connector = AsyncMock()
        return connector

    @pytest.fixture
    def service(self, mock_repositories, mock_lastfm_connector):
        """Create service instance with mocked dependencies."""
        return LastfmImportService(
            repositories=mock_repositories,
            lastfm_connector=mock_lastfm_connector
        )

    @pytest.fixture
    def sample_play_records(self):
        """Sample Last.fm play records."""
        return [
            PlayRecord(
                artist_name="Radiohead",
                track_name="Paranoid Android",
                played_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
                service="lastfm",
                album_name="OK Computer",
                service_metadata={
                    "lastfm_track_url": "https://www.last.fm/music/Radiohead/_/Paranoid+Android",
                    "mbid": "test-mbid-123"
                }
            ),
            PlayRecord(
                artist_name="The Beatles",
                track_name="Yesterday",
                played_at=datetime(2024, 1, 1, 11, 30, 0, tzinfo=UTC),
                service="lastfm",
                album_name="Help!",
                service_metadata={
                    "lastfm_track_url": "https://www.last.fm/music/The+Beatles/_/Yesterday"
                }
            )
        ]

    async def test_import_recent_plays_success(
        self, 
        service, 
        mock_lastfm_connector, 
        sample_play_records,
        mock_repositories
    ):
        """Test successful import of recent plays."""
        # Setup: Mock API response
        mock_lastfm_connector.get_recent_tracks.return_value = sample_play_records
        
        # Act: Import recent plays
        result = await service.import_recent_plays(limit=1000)
        
        # Assert: API called correctly
        mock_lastfm_connector.get_recent_tracks.assert_called_once_with(
            limit=200,  # API max per page
            page=1
        )
        
        # Assert: Plays were saved
        mock_repositories.plays.bulk_insert_plays.assert_called_once()
        saved_plays = mock_repositories.plays.bulk_insert_plays.call_args[0][0]
        assert len(saved_plays) == 2
        assert all(isinstance(play, TrackPlay) for play in saved_plays)
        
        # Assert: Result structure
        assert isinstance(result, OperationResult)
        assert result.operation_name == "Last.fm Recent Plays Import"
        assert result.plays_processed == 2
        assert result.imported_count == 5  # Mock return value

    async def test_import_recent_plays_pagination(
        self, 
        service, 
        mock_lastfm_connector, 
        sample_play_records
    ):
        """Test pagination when limit exceeds single page."""
        # Setup: Mock multiple pages with full page sizes to trigger pagination
        # Create records that fill pages (200 records each to trigger continuation)
        page1_records = sample_play_records * 100  # 200 records (full page)
        page2_records = sample_play_records[:1] * 100  # 100 records (partial page)
        
        mock_lastfm_connector.get_recent_tracks.side_effect = [
            page1_records,
            page2_records
        ]
        
        # Act: Import with limit requiring multiple pages
        result = await service.import_recent_plays(limit=400)  # 2 pages worth
        
        # Assert: Multiple API calls made (stops after partial page)
        assert mock_lastfm_connector.get_recent_tracks.call_count == 2
        
        # Verify call parameters
        calls = mock_lastfm_connector.get_recent_tracks.call_args_list
        assert calls[0][1] == {"limit": 200, "page": 1}
        assert calls[1][1] == {"limit": 200, "page": 2}
        
        # Assert: All records processed (300 total records)
        assert result.plays_processed == 300

    async def test_import_recent_plays_empty_response(
        self, 
        service, 
        mock_lastfm_connector,
        mock_repositories
    ):
        """Test handling of empty API response."""
        # Setup: Mock empty response
        mock_lastfm_connector.get_recent_tracks.return_value = []
        
        # Act: Import recent plays
        result = await service.import_recent_plays(limit=1000)
        
        # Assert: No database operations
        mock_repositories.plays.bulk_insert_plays.assert_not_called()
        
        # Assert: Result reflects empty import
        assert result.plays_processed == 0
        assert result.imported_count == 0

    async def test_import_recent_plays_api_error(
        self, 
        service, 
        mock_lastfm_connector,
        mock_repositories
    ):
        """Test handling of API errors."""
        # Setup: Mock API error
        mock_lastfm_connector.get_recent_tracks.side_effect = Exception("API Error")
        
        # Act: Import should return error result, not raise
        result = await service.import_recent_plays(limit=1000)
        
        # Assert: Error result returned
        assert result.plays_processed == 0
        assert result.error_count == 1
        assert "API Error" in result.play_metrics["errors"][0]
        
        # Assert: No database operations attempted
        mock_repositories.plays.bulk_insert_plays.assert_not_called()

    async def test_import_recent_plays_with_track_resolution(
        self,
        service,
        mock_lastfm_connector,
        sample_play_records,
        mock_repositories
    ):
        """Test import with track resolution to existing tracks."""
        # Setup: Mock API response
        mock_lastfm_connector.get_recent_tracks.return_value = sample_play_records
        
        # Setup: Mock existing tracks that match our play records
        existing_track = Track(
            id=123,
            title="Paranoid Android", 
            artists=[Artist(name="Radiohead")],
            album="OK Computer"
        )
        
        # Mock track resolution - the service will try to resolve tracks
        mock_repositories.core.create_tracks_from_external_data = AsyncMock(
            return_value=[existing_track]
        )
        
        # Mock the play record to track resolution (use index-based mapping)
        service._resolve_tracks_from_play_records = AsyncMock(
            return_value={0: existing_track}  # First record resolves
        )
        
        # Act: Import with track resolution enabled
        result = await service.import_recent_plays_with_resolution(limit=1000)
        
        # Assert: Track resolution was attempted
        service._resolve_tracks_from_play_records.assert_called_once_with(sample_play_records)
        
        # Assert: Plays were saved with resolved track IDs
        mock_repositories.plays.bulk_insert_plays.assert_called_once()
        saved_plays = mock_repositories.plays.bulk_insert_plays.call_args[0][0]
        
        # First play should have resolved track ID
        resolved_play = saved_plays[0]
        assert resolved_play.track_id == 123
        
        # Second play should remain unresolved (no mock match)
        unresolved_play = saved_plays[1] 
        assert unresolved_play.track_id is None
        
        # Assert: Result shows resolution statistics
        assert result.play_metrics["resolved_count"] == 1
        assert result.play_metrics["unresolved_count"] == 1

    async def test_import_creates_connector_tracks_for_resolved_plays(
        self,
        service,
        mock_lastfm_connector,
        sample_play_records,
        mock_repositories
    ):
        """Test that resolved tracks create Last.fm connector track mappings."""
        # Setup: Mock API response
        mock_lastfm_connector.get_recent_tracks.return_value = sample_play_records
        
        # Setup: Mock resolved track
        resolved_track = Track(
            id=456,
            title="Yesterday",
            artists=[Artist(name="The Beatles")],
            album="Help!"
        )
        
        # Mock track resolution returning one match
        service._resolve_tracks_from_play_records = AsyncMock(
            return_value={1: resolved_track}  # Second record resolves (index 1)
        )
        
        # Act: Import with track resolution
        await service.import_recent_plays_with_resolution(limit=1000)
        
        # Assert: ConnectorTrack mapping was created
        mock_repositories.connector.map_track_to_connector.assert_called_once()
        
        # Verify mapping parameters
        call_args = mock_repositories.connector.map_track_to_connector.call_args
        assert call_args[1]["track"] == resolved_track
        assert call_args[1]["connector"] == "lastfm"
        assert call_args[1]["connector_id"] == "https://www.last.fm/music/The+Beatles/_/Yesterday"
        assert call_args[1]["match_method"] == "track_resolution"

    async def test_import_handles_unresolved_tracks_gracefully(
        self,
        service,
        mock_lastfm_connector, 
        sample_play_records,
        mock_repositories
    ):
        """Test that unresolved tracks are handled gracefully."""
        # Setup: Mock API response
        mock_lastfm_connector.get_recent_tracks.return_value = sample_play_records
        
        # Setup: Mock no track resolution (all tracks remain unresolved)
        service._resolve_tracks_from_play_records = AsyncMock(return_value={})
        
        # Act: Import with no tracks resolved
        result = await service.import_recent_plays_with_resolution(limit=1000)
        
        # Assert: All plays created with track_id=None
        saved_plays = mock_repositories.plays.bulk_insert_plays.call_args[0][0]
        assert all(play.track_id is None for play in saved_plays)
        
        # Assert: No connector track mappings created
        mock_repositories.connector.map_track_to_connector.assert_not_called()
        
        # Assert: Result shows resolution statistics
        assert result.play_metrics["resolved_count"] == 0
        assert result.play_metrics["unresolved_count"] == 2
        
        # Assert: Import still succeeds
        assert result.plays_processed == 2

    async def test_import_incremental_plays_no_checkpoint(
        self,
        service,
        mock_lastfm_connector,
        sample_play_records,
        mock_repositories
    ):
        """Test incremental import with no existing checkpoint."""
        # Setup: Mock no existing checkpoint
        mock_repositories.checkpoints.get_sync_checkpoint.return_value = None
        mock_lastfm_connector.lastfm_username = "testuser"
        mock_lastfm_connector.get_recent_tracks.return_value = sample_play_records
        
        # Act: Run incremental import
        result = await service.import_incremental_plays(resolve_tracks=False)
        
        # Assert: Checkpoint was queried
        mock_repositories.checkpoints.get_sync_checkpoint.assert_called_once_with(
            user_id="testuser",
            service="lastfm",
            entity_type="plays"
        )
        
        # Assert: API called with from_time=None (no checkpoint)
        mock_lastfm_connector.get_recent_tracks.assert_called_with(
            username="testuser",
            limit=200,
            page=1,
            from_time=None,
        )
        
        # Assert: Checkpoint saved with most recent timestamp
        mock_repositories.checkpoints.save_sync_checkpoint.assert_called_once()
        saved_checkpoint = mock_repositories.checkpoints.save_sync_checkpoint.call_args[0][0]
        assert saved_checkpoint.user_id == "testuser"
        assert saved_checkpoint.service == "lastfm"
        assert saved_checkpoint.entity_type == "plays"
        
        # Assert: Result includes checkpoint info
        assert result.play_metrics["checkpoint_updated"] is True
        assert result.plays_processed == 2

    async def test_import_incremental_plays_with_existing_checkpoint(
        self,
        service,
        mock_lastfm_connector,
        sample_play_records,
        mock_repositories
    ):
        """Test incremental import with existing checkpoint."""
        # Setup: Mock existing checkpoint
        checkpoint_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        existing_checkpoint = SyncCheckpoint(
            user_id="testuser",
            service="lastfm",
            entity_type="plays",
            last_timestamp=checkpoint_time,
            id=1
        )
        mock_repositories.checkpoints.get_sync_checkpoint.return_value = existing_checkpoint
        mock_lastfm_connector.lastfm_username = "testuser"
        mock_lastfm_connector.get_recent_tracks.return_value = sample_play_records
        
        # Act: Run incremental import
        result = await service.import_incremental_plays(resolve_tracks=False)
        
        # Assert: API called with from_time from checkpoint
        mock_lastfm_connector.get_recent_tracks.assert_called_with(
            username="testuser",
            limit=200,
            page=1,
            from_time=checkpoint_time,
        )
        
        # Assert: Checkpoint updated with new timestamp
        mock_repositories.checkpoints.save_sync_checkpoint.assert_called_once()
        saved_checkpoint = mock_repositories.checkpoints.save_sync_checkpoint.call_args[0][0]
        assert saved_checkpoint.last_timestamp > checkpoint_time
        
        # Assert: Result includes checkpoint timestamps
        assert result.play_metrics["from_timestamp"] == checkpoint_time.isoformat()
        assert "to_timestamp" in result.play_metrics

    async def test_import_incremental_plays_no_new_plays(
        self,
        service,
        mock_lastfm_connector,
        mock_repositories
    ):
        """Test incremental import when no new plays are found."""
        # Setup: Mock empty API response (no new plays)
        mock_lastfm_connector.lastfm_username = "testuser"
        mock_lastfm_connector.get_recent_tracks.return_value = []
        
        checkpoint_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        existing_checkpoint = SyncCheckpoint(
            user_id="testuser",
            service="lastfm",
            entity_type="plays",
            last_timestamp=checkpoint_time,
            id=1
        )
        mock_repositories.checkpoints.get_sync_checkpoint.return_value = existing_checkpoint
        
        # Act: Run incremental import
        result = await service.import_incremental_plays()
        
        # Assert: No plays processed
        assert result.plays_processed == 0
        assert result.imported_count == 0
        
        # Assert: Checkpoint still updated (to prevent future empty calls)
        mock_repositories.checkpoints.save_sync_checkpoint.assert_called_once()
        
        # Assert: No database insert attempted
        mock_repositories.plays.bulk_insert_plays.assert_not_called()

    async def test_import_incremental_plays_with_resolution(
        self,
        service,
        mock_lastfm_connector,
        sample_play_records,
        mock_repositories
    ):
        """Test incremental import with track resolution enabled."""
        # Setup: Mock connector and existing checkpoint
        mock_lastfm_connector.lastfm_username = "testuser"
        mock_lastfm_connector.get_recent_tracks.return_value = sample_play_records
        
        existing_checkpoint = SyncCheckpoint(
            user_id="testuser",
            service="lastfm",
            entity_type="plays",
            last_timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC),
            id=1
        )
        mock_repositories.checkpoints.get_sync_checkpoint.return_value = existing_checkpoint
        
        # Mock track resolution
        resolved_track = Track(
            id=789,
            title="Paranoid Android",
            artists=[Artist(name="Radiohead")],
            album="OK Computer"
        )
        service._resolve_tracks_from_play_records = AsyncMock(
            return_value={0: resolved_track}
        )
        
        # Act: Run incremental import with resolution
        result = await service.import_incremental_plays(resolve_tracks=True)
        
        # Assert: Track resolution was called
        service._resolve_tracks_from_play_records.assert_called_once_with(sample_play_records)
        
        # Assert: Plays saved with import_source indicating incremental+resolved
        saved_plays = mock_repositories.plays.bulk_insert_plays.call_args[0][0]
        assert saved_plays[0].import_source == "lastfm_api_incremental_resolved"
        assert saved_plays[0].track_id == 789
        
        # Assert: Resolution stats in result
        assert result.play_metrics["resolved_count"] == 1
        assert result.play_metrics["unresolved_count"] == 1

    async def test_import_incremental_plays_no_username_configured(
        self,
        service,
        mock_lastfm_connector,
        mock_repositories
    ):
        """Test incremental import with no username configured."""
        # Setup: No username configured
        mock_lastfm_connector.lastfm_username = None
        
        # Act: Run incremental import
        result = await service.import_incremental_plays()
        
        # Assert: Error result returned
        assert result.plays_processed == 0
        assert result.error_count == 1
        assert "LASTFM_USERNAME" in result.play_metrics["errors"][0]
        
        # Assert: No database operations
        mock_repositories.checkpoints.get_sync_checkpoint.assert_not_called()
        mock_repositories.plays.bulk_insert_plays.assert_not_called()

    async def test_import_incremental_plays_custom_user_id(
        self,
        service,
        mock_lastfm_connector,
        sample_play_records,
        mock_repositories
    ):
        """Test incremental import with custom user_id parameter."""
        # Setup: Mock response
        mock_lastfm_connector.get_recent_tracks.return_value = sample_play_records
        mock_repositories.checkpoints.get_sync_checkpoint.return_value = None
        
        # Act: Run incremental import with custom user
        await service.import_incremental_plays(
            user_id="customuser",
            resolve_tracks=False
        )
        
        # Assert: Custom user ID used in checkpoint operations
        mock_repositories.checkpoints.get_sync_checkpoint.assert_called_once_with(
            user_id="customuser",
            service="lastfm",
            entity_type="plays"
        )
        
        # Assert: Custom user ID used in API call
        mock_lastfm_connector.get_recent_tracks.assert_called_with(
            username="customuser",
            limit=200,
            page=1,
            from_time=None,
        )
        
        # Assert: Checkpoint saved with custom user ID
        saved_checkpoint = mock_repositories.checkpoints.save_sync_checkpoint.call_args[0][0]
        assert saved_checkpoint.user_id == "customuser"