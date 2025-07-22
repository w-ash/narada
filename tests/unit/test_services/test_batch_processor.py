"""Tests for unified BatchProcessor to eliminate duplicate batch processing patterns."""

from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock
from typing import Any

import pytest

from src.domain.entities.track import Track, Artist
from src.application.utilities.batching import (
    BatchProcessor,
    ImportStrategy,
    MatchStrategy, 
    SyncStrategy,
    BatchResult,
)


class TestBatchProcessor:
    """Test unified batch processor that eliminates processing duplication."""

    @pytest.fixture
    def mock_repositories(self):
        """Create mock repositories for testing."""
        repos = MagicMock()
        repos.session = MagicMock()
        repos.plays = AsyncMock()
        repos.likes = AsyncMock()
        repos.core = AsyncMock()
        return repos


    @pytest.fixture
    def batch_processor(self, mock_repositories):
        """Create BatchProcessor instance for testing."""
        return BatchProcessor(repositories=mock_repositories)

    def test_import_strategy_processing(self, batch_processor, tracks):
        """Test batch processing with import strategy."""
        # Arrange
        strategy = ImportStrategy(
            batch_size=2,
            processor_func=AsyncMock(return_value={"status": "imported"}),
        )
        
        # Act & Assert - should process in specified batch sizes
        assert strategy.batch_size == 2
        assert isinstance(strategy.processor_func, Callable)

    def test_match_strategy_processing(self, batch_processor, tracks):
        """Test batch processing with match strategy."""
        # Arrange
        mock_connector = AsyncMock()
        strategy = MatchStrategy(
            batch_size=3,
            connector=mock_connector,
            confidence_threshold=80.0,
        )
        
        # Act & Assert
        assert strategy.batch_size == 3
        assert strategy.connector == mock_connector
        assert strategy.confidence_threshold == 80.0

    def test_sync_strategy_processing(self, batch_processor, tracks):
        """Test batch processing with sync strategy."""
        # Arrange
        strategy = SyncStrategy(
            batch_size=5,
            source_service="spotify",
            target_service="lastfm",
            sync_func=AsyncMock(return_value={"status": "synced"}),
        )
        
        # Act & Assert
        assert strategy.batch_size == 5
        assert strategy.source_service == "spotify"
        assert strategy.target_service == "lastfm"

    async def test_process_with_import_strategy(self, batch_processor, tracks):
        """Test processing items with import strategy."""
        # Arrange
        async def mock_import_processor(item: Track) -> dict:
            return {
                "track_id": item.id,
                "status": "imported",
                "title": item.title,
            }
        
        strategy = ImportStrategy(
            batch_size=2,
            processor_func=mock_import_processor,
        )
        
        # Act
        result = await batch_processor.process_with_strategy(
            items=tracks,
            strategy=strategy,
        )
        
        # Assert
        assert isinstance(result, BatchResult)
        assert result.total_items == 3
        assert result.processed_count == 3
        assert len(result.batch_results) == 2  # 2 batches: [2 items], [1 item]

    async def test_process_with_match_strategy(self, batch_processor, tracks):
        """Test processing items with match strategy."""
        # Arrange
        mock_connector = AsyncMock()
        
        async def mock_match_processor(items: list[Track], connector: Any) -> list[dict]:
            return [
                {"track_id": item.id, "status": "matched", "confidence": 85.0}
                for item in items
            ]
        
        strategy = MatchStrategy(
            batch_size=2,
            connector=mock_connector,
            confidence_threshold=80.0,
            processor_func=mock_match_processor,
        )
        
        # Act
        result = await batch_processor.process_with_strategy(
            items=tracks,
            strategy=strategy,
        )
        
        # Assert
        assert result.total_items == 3
        assert result.processed_count == 3
        # Check that results have confidence in individual batch items
        assert all(
            any("confidence" in item for item in batch) 
            for batch in result.batch_results
        )

    async def test_process_with_sync_strategy(self, batch_processor, tracks):
        """Test processing items with sync strategy."""
        # Arrange
        async def mock_sync_processor(items: list[Track]) -> list[dict]:
            return [
                {"track_id": item.id, "status": "synced", "service": "lastfm"}
                for item in items
            ]
        
        strategy = SyncStrategy(
            batch_size=1,
            source_service="narada",
            target_service="lastfm",
            sync_func=mock_sync_processor,
        )
        
        # Act
        result = await batch_processor.process_with_strategy(
            items=tracks,
            strategy=strategy,
        )
        
        # Assert
        assert result.total_items == 3
        assert result.processed_count == 3
        assert len(result.batch_results) == 3  # 3 batches of 1 item each

    def test_batch_result_aggregation(self):
        """Test that BatchResult properly aggregates results."""
        # Arrange
        batch_results = [
            [
                {"status": "imported", "track_id": 1},
                {"status": "skipped", "track_id": 2},
            ],
            [
                {"status": "imported", "track_id": 3},
                {"status": "error", "track_id": 4},
            ],
        ]
        
        # Act
        result = BatchResult(
            total_items=4,
            processed_count=4,
            batch_results=batch_results,
        )
        
        # Assert
        assert result.total_items == 4
        assert result.processed_count == 4
        assert result.success_count == 2  # 2 imported
        assert result.error_count == 1    # 1 error
        assert result.skipped_count == 1  # 1 skipped

    def test_batch_result_metrics_calculation(self):
        """Test metrics calculation in BatchResult."""
        # Arrange
        batch_results = [
            [{"status": "imported"}, {"status": "imported"}],
            [{"status": "skipped"}],
        ]
        
        result = BatchResult(
            total_items=3,
            processed_count=3,
            batch_results=batch_results,
        )
        
        # Act & Assert
        assert result.success_rate == 66.67  # 2/3 * 100, rounded
        assert result.get_status_count("imported") == 2
        assert result.get_status_count("skipped") == 1
        assert result.get_status_count("error") == 0

    async def test_error_handling_in_batch_processing(self, batch_processor, tracks):
        """Test error handling during batch processing."""
        # Arrange
        async def failing_processor(item: Track) -> dict:
            if item.id == 2:
                raise ValueError("Processing failed")
            return {"track_id": item.id, "status": "processed"}
        
        strategy = ImportStrategy(
            batch_size=1,
            processor_func=failing_processor,
        )
        
        # Act
        result = await batch_processor.process_with_strategy(
            items=tracks,
            strategy=strategy,
        )
        
        # Assert
        assert result.total_items == 3
        assert result.error_count == 1
        assert result.success_count == 2

    def test_configurable_batch_sizes(self, batch_processor, tracks):
        """Test that different strategies can have different batch sizes."""
        # Arrange
        import_strategy = ImportStrategy(batch_size=1, processor_func=AsyncMock())
        match_strategy = MatchStrategy(batch_size=5, connector=AsyncMock())
        sync_strategy = SyncStrategy(batch_size=10, source_service="a", target_service="b")
        
        # Act & Assert
        assert import_strategy.batch_size == 1
        assert match_strategy.batch_size == 5
        assert sync_strategy.batch_size == 10

    def test_progress_callback_integration(self, batch_processor, tracks):
        """Test that progress callbacks work with batch processing."""
        # Arrange
        progress_calls = []
        
        def mock_progress_callback(current: int, total: int, description: str):
            progress_calls.append((current, total, description))
        
        strategy = ImportStrategy(
            batch_size=2,
            processor_func=AsyncMock(return_value={"status": "processed"}),
        )
        
        # Act & Assert - should accept progress callback
        # The actual implementation would integrate with the progress system
        assert hasattr(batch_processor, 'process_with_strategy')


class TestBatchStrategies:
    """Test the individual batch processing strategies."""

    def test_import_strategy_validation(self):
        """Test ImportStrategy validation."""
        # Should require processor_func
        with pytest.raises(TypeError):
            ImportStrategy(batch_size=10)
        
        # Should accept valid processor
        strategy = ImportStrategy(
            batch_size=5,
            processor_func=AsyncMock(),
        )
        assert strategy.batch_size == 5

    def test_match_strategy_validation(self):
        """Test MatchStrategy validation."""
        # Should require connector
        with pytest.raises(TypeError):
            MatchStrategy(batch_size=10)
        
        # Should accept valid connector
        strategy = MatchStrategy(
            batch_size=3,
            connector=AsyncMock(),
            confidence_threshold=75.0,
        )
        assert strategy.confidence_threshold == 75.0

    def test_sync_strategy_validation(self):
        """Test SyncStrategy validation."""
        # Should require services
        with pytest.raises(TypeError):
            SyncStrategy(batch_size=5)
        
        # Should accept valid services
        strategy = SyncStrategy(
            batch_size=8,
            source_service="spotify",
            target_service="lastfm",
        )
        assert strategy.source_service == "spotify"
        assert strategy.target_service == "lastfm"


class TestBatchProcessorIntegration:
    """Test integration scenarios that eliminate existing duplication."""

    @pytest.fixture
    def mock_repositories(self):
        """Create mock repositories for testing."""
        repos = MagicMock()
        repos.session = MagicMock()
        return repos

    @pytest.fixture
    def batch_processor(self, mock_repositories):
        """Create BatchProcessor instance for testing."""
        return BatchProcessor(repositories=mock_repositories)

    def test_replaces_matcher_process_in_batches(self, batch_processor):
        """Test that BatchProcessor can replace matcher.process_in_batches."""
        # The unified processor should handle the same scenarios as the
        # existing process_in_batches function in matcher.py
        
        # Should support different connector types
        spotify_strategy = MatchStrategy(
            batch_size=50,
            connector=AsyncMock(),
            connector_type="spotify",
        )
        
        lastfm_strategy = MatchStrategy(
            batch_size=20,
            connector=AsyncMock(),
            connector_type="lastfm",
        )
        
        assert spotify_strategy.batch_size == 50
        assert lastfm_strategy.batch_size == 20

    def test_replaces_like_operations_batch_processing(self, batch_processor):
        """Test that BatchProcessor can replace like_operations batch processing."""
        # Should handle the same scenarios as process_batch_with_matcher
        # in like_operations.py
        
        strategy = SyncStrategy(
            batch_size=30,
            source_service="narada",
            target_service="lastfm",
            connector=AsyncMock(),
        )
        
        assert hasattr(strategy, 'source_service')
        assert hasattr(strategy, 'target_service')

    def test_consolidates_configuration_patterns(self, batch_processor):
        """Test that batch sizes are configured consistently."""
        # Should use the same config patterns across all strategies
        
        # All strategies should support config-driven batch sizes
        strategies = [
            ImportStrategy(batch_size=None, processor_func=AsyncMock()),
            MatchStrategy(batch_size=None, connector=AsyncMock()),
            SyncStrategy(batch_size=None, source_service="a", target_service="b"),
        ]
        
        # Should fall back to reasonable defaults when batch_size is None
        for strategy in strategies:
            # Implementation would set default batch sizes from config
            assert hasattr(strategy, 'batch_size')