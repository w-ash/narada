"""Tests for application layer batching utilities.

Validates Clean Architecture compliance - no external dependencies.
"""

import pytest
from unittest.mock import AsyncMock, Mock

from src.application.utilities.batching import (
    BatchProcessor, 
    BatchResult, 
    ImportStrategy, 
    MatchStrategy, 
    SyncStrategy,
    ConfigProvider,
    Logger,
    RepositoryProvider
)


class TestBatchResult:
    """Test BatchResult aggregation and metrics."""
    
    def test_empty_result(self):
        """Test empty batch result."""
        result = BatchResult(total_items=0, processed_count=0)
        
        assert result.total_items == 0
        assert result.processed_count == 0
        assert result.success_count == 0
        assert result.error_count == 0
        assert result.skipped_count == 0
        assert result.success_rate == 0.0
    
    def test_success_metrics(self):
        """Test success count calculation."""
        batch_results = [
            [
                {"status": "imported"},
                {"status": "processed"}, 
                {"status": "synced"},
                {"status": "error"},
                {"status": "skipped"}
            ]
        ]
        
        result = BatchResult(
            total_items=5,
            processed_count=5,
            batch_results=batch_results
        )
        
        assert result.success_count == 3  # imported + processed + synced
        assert result.error_count == 1
        assert result.skipped_count == 1
        assert result.success_rate == 60.0  # 3/5 * 100
    
    def test_success_rate_calculation(self):
        """Test success rate calculation with different scenarios."""
        # All successful
        batch_results = [[{"status": "imported"}, {"status": "processed"}]]
        result = BatchResult(total_items=2, processed_count=2, batch_results=batch_results)
        assert result.success_rate == 100.0
        
        # All failed
        batch_results = [[{"status": "error"}, {"status": "error"}]]
        result = BatchResult(total_items=2, processed_count=2, batch_results=batch_results)
        assert result.success_rate == 0.0


class TestImportStrategy:
    """Test ImportStrategy with dependency injection."""
    
    @pytest.fixture
    def mock_config(self):
        """Mock config provider."""
        config = Mock(spec=ConfigProvider)
        config.get.return_value = 25
        return config
    
    @pytest.fixture
    def mock_logger(self):
        """Mock logger."""
        logger = Mock(spec=Logger)
        return logger
    
    @pytest.fixture
    async def mock_processor(self):
        """Mock async processor function."""
        processor = AsyncMock()
        processor.return_value = {"status": "imported", "id": 1}
        return processor
    
    def test_default_batch_size(self, mock_processor):
        """Test default batch size without config."""
        strategy = ImportStrategy(processor_func=mock_processor)
        assert strategy.batch_size == 50
    
    def test_config_batch_size(self, mock_processor, mock_config):
        """Test batch size from config provider."""
        strategy = ImportStrategy(
            processor_func=mock_processor, 
            config=mock_config
        )
        assert strategy.batch_size == 25
        mock_config.get.assert_called_once_with("DEFAULT_IMPORT_BATCH_SIZE", 50)
    
    @pytest.mark.asyncio
    async def test_process_batch_success(self, mock_processor, mock_logger):
        """Test successful batch processing."""
        items = ["item1", "item2"]
        strategy = ImportStrategy(
            processor_func=mock_processor,
            logger=mock_logger
        )
        
        results = await strategy.process_batch(items)
        
        assert len(results) == 2
        assert all(r["status"] == "imported" for r in results)
        assert mock_processor.call_count == 2
    
    @pytest.mark.asyncio
    async def test_process_batch_with_errors(self, mock_logger):
        """Test batch processing with exceptions."""
        failing_processor = AsyncMock()
        failing_processor.side_effect = [
            {"status": "imported"},
            Exception("Processing failed")
        ]
        
        strategy = ImportStrategy(
            processor_func=failing_processor,
            logger=mock_logger
        )
        
        results = await strategy.process_batch(["item1", "item2"])
        
        assert len(results) == 2
        assert results[0]["status"] == "imported"
        assert results[1]["status"] == "error"
        assert "Processing failed" in results[1]["error"]
        mock_logger.exception.assert_called_once()


class TestMatchStrategy:
    """Test MatchStrategy with dependency injection."""
    
    @pytest.fixture
    def mock_config(self):
        """Mock config provider."""
        config = Mock(spec=ConfigProvider)
        config.get.side_effect = lambda key, default: {
            "SPOTIFY_API_BATCH_SIZE": 20,
            "DEFAULT_MATCH_BATCH_SIZE": 30
        }.get(key, default)
        return config
    
    def test_connector_specific_batch_size(self, mock_config):
        """Test connector-specific batch size configuration."""
        strategy = MatchStrategy(
            connector=Mock(),
            connector_type="spotify",
            config=mock_config
        )
        assert strategy.batch_size == 20
    
    def test_default_match_batch_size(self, mock_config):
        """Test default match batch size."""
        strategy = MatchStrategy(
            connector=Mock(),
            config=mock_config
        )
        assert strategy.batch_size == 30
    
    @pytest.mark.asyncio
    async def test_custom_processor_function(self):
        """Test using custom processor function."""
        mock_processor = AsyncMock()
        mock_processor.return_value = [{"status": "matched", "confidence": 90.0}]
        
        strategy = MatchStrategy(
            connector=Mock(),
            processor_func=mock_processor
        )
        
        items = ["item1"]
        results = await strategy.process_batch(items)
        
        assert len(results) == 1
        assert results[0]["confidence"] == 90.0
        mock_processor.assert_called_once()


class TestSyncStrategy:
    """Test SyncStrategy with dependency injection."""
    
    @pytest.fixture
    def mock_config(self):
        """Mock config provider."""
        config = Mock(spec=ConfigProvider)
        config.get.side_effect = lambda key, default: {
            "LASTFM_API_BATCH_SIZE": 15,
            "DEFAULT_SYNC_BATCH_SIZE": 20
        }.get(key, default)
        return config
    
    def test_target_service_batch_size(self, mock_config):
        """Test batch size based on target service."""
        strategy = SyncStrategy(
            source_service="internal",
            target_service="lastfm",
            config=mock_config
        )
        assert strategy.batch_size == 15
    
    @pytest.mark.asyncio
    async def test_custom_sync_function(self):
        """Test using custom sync function."""
        mock_sync_func = AsyncMock()
        mock_sync_func.return_value = [{"status": "synced", "service": "lastfm"}]
        
        strategy = SyncStrategy(
            source_service="internal",
            target_service="lastfm",
            sync_func=mock_sync_func
        )
        
        items = ["item1"]
        results = await strategy.process_batch(items)
        
        assert len(results) == 1
        assert results[0]["status"] == "synced"
        mock_sync_func.assert_called_once_with(items)


class TestBatchProcessor:
    """Test BatchProcessor orchestration with dependency injection."""
    
    @pytest.fixture
    def mock_logger(self):
        """Mock logger."""
        logger = Mock(spec=Logger)
        return logger
    
    @pytest.fixture
    def mock_repositories(self):
        """Mock repository provider."""
        return Mock(spec=RepositoryProvider)
    
    @pytest.fixture
    def processor(self, mock_repositories, mock_logger):
        """Create batch processor with mocked dependencies."""
        return BatchProcessor(
            repositories=mock_repositories,
            logger=mock_logger
        )
    
    @pytest.mark.asyncio
    async def test_empty_items_list(self, processor):
        """Test processing empty items list."""
        mock_strategy = Mock()
        
        result = await processor.process_with_strategy([], mock_strategy)
        
        assert result.total_items == 0
        assert result.processed_count == 0
    
    @pytest.mark.asyncio
    async def test_successful_processing(self, processor):
        """Test successful batch processing."""
        items = ["item1", "item2", "item3"]
        
        mock_strategy = Mock()
        mock_strategy.batch_size = 2
        mock_strategy.process_batch = AsyncMock()
        mock_strategy.process_batch.side_effect = [
            [{"status": "imported"}, {"status": "imported"}],
            [{"status": "imported"}]
        ]
        
        result = await processor.process_with_strategy(items, mock_strategy)
        
        assert result.total_items == 3
        assert result.processed_count == 3
        assert result.success_count == 3
        assert mock_strategy.process_batch.call_count == 2
    
    @pytest.mark.asyncio
    async def test_progress_callback(self, processor):
        """Test progress callback functionality."""
        items = ["item1", "item2"]
        progress_calls = []
        
        def progress_callback(current, total, message):
            progress_calls.append((current, total, message))
        
        mock_strategy = Mock()
        mock_strategy.batch_size = 1
        mock_strategy.process_batch = AsyncMock()
        mock_strategy.process_batch.return_value = [{"status": "imported"}]
        
        await processor.process_with_strategy(
            items, 
            mock_strategy, 
            progress_callback=progress_callback
        )
        
        assert len(progress_calls) == 2
        assert progress_calls[0] == (1, 2, "Processing batch 1")
        assert progress_calls[1] == (2, 2, "Processing batch 2")
    
    def test_strategy_factory_methods(self, processor):
        """Test strategy factory methods."""
        # Import strategy
        import_strategy = processor.create_import_strategy(
            processor_func=AsyncMock()
        )
        assert isinstance(import_strategy, ImportStrategy)
        
        # Match strategy
        match_strategy = processor.create_match_strategy(
            connector=Mock()
        )
        assert isinstance(match_strategy, MatchStrategy)
        
        # Sync strategy
        sync_strategy = processor.create_sync_strategy(
            source_service="internal",
            target_service="spotify"
        )
        assert isinstance(sync_strategy, SyncStrategy)


class TestCleanArchitectureCompliance:
    """Test Clean Architecture compliance - no external dependencies."""
    
    def test_no_external_imports(self):
        """Verify batching module has no external dependencies."""
        import sys
        sys.path.insert(0, 'src')
        
        # This should work without any narada.* imports
        from application.utilities.batching import (
            BatchProcessor, 
            BatchResult,
            ImportStrategy,
            MatchStrategy, 
            SyncStrategy
        )
        
        # Verify we can create instances without external dependencies
        result = BatchResult(total_items=0, processed_count=0)
        assert result.total_items == 0
        
        # Verify Protocol interfaces work
        processor = BatchProcessor()
        assert processor.repositories is None
        assert processor.logger is None
    
    def test_dependency_injection_protocols(self):
        """Test that Protocol interfaces enforce contracts."""
        from application.utilities.batching import ConfigProvider, Logger, RepositoryProvider
        
        # Verify protocols define expected methods
        assert hasattr(ConfigProvider, 'get')
        assert hasattr(Logger, 'info')
        assert hasattr(Logger, 'debug')
        assert hasattr(Logger, 'exception')
        
        # Should be able to create mock implementations
        class MockConfig:
            def get(self, key: str, default=None):
                return default
        
        class MockLogger:
            def info(self, message: str, **kwargs): pass
            def debug(self, message: str, **kwargs): pass
            def exception(self, message: str, **kwargs): pass
        
        # These should satisfy the protocol contracts
        config: ConfigProvider = MockConfig()
        logger: Logger = MockLogger()
        
        assert config.get("test", 42) == 42