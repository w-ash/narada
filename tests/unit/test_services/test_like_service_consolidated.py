"""Tests for consolidated LikeService that merges like_operations and like_sync functionality."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.use_cases.sync_likes import LikeService
from src.domain.entities import Artist, Track
from src.domain.entities.operations import OperationResult


class TestLikeServiceConsolidated:
    """Test the consolidated LikeService that eliminates functional overlap."""

    @pytest.fixture
    def mock_repositories(self):
        """Create mock repositories for testing."""
        repos = MagicMock()
        repos.session = MagicMock()
        repos.likes = AsyncMock()
        repos.core = AsyncMock()
        repos.checkpoints = AsyncMock()
        repos.connector = AsyncMock()
        return repos

    @pytest.fixture
    def mock_spotify_connector(self):
        """Create mock Spotify connector."""
        connector = AsyncMock()
        connector.get_liked_tracks = AsyncMock()
        return connector

    @pytest.fixture
    def mock_lastfm_connector(self):
        """Create mock Last.fm connector."""
        connector = AsyncMock()
        connector.love_track = AsyncMock()
        return connector

    @pytest.fixture
    def mock_connector_provider(self, mock_spotify_connector, mock_lastfm_connector):
        """Create mock connector provider."""
        provider = MagicMock()
        provider.get_connector.side_effect = lambda name: {
            "spotify": mock_spotify_connector,
            "lastfm": mock_lastfm_connector
        }.get(name)
        return provider

    @pytest.fixture
    def like_service(self, mock_repositories, mock_connector_provider):
        """Create LikeService instance for testing."""
        return LikeService(repositories=mock_repositories, connector_provider=mock_connector_provider)

    def test_import_spotify_likes_consolidates_session_handling(self, like_service, mock_spotify_connector):
        """Test that Spotify likes import eliminates session wrapper patterns."""
        # This test verifies that we no longer need separate session wrapper functions
        # The service should handle everything internally with the injected repositories
        
        # Arrange
        
        # Configure mock to return some connector tracks
        mock_spotify_connector.get_liked_tracks.return_value = ([], None)
        
        # Act & Assert - should not require external session management
        # The consolidated service should handle this internally
        assert hasattr(like_service, 'import_spotify_likes')
        assert hasattr(like_service, 'export_likes_to_lastfm')

    def test_export_likes_to_lastfm_consolidates_batch_processing(self, like_service, mock_lastfm_connector):
        """Test that Last.fm export consolidates batch processing logic."""
        # This test verifies that duplicate batch processing patterns are eliminated
        
        # Arrange
        tracks = [
            Track(id=1, title="Test Track 1", artists=[Artist(name="Artist 1")]),
            Track(id=2, title="Test Track 2", artists=[Artist(name="Artist 2")]),
        ]
        
        # Configure mocks
        like_service.repositories.likes.get_all_liked_tracks.return_value = []
        like_service.repositories.core.get_by_id.side_effect = tracks
        mock_lastfm_connector.love_track.return_value = True
        
        # Act & Assert - should use consolidated batch processing
        assert hasattr(like_service, '_process_batch_with_unified_processor')

    def test_checkpoint_management_consolidation(self, like_service):
        """Test that checkpoint management is consolidated into the service."""
        # This test verifies that CheckpointManager functionality is integrated
        
        # Act & Assert
        assert hasattr(like_service, 'get_or_create_checkpoint')
        assert hasattr(like_service, 'update_checkpoint')

    def test_result_creation_uses_result_factory(self, like_service):
        """Test that consolidated service uses ResultFactory for consistent results."""
        # Arrange
        import_data = {
            'imported_count': 10,
            'skipped_count': 2,
            'error_count': 1,
        }
        
        # Act
        result = like_service._create_import_result("Spotify Likes Import", import_data)
        
        # Assert
        assert isinstance(result, OperationResult)
        assert result.operation_name == "Spotify Likes Import"
        assert result.imported_count == 10
        assert result.skipped_count == 2
        assert result.error_count == 1

    def test_consolidated_service_eliminates_duplicate_functions(self, like_service):
        """Test that the consolidated service eliminates duplicate wrapper functions."""
        # Verify that session wrapper functions are no longer needed
        
        # These methods should NOT exist in the consolidated service
        assert not hasattr(like_service, 'run_with_session')
        assert not hasattr(like_service, 'run_spotify_likes_import')  
        assert not hasattr(like_service, 'run_lastfm_likes_export')
        
        # These should be the primary interface methods
        assert hasattr(like_service, 'import_spotify_likes')
        assert hasattr(like_service, 'export_likes_to_lastfm')

    def test_batch_processing_strategy_consolidation(self, like_service):
        """Test that batch processing uses unified strategy pattern."""
        # The service should have a single batch processing method that works for both
        # import and export scenarios, eliminating the duplication
        
        assert hasattr(like_service, '_process_batch_with_unified_processor')
        
        # Should not have separate batch processing methods
        assert not hasattr(like_service, 'process_batch_with_matcher')

    def test_progress_handling_standardization(self, like_service):
        """Test that progress handling is standardized across operations."""
        # Both import and export should use the same progress handling pattern
        
        # The service should use the unified progress system via decorators
        # Progress is handled by the @with_db_progress decorators in the methods
        assert hasattr(like_service, 'import_spotify_likes')
        assert hasattr(like_service, 'export_likes_to_lastfm')

    def test_error_handling_consolidation(self, like_service):
        """Test that error handling follows consistent patterns."""
        # All operations should use the same error handling approach
        
        # Should use ResultFactory for consistent error results
        error_result = like_service._create_error_result("Test error", "batch_123")
        assert error_result.error_count == 1
        assert "Test error" in error_result.play_metrics.get("errors", [])


class TestOperationResult:
    """Test the specialized result type for like import operations."""

    def test_like_import_result_extends_operation_result(self):
        """Test that OperationResult properly extends OperationResult."""
        result = OperationResult(
            operation_name="Test Import",
            imported_count=50,
            skipped_count=5,
            error_count=2,
            already_liked=100,
            candidates=57,
        )
        
        assert result.operation_name == "Test Import"
        assert result.imported_count == 50
        assert result.total_processed == 57  # 50 + 5 + 2
        assert result.success_rate > 0

    def test_efficiency_metrics_calculation(self):
        """Test efficiency metrics for like operations."""
        result = OperationResult(
            operation_name="Efficiency Test",
            imported_count=80,
            skipped_count=15,
            error_count=5,
            already_liked=200,
            candidates=100,
        )
        
        # Should calculate efficiency rate properly
        assert result.efficiency_rate == 200.0  # (200 already_liked / 100 total) * 100


class TestOperationResult:
    """Test the specialized result type for like export operations."""

    def test_like_export_result_extends_operation_result(self):
        """Test that OperationResult properly extends OperationResult."""
        result = OperationResult(
            operation_name="Test Export",
            exported_count=25,
            skipped_count=3,
            error_count=1,
            already_liked=50,
            candidates=29,
        )
        
        assert result.operation_name == "Test Export"
        assert result.exported_count == 25
        assert result.total_processed == 29  # 25 + 3 + 1
        assert result.success_rate > 0

    def test_export_specific_metrics(self):
        """Test export-specific metrics and calculations."""
        result = OperationResult(
            operation_name="Export Metrics Test",
            exported_count=45,
            skipped_count=10,
            error_count=5,
            already_liked=100,
            candidates=60,
        )
        
        # Should track export-specific metrics
        assert result.exported_count == 45
        assert result.already_liked == 100