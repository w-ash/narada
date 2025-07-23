"""Tests for refactored LastfmImportService using BaseImportService."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest

from src.domain.entities import (
    Artist,
    OperationResult,
    PlayRecord,
    SyncCheckpoint,
    Track,
)


class TestLastfmImportServiceRefactored:
    """Test suite for refactored LastfmImportService using template method pattern."""

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
        connector.lastfm_username = "testuser"
        return connector

    @pytest.fixture
    def service(self, mock_repositories, mock_lastfm_connector):
        """Create refactored service instance."""
        from src.infrastructure.services.lastfm_import import LastfmImportService
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
                },
                api_page=1
            ),
            PlayRecord(
                artist_name="The Beatles",
                track_name="Yesterday",
                played_at=datetime(2024, 1, 1, 13, 0, 0, tzinfo=UTC),
                service="lastfm",
                album_name="Help!",
                service_metadata={
                    "lastfm_track_url": "https://www.last.fm/music/The+Beatles/_/Yesterday",
                },
                api_page=1
            ),
        ]

    async def test_import_recent_plays_uses_template_method(
        self, service, mock_lastfm_connector, sample_play_records, mock_repositories
    ):
        """Test that import_recent_plays delegates to template method."""
        # Arrange: Mock API response
        mock_lastfm_connector.get_recent_tracks.return_value = sample_play_records
        
        # Act: Import recent plays
        result = await service.import_recent_plays(limit=1000)
        
        # Assert: Template method was used (inherits from BaseImportService)
        assert isinstance(result, OperationResult)
        assert result.operation_name == "Last.fm Recent Plays Import"
        assert result.plays_processed == 2
        assert result.imported_count == 5
        
        # Assert: API was called with recent strategy parameters
        mock_lastfm_connector.get_recent_tracks.assert_called()
        call_args = mock_lastfm_connector.get_recent_tracks.call_args_list
        # Should be called with limit and page for recent strategy
        assert any("limit" in str(call) for call in call_args)

    async def test_import_recent_plays_with_resolution_includes_resolution_stats(
        self, service, mock_lastfm_connector, sample_play_records, mock_repositories
    ):
        """Test that resolution import includes resolution statistics."""
        # Arrange: Mock API and resolution
        mock_lastfm_connector.get_recent_tracks.return_value = sample_play_records
        
        # Mock track resolution
        resolved_track = Track(id=123, title="Test Track", artists=[Artist(name="Test Artist")])
        service._resolve_tracks_from_play_records = AsyncMock(
            return_value={0: resolved_track}  # First track resolves
        )
        
        # Act: Import with resolution
        result = await service.import_recent_plays_with_resolution(limit=1000)
        
        # Assert: Resolution stats included
        assert "resolved_count" in result.play_metrics
        assert "unresolved_count" in result.play_metrics
        assert result.play_metrics["resolved_count"] == 1
        assert result.play_metrics["unresolved_count"] == 1
        
        # Assert: Import source indicates resolution
        saved_plays = mock_repositories.plays.bulk_insert_plays.call_args[0][0]
        assert all("resolved" in play.import_source for play in saved_plays)

    async def test_import_incremental_plays_uses_checkpoint_strategy(
        self, service, mock_lastfm_connector, sample_play_records, mock_repositories
    ):
        """Test that incremental import uses checkpoint strategy."""
        # Arrange: Mock existing checkpoint
        checkpoint_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        existing_checkpoint = SyncCheckpoint(
            user_id="testuser",
            service="lastfm",
            entity_type="plays",
            last_timestamp=checkpoint_time,
            id=1
        )
        mock_repositories.checkpoints.get_sync_checkpoint.return_value = existing_checkpoint
        mock_lastfm_connector.get_recent_tracks.return_value = sample_play_records
        
        # Act: Import incrementally
        await service.import_incremental_plays(user_id="testuser", resolve_tracks=False)
        
        # Assert: Checkpoint was queried
        mock_repositories.checkpoints.get_sync_checkpoint.assert_called_once_with(
            user_id="testuser", service="lastfm", entity_type="plays"
        )
        
        # Assert: API called with from_time from checkpoint
        api_calls = mock_lastfm_connector.get_recent_tracks.call_args_list
        assert any("from_time" in str(call) for call in api_calls)
        
        # Assert: Checkpoint was updated
        mock_repositories.checkpoints.save_sync_checkpoint.assert_called_once()
        
        # Assert: Import source indicates incremental
        saved_plays = mock_repositories.plays.bulk_insert_plays.call_args[0][0]
        assert all("incremental" in play.import_source for play in saved_plays)

    async def test_refactored_service_maintains_api_compatibility(
        self, service, mock_lastfm_connector, sample_play_records
    ):
        """Test that refactored service maintains original API compatibility."""
        # Arrange: Mock API response
        mock_lastfm_connector.get_recent_tracks.return_value = sample_play_records
        
        # Act: Call all original public methods
        recent_result = await service.import_recent_plays(limit=500)
        resolution_result = await service.import_recent_plays_with_resolution(limit=500)
        incremental_result = await service.import_incremental_plays(user_id="testuser")
        
        # Assert: All methods return OperationResult
        assert all(isinstance(result, OperationResult) for result in [
            recent_result, resolution_result, incremental_result
        ])
        
        # Assert: All have expected operation name
        assert all(result.operation_name == "Last.fm Recent Plays Import" for result in [
            recent_result, resolution_result, incremental_result
        ])
        
        # Assert: All processed expected number of plays
        assert all(result.plays_processed == 2 for result in [
            recent_result, resolution_result, incremental_result
        ])

    async def test_recent_strategy_pagination_logic(
        self, service, mock_lastfm_connector, sample_play_records
    ):
        """Test that recent strategy properly handles pagination."""
        # Arrange: Mock multiple pages
        page1_records = sample_play_records * 100  # 200 records (full page)
        page2_records = sample_play_records[:1] * 50  # 50 records (partial page)
        
        mock_lastfm_connector.get_recent_tracks.side_effect = [
            page1_records,
            page2_records
        ]
        
        # Act: Import with limit requiring multiple pages
        result = await service.import_recent_plays(limit=300)
        
        # Assert: Multiple API calls made
        assert mock_lastfm_connector.get_recent_tracks.call_count == 2
        
        # Assert: Correct number of records processed
        assert result.plays_processed == 250  # 200 + 50

    async def test_incremental_strategy_checkpoint_creation(
        self, service, mock_lastfm_connector, sample_play_records, mock_repositories
    ):
        """Test that incremental strategy creates checkpoint for first-time import."""
        # Arrange: No existing checkpoint
        mock_repositories.checkpoints.get_sync_checkpoint.return_value = None
        mock_lastfm_connector.get_recent_tracks.return_value = sample_play_records
        
        # Act: First-time incremental import
        await service.import_incremental_plays(user_id="newuser")
        
        # Assert: Checkpoint was created
        mock_repositories.checkpoints.save_sync_checkpoint.assert_called_once()
        saved_checkpoint = mock_repositories.checkpoints.save_sync_checkpoint.call_args[0][0]
        assert saved_checkpoint.user_id == "newuser"
        assert saved_checkpoint.service == "lastfm"
        assert saved_checkpoint.entity_type == "plays"
        assert saved_checkpoint.last_timestamp is not None

    async def test_error_handling_preserves_template_method_behavior(
        self, service, mock_lastfm_connector
    ):
        """Test that error handling follows template method pattern."""
        # Arrange: Mock API error
        mock_lastfm_connector.get_recent_tracks.side_effect = Exception("API error")
        
        # Act: Import with error
        result = await service.import_recent_plays()
        
        # Assert: Error result follows template format
        assert result.operation_name == "Last.fm Recent Plays Import"
        assert result.plays_processed == 0
        assert result.error_count == 1
        assert "API error" in result.play_metrics["errors"][0]

    async def test_progress_callback_integration_with_template(
        self, service, mock_lastfm_connector, sample_play_records
    ):
        """Test that progress callbacks integrate properly with template method."""
        # Arrange: Mock API response and progress callback
        mock_lastfm_connector.get_recent_tracks.return_value = sample_play_records
        progress_callback = Mock()
        
        # Act: Import with progress callback
        await service.import_recent_plays(progress_callback=progress_callback)
        
        # Assert: Progress callback was called multiple times
        assert progress_callback.call_count >= 3
        
        # Assert: Progress goes from 0 to 100
        progress_calls = progress_callback.call_args_list
        first_progress = progress_calls[0][0][0]
        last_progress = progress_calls[-1][0][0]
        assert first_progress == 0
        assert last_progress == 100

    async def test_refactored_service_reduces_code_duplication(self, service):
        """Test that refactored service eliminates original code duplication."""
        # This test validates that the refactoring achieved its goal
        
        # Assert: Service inherits from BaseImportService
        from src.infrastructure.services.base_import import BaseImportService
        assert isinstance(service, BaseImportService)
        
        # Assert: Public methods delegate to template method
        import inspect
        recent_source = inspect.getsource(service.import_recent_plays)
        resolution_source = inspect.getsource(service.import_recent_plays_with_resolution)
        incremental_source = inspect.getsource(service.import_incremental_plays)
        
        # All should delegate to import_data template method
        assert "import_data" in recent_source
        assert "import_data" in resolution_source
        assert "import_data" in incremental_source
        
        # Assert: Strategy pattern used for different behaviors
        assert 'strategy="recent"' in recent_source
        assert 'strategy="recent"' in resolution_source
        assert 'strategy="incremental"' in incremental_source

    async def test_connector_mapping_creation_preserved(
        self, service, mock_lastfm_connector, sample_play_records, mock_repositories
    ):
        """Test that connector mapping functionality is preserved."""
        # Arrange: Mock resolution with track
        resolved_track = Track(id=456, title="Test Track", artists=[Artist(name="Test")])
        service._resolve_tracks_from_play_records = AsyncMock(
            return_value={0: resolved_track}
        )
        mock_lastfm_connector.get_recent_tracks.return_value = sample_play_records
        
        # Act: Import with resolution
        await service.import_recent_plays_with_resolution()
        
        # Assert: Connector mapping was created
        mock_repositories.connector.map_track_to_connector.assert_called_once()
        
        # Assert: Mapping parameters are correct
        call_args = mock_repositories.connector.map_track_to_connector.call_args
        assert call_args[1]["track"] == resolved_track
        assert call_args[1]["connector"] == "lastfm"
        assert call_args[1]["match_method"] == "track_resolution"