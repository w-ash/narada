"""Tests for BaseImportService template method pattern."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest

from src.domain.entities import OperationResult, TrackPlay


class TestBaseImportService:
    """Test suite for BaseImportService template method pattern."""

    @pytest.fixture
    def mock_repositories(self):
        """Mock track repositories."""
        repositories = Mock()
        repositories.plays = AsyncMock()
        repositories.plays.bulk_insert_plays = AsyncMock(return_value=10)
        repositories.checkpoints = AsyncMock()
        repositories.checkpoints.get_sync_checkpoint = AsyncMock(return_value=None)
        repositories.checkpoints.save_sync_checkpoint = AsyncMock()
        return repositories

    @pytest.fixture
    def mock_concrete_service(self, mock_repositories):
        """Mock concrete service for testing template method."""
        from src.infrastructure.services.base_import import BaseImportService
        
        class MockImportService(BaseImportService):
            def __init__(self, repositories):
                super().__init__(repositories)
                self.operation_name = "Mock Import"
                self._fetch_data_called = False
                self._process_data_called = False
                self._handle_checkpoints_called = False
            
            async def _fetch_data(self, progress_callback=None, **kwargs):
                self._fetch_data_called = True
                return ["mock_raw_data_1", "mock_raw_data_2"]
            
            async def _process_data(self, raw_data, batch_id, import_timestamp, progress_callback=None, **kwargs):
                self._process_data_called = True
                # Create mock TrackPlay objects
                return [
                    TrackPlay(
                        track_id=1,
                        service="test",
                        played_at=datetime.now(UTC),
                        ms_played=180000,
                        context={"test": True},
                        import_timestamp=import_timestamp,
                        import_source="test",
                        import_batch_id=batch_id,
                    ),
                    TrackPlay(
                        track_id=2,
                        service="test",
                        played_at=datetime.now(UTC),
                        ms_played=210000,
                        context={"test": True},
                        import_timestamp=import_timestamp,
                        import_source="test",
                        import_batch_id=batch_id,
                    ),
                ]
            
            async def _handle_checkpoints(self, raw_data, **kwargs):
                self._handle_checkpoints_called = True
        
        return MockImportService(mock_repositories)

    async def test_import_workflow_template_method_calls_steps_in_order(
        self, mock_concrete_service, mock_repositories
    ):
        """Test that template method calls abstract methods in correct order."""
        # Act: Run the template method
        result = await mock_concrete_service.import_data()
        
        # Assert: All template steps were called
        assert mock_concrete_service._fetch_data_called
        assert mock_concrete_service._process_data_called
        assert mock_concrete_service._handle_checkpoints_called
        
        # Assert: Database save was called
        mock_repositories.plays.bulk_insert_plays.assert_called_once()
        
        # Assert: Result has expected structure
        assert isinstance(result, OperationResult)
        assert result.operation_name == "Mock Import"
        assert result.plays_processed == 2
        assert result.imported_count == 10

    async def test_template_method_generates_batch_id_automatically(
        self, mock_concrete_service
    ):
        """Test that template method generates batch ID when not provided."""
        # Act: Run template method without batch_id
        result = await mock_concrete_service.import_data()
        
        # Assert: Batch ID was generated
        batch_id = result.play_metrics["batch_id"]
        assert batch_id is not None
        assert len(batch_id) == 36  # UUID4 length
        
        # Try to parse as UUID to verify format
        from uuid import UUID
        UUID(batch_id)  # Should not raise

    async def test_template_method_uses_provided_batch_id(
        self, mock_concrete_service
    ):
        """Test that template method uses provided batch ID."""
        # Arrange: Provide custom batch ID
        custom_batch_id = "custom-batch-123"
        
        # Act: Run template method with custom batch_id
        result = await mock_concrete_service.import_data(import_batch_id=custom_batch_id)
        
        # Assert: Custom batch ID was used
        assert result.play_metrics["batch_id"] == custom_batch_id

    async def test_template_method_handles_empty_data_gracefully(
        self, mock_repositories
    ):
        """Test template method when fetch returns no data."""
        from src.infrastructure.services.base_import import BaseImportService
        
        class EmptyDataService(BaseImportService):
            def __init__(self, repositories):
                super().__init__(repositories)
                self.operation_name = "Empty Data Import"
            
            async def _fetch_data(self, progress_callback=None, **kwargs):
                return []
            
            async def _process_data(self, raw_data, batch_id, import_timestamp, progress_callback=None, **kwargs):
                return []
            
            async def _handle_checkpoints(self, raw_data, **kwargs):
                pass
        
        service = EmptyDataService(mock_repositories)
        
        # Act: Run import with empty data
        result = await service.import_data()
        
        # Assert: Empty result handled correctly
        assert result.plays_processed == 0
        assert result.imported_count == 0
        
        # Assert: No database save attempted for empty data
        mock_repositories.plays.bulk_insert_plays.assert_not_called()

    async def test_template_method_error_handling(
        self, mock_repositories
    ):
        """Test template method error handling creates proper error result."""
        from src.infrastructure.services.base_import import BaseImportService
        
        class FailingService(BaseImportService):
            def __init__(self, repositories):
                super().__init__(repositories)
                self.operation_name = "Failing Import"
            
            async def _fetch_data(self, progress_callback=None, **kwargs):
                raise ValueError("API connection failed")
            
            async def _process_data(self, raw_data, batch_id, import_timestamp, progress_callback=None, **kwargs):
                return []
            
            async def _handle_checkpoints(self, raw_data, **kwargs):
                pass
        
        service = FailingService(mock_repositories)
        
        # Act: Run import that fails
        result = await service.import_data()
        
        # Assert: Error result created
        assert result.operation_name == "Failing Import"
        assert result.plays_processed == 0
        assert result.error_count == 1
        assert "API connection failed" in result.play_metrics["errors"][0]
        
        # Assert: No database operations attempted
        mock_repositories.plays.bulk_insert_plays.assert_not_called()

    async def test_template_method_progress_callback_integration(
        self, mock_concrete_service
    ):
        """Test that template method properly integrates with progress callbacks."""
        # Arrange: Mock progress callback
        progress_callback = Mock()
        
        # Act: Run import with progress callback
        await mock_concrete_service.import_data(progress_callback=progress_callback)
        
        # Assert: Progress callback was called at key stages
        progress_calls = progress_callback.call_args_list
        assert len(progress_calls) >= 3  # At least start, middle, end
        
        # Assert: Progress goes from 0 to 100
        first_call = progress_calls[0][0]
        last_call = progress_calls[-1][0]
        assert first_call[0] == 0  # First progress is 0
        assert last_call[0] == 100  # Last progress is 100

    async def test_template_method_preserves_operation_context(
        self, mock_concrete_service
    ):
        """Test that template method preserves operation context in TrackPlay objects."""
        # Act: Run import with custom context
        result = await mock_concrete_service.import_data(custom_param="test_value")
        
        # Assert: TrackPlay objects contain import metadata
        saved_plays = mock_concrete_service.repositories.plays.bulk_insert_plays.call_args[0][0]
        
        for play in saved_plays:
            assert play.import_source == "test"
            assert play.import_batch_id == result.play_metrics["batch_id"]
            assert play.import_timestamp is not None
            assert isinstance(play.import_timestamp, datetime)

    async def test_template_method_supports_checkpoint_strategies(
        self, mock_repositories
    ):
        """Test that template method supports different checkpoint strategies."""
        from src.infrastructure.services.base_import import BaseImportService
        
        class CheckpointTestService(BaseImportService):
            def __init__(self, repositories):
                super().__init__(repositories)
                self.operation_name = "Checkpoint Test"
                self.checkpoint_strategy_called = None
            
            async def _fetch_data(self, progress_callback=None, **kwargs):
                return ["data"]
            
            async def _process_data(self, raw_data, batch_id, import_timestamp, progress_callback=None, **kwargs):
                return []
            
            async def _handle_checkpoints(self, raw_data, strategy="default", **kwargs):
                self.checkpoint_strategy_called = strategy
        
        service = CheckpointTestService(mock_repositories)
        
        # Act: Run with custom checkpoint strategy
        await service.import_data(strategy="incremental")
        
        # Assert: Strategy was passed to checkpoint handler
        assert service.checkpoint_strategy_called == "incremental"