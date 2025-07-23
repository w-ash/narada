"""Tests for import service strategy pattern integration."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest

from src.domain.entities import PlayRecord, SyncCheckpoint, TrackPlay


class TestImportStrategyPattern:
    """Test suite for strategy pattern integration with BaseImportService."""

    @pytest.fixture
    def mock_repositories(self):
        """Mock track repositories with checkpoint support."""
        repositories = Mock()
        repositories.plays = AsyncMock()
        repositories.plays.bulk_insert_plays = AsyncMock(return_value=5)
        repositories.checkpoints = AsyncMock()
        repositories.checkpoints.get_sync_checkpoint = AsyncMock(return_value=None)
        repositories.checkpoints.save_sync_checkpoint = AsyncMock()
        return repositories

    @pytest.fixture
    def mock_lastfm_connector(self):
        """Mock Last.fm connector for strategy testing."""
        connector = AsyncMock()
        connector.lastfm_username = "testuser"
        return connector

    @pytest.fixture
    def sample_play_records(self):
        """Sample Last.fm play records for testing."""
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

    @pytest.fixture
    def strategy_based_service(self, mock_repositories, mock_lastfm_connector):
        """Create a mock service that uses strategy pattern."""
        from src.infrastructure.services.base_import import BaseImportService
        
        class StrategyTestService(BaseImportService):
            def __init__(self, repositories, lastfm_connector):
                super().__init__(repositories)
                self.operation_name = "Last.fm Strategy Test"
                self.lastfm_connector = lastfm_connector
                self.fetch_strategy_used = None
                self.checkpoint_strategy_used = None
            
            async def _fetch_data(self, strategy="recent", progress_callback=None, **kwargs):
                self.fetch_strategy_used = strategy
                if strategy == "recent":
                    return await self._fetch_recent_strategy(progress_callback=progress_callback, **kwargs)
                elif strategy == "incremental":
                    return await self._fetch_incremental_strategy(progress_callback=progress_callback, **kwargs)
                else:
                    raise ValueError(f"Unknown strategy: {strategy}")
            
            async def _fetch_recent_strategy(self, limit=1000, progress_callback=None, **kwargs):
                # Mock recent fetch - gets latest N tracks
                return await self.lastfm_connector.get_recent_tracks(limit=limit)
            
            async def _fetch_incremental_strategy(self, user_id=None, progress_callback=None, **kwargs):
                # Mock incremental fetch - gets tracks since checkpoint
                username = user_id or self.lastfm_connector.lastfm_username
                checkpoint = await self.repositories.checkpoints.get_sync_checkpoint(
                    user_id=username, service="lastfm", entity_type="plays"
                )
                from_time = checkpoint.last_timestamp if checkpoint else None
                return await self.lastfm_connector.get_recent_tracks(from_time=from_time)
            
            async def _process_data(self, raw_data, batch_id, import_timestamp, 
                                   resolve_tracks=False, progress_callback=None, **kwargs):
                # Convert PlayRecords to TrackPlays
                track_plays = []
                for record in raw_data:
                    track_play = TrackPlay(
                        track_id=None,  # Would be resolved in real implementation
                        service="lastfm",
                        played_at=record.played_at,
                        ms_played=record.ms_played,
                        context={
                            "track_name": record.track_name,
                            "artist_name": record.artist_name,
                            "album_name": record.album_name,
                            "resolution_enabled": resolve_tracks,
                        },
                        import_timestamp=import_timestamp,
                        import_source=f"lastfm_strategy_{self.fetch_strategy_used}",
                        import_batch_id=batch_id,
                    )
                    track_plays.append(track_play)
                return track_plays
            
            async def _handle_checkpoints(self, raw_data, strategy="recent", **kwargs):
                self.checkpoint_strategy_used = strategy
                if strategy == "incremental" and raw_data:
                    # Update checkpoint with most recent timestamp
                    username = kwargs.get("user_id") or self.lastfm_connector.lastfm_username
                    most_recent_timestamp = max(record.played_at for record in raw_data)
                    checkpoint = SyncCheckpoint(
                        user_id=username,
                        service="lastfm",
                        entity_type="plays",
                        last_timestamp=most_recent_timestamp
                    )
                    await self.repositories.checkpoints.save_sync_checkpoint(checkpoint)
        
        return StrategyTestService(mock_repositories, mock_lastfm_connector)

    async def test_recent_strategy_selection(
        self, strategy_based_service, mock_lastfm_connector, sample_play_records
    ):
        """Test that recent strategy is properly selected and executed."""
        # Arrange: Mock recent tracks API
        mock_lastfm_connector.get_recent_tracks.return_value = sample_play_records
        
        # Act: Import using recent strategy
        result = await strategy_based_service.import_data(strategy="recent", limit=1000)
        
        # Assert: Recent strategy was used
        assert strategy_based_service.fetch_strategy_used == "recent"
        assert strategy_based_service.checkpoint_strategy_used == "recent"
        
        # Assert: Recent API was called correctly
        mock_lastfm_connector.get_recent_tracks.assert_called_once_with(limit=1000)
        
        # Assert: Plays processed correctly
        assert result.plays_processed == 2
        assert result.imported_count == 5  # Mock return value
        
        # Assert: Import source reflects strategy
        saved_plays = strategy_based_service.repositories.plays.bulk_insert_plays.call_args[0][0]
        assert all(play.import_source == "lastfm_strategy_recent" for play in saved_plays)

    async def test_incremental_strategy_selection(
        self, strategy_based_service, mock_lastfm_connector, sample_play_records
    ):
        """Test that incremental strategy is properly selected and executed."""
        # Arrange: Mock existing checkpoint
        checkpoint_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        existing_checkpoint = SyncCheckpoint(
            user_id="testuser",
            service="lastfm",
            entity_type="plays",
            last_timestamp=checkpoint_time,
            id=1
        )
        strategy_based_service.repositories.checkpoints.get_sync_checkpoint.return_value = existing_checkpoint
        mock_lastfm_connector.get_recent_tracks.return_value = sample_play_records
        
        # Act: Import using incremental strategy
        await strategy_based_service.import_data(strategy="incremental", user_id="testuser")
        
        # Assert: Incremental strategy was used
        assert strategy_based_service.fetch_strategy_used == "incremental"
        assert strategy_based_service.checkpoint_strategy_used == "incremental"
        
        # Assert: Checkpoint was queried
        strategy_based_service.repositories.checkpoints.get_sync_checkpoint.assert_called_once_with(
            user_id="testuser", service="lastfm", entity_type="plays"
        )
        
        # Assert: API called with from_time from checkpoint
        mock_lastfm_connector.get_recent_tracks.assert_called_once_with(from_time=checkpoint_time)
        
        # Assert: Checkpoint was updated with new timestamp
        strategy_based_service.repositories.checkpoints.save_sync_checkpoint.assert_called_once()
        saved_checkpoint = strategy_based_service.repositories.checkpoints.save_sync_checkpoint.call_args[0][0]
        assert saved_checkpoint.user_id == "testuser"
        assert saved_checkpoint.service == "lastfm"
        assert saved_checkpoint.entity_type == "plays"
        
        # Assert: Import source reflects strategy
        saved_plays = strategy_based_service.repositories.plays.bulk_insert_plays.call_args[0][0]
        assert all(play.import_source == "lastfm_strategy_incremental" for play in saved_plays)

    async def test_strategy_parameter_passing(
        self, strategy_based_service, mock_lastfm_connector, sample_play_records
    ):
        """Test that strategy-specific parameters are properly passed through."""
        # Arrange: Mock API response
        mock_lastfm_connector.get_recent_tracks.return_value = sample_play_records
        
        # Act: Import with strategy-specific and processing parameters
        await strategy_based_service.import_data(
            strategy="recent",
            limit=500,
            resolve_tracks=True,
            user_id="customuser"
        )
        
        # Assert: Strategy-specific parameter was passed to fetch
        mock_lastfm_connector.get_recent_tracks.assert_called_once_with(limit=500)
        
        # Assert: Processing parameter was passed through
        saved_plays = strategy_based_service.repositories.plays.bulk_insert_plays.call_args[0][0]
        assert all(play.context["resolution_enabled"] is True for play in saved_plays)

    async def test_invalid_strategy_handling(self, strategy_based_service):
        """Test that invalid strategy creates error result."""
        # Act: Invalid strategy should create error result
        result = await strategy_based_service.import_data(strategy="invalid")
        
        # Assert: Error result created
        assert result.plays_processed == 0
        assert result.error_count == 1
        assert "Unknown strategy: invalid" in result.play_metrics["errors"][0]

    async def test_strategy_with_empty_data(
        self, strategy_based_service, mock_lastfm_connector
    ):
        """Test strategy pattern handles empty data correctly."""
        # Arrange: Mock empty response
        mock_lastfm_connector.get_recent_tracks.return_value = []
        
        # Act: Import with empty data
        result = await strategy_based_service.import_data(strategy="incremental")
        
        # Assert: Strategy was still selected
        assert strategy_based_service.fetch_strategy_used == "incremental"
        
        # Assert: Empty result
        assert result.plays_processed == 0
        assert result.imported_count == 0
        
        # Assert: Checkpoint strategy wasn't called (no data to process)
        assert strategy_based_service.checkpoint_strategy_used == "incremental"

    async def test_strategy_error_propagation(
        self, strategy_based_service, mock_lastfm_connector
    ):
        """Test that strategy-specific errors are properly propagated."""
        # Arrange: Mock API error
        mock_lastfm_connector.get_recent_tracks.side_effect = Exception("API timeout")
        
        # Act: Import with failing strategy
        result = await strategy_based_service.import_data(strategy="recent", limit=1000)
        
        # Assert: Error result created
        assert result.plays_processed == 0
        assert result.error_count == 1
        assert "API timeout" in result.play_metrics["errors"][0]
        
        # Assert: Strategy was selected before error
        assert strategy_based_service.fetch_strategy_used == "recent"

    async def test_concurrent_strategy_isolation(
        self, mock_repositories, mock_lastfm_connector, sample_play_records
    ):
        """Test that concurrent imports with different strategies don't interfere."""
        from src.infrastructure.services.base_import import BaseImportService
        
        class IsolationTestService(BaseImportService):
            def __init__(self, repositories, lastfm_connector, instance_id):
                super().__init__(repositories)
                self.operation_name = f"Isolation Test {instance_id}"
                self.lastfm_connector = lastfm_connector
                self.instance_id = instance_id
                self.strategy_used = None
            
            async def _fetch_data(self, strategy="recent", **kwargs):
                self.strategy_used = f"{strategy}_{self.instance_id}"
                return sample_play_records[:1]  # Return one record per instance
            
            async def _process_data(self, raw_data, batch_id, import_timestamp, **kwargs):
                return [
                    TrackPlay(
                        track_id=self.instance_id,
                        service="test",
                        played_at=datetime.now(UTC),
                        ms_played=180000,
                        context={"instance": self.instance_id},
                        import_timestamp=import_timestamp,
                        import_source=f"test_{self.strategy_used}",
                        import_batch_id=batch_id,
                    )
                ]
            
            async def _handle_checkpoints(self, raw_data, **kwargs):
                pass
        
        service1 = IsolationTestService(mock_repositories, mock_lastfm_connector, 1)
        service2 = IsolationTestService(mock_repositories, mock_lastfm_connector, 2)
        
        # Act: Run concurrent imports with different strategies
        import asyncio
        results = await asyncio.gather(
            service1.import_data(strategy="recent"),
            service2.import_data(strategy="incremental")
        )
        
        # Assert: Each service used its own strategy
        assert service1.strategy_used == "recent_1"
        assert service2.strategy_used == "incremental_2"
        
        # Assert: Both imports succeeded independently
        assert all(result.plays_processed == 1 for result in results)
        assert results[0].operation_name == "Isolation Test 1"
        assert results[1].operation_name == "Isolation Test 2"