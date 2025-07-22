"""Test suite for unified OperationResult class.

This test suite covers all functionality from the specialized result classes
that will be consolidated into the unified OperationResult system.
"""

import pytest
from datetime import datetime, UTC
from typing import Any

from src.domain.entities.operations import OperationResult, WorkflowResult
from src.domain.entities.track import Track, Artist
from src.application.utilities.results import ResultFactory, ImportResultData, SyncResultData


class TestUnifiedOperationResult:
    """Test the unified OperationResult class with all consolidated fields."""

    def test_basic_initialization(self):
        """Test that OperationResult initializes with all required fields."""
        result = OperationResult()
        
        # Existing fields
        assert result.tracks == []
        assert result.metrics == {}
        assert result.operation_name == ""
        assert result.execution_time == 0.0
        assert result.plays_processed == 0
        assert result.play_metrics == {}
        
        # New unified fields (these should be added)
        assert result.imported_count == 0
        assert result.exported_count == 0
        assert result.skipped_count == 0
        assert result.error_count == 0
        assert result.already_liked == 0
        assert result.candidates == 0

    def test_total_processed_property(self):
        """Test the total_processed computed property."""
        result = OperationResult(
            imported_count=10,
            exported_count=5,
            skipped_count=3,
            error_count=2
        )
        
        assert result.total_processed == 20

    def test_success_rate_property(self):
        """Test the success_rate computed property."""
        result = OperationResult(
            imported_count=10,
            exported_count=5,
            skipped_count=3,
            error_count=2
        )
        
        # Success rate = (imported + exported) / total * 100
        assert result.success_rate == 75.0

    def test_success_rate_zero_division(self):
        """Test success_rate handles zero division."""
        result = OperationResult()
        assert result.success_rate == 0.0

    def test_efficiency_rate_property(self):
        """Test the efficiency_rate computed property."""
        result = OperationResult(
            already_liked=8,
            candidates=10
        )
        
        # Efficiency rate = already_liked / candidates * 100
        assert result.efficiency_rate == 80.0

    def test_efficiency_rate_zero_division(self):
        """Test efficiency_rate handles zero division."""
        result = OperationResult()
        assert result.efficiency_rate == 0.0

    def test_to_dict_includes_all_fields(self):
        """Test that to_dict includes all unified fields."""
        tracks = [
            Track(id=1, title="Track 1", artists=[Artist(name="Artist 1")]),
            Track(id=2, title="Track 2", artists=[Artist(name="Artist 2")])
        ]
        
        result = OperationResult(
            operation_name="Test Operation",
            execution_time=1.5,
            tracks=tracks,
            imported_count=10,
            exported_count=5,
            skipped_count=3,
            error_count=2,
            already_liked=8,
            candidates=25
        )
        
        data = result.to_dict()
        
        # Check all fields are present
        assert data["operation_name"] == "Test Operation"
        assert data["execution_time"] == 1.5
        assert data["track_count"] == 2
        assert data["imported_count"] == 10
        assert data["exported_count"] == 5
        assert data["skipped_count"] == 3
        assert data["error_count"] == 2
        assert data["already_liked"] == 8
        assert data["candidates"] == 25
        assert data["total_processed"] == 20
        assert data["success_rate"] == 75.0
        assert data["efficiency_rate"] == 32.0


class TestBackwardCompatibility:
    """Test backward compatibility with existing specialized classes."""

    def test_sync_stats_compatibility(self):
        """Test that unified OperationResult can replace SyncStats."""
        # Create a unified result that behaves like SyncStats
        result = OperationResult(
            operation_name="Sync Operation",
            imported_count=5,
            exported_count=3,
            skipped_count=2,
            error_count=1
        )
        
        # Test SyncStats-like properties
        assert result.imported_count == 5  # SyncStats.imported
        assert result.exported_count == 3  # SyncStats.exported
        assert result.skipped_count == 2   # SyncStats.skipped
        assert result.error_count == 1     # SyncStats.errors
        assert result.total_processed == 11  # SyncStats.total

    def test_like_import_result_compatibility(self):
        """Test that unified OperationResult can replace LikeImportResult."""
        result = OperationResult(
            operation_name="Like Import",
            imported_count=10,
            skipped_count=5,
            error_count=2,
            already_liked=8,
            candidates=25
        )
        
        # Test LikeImportResult-like properties
        assert result.imported_count == 10
        assert result.skipped_count == 5
        assert result.error_count == 2
        assert result.already_liked == 8
        assert result.candidates == 25
        assert result.total_processed == 17
        assert result.success_rate == (10 / 17) * 100
        assert result.efficiency_rate == (8 / 25) * 100

    def test_like_export_result_compatibility(self):
        """Test that unified OperationResult can replace LikeExportResult."""
        result = OperationResult(
            operation_name="Like Export",
            exported_count=12,
            skipped_count=3,
            error_count=1,
            already_liked=15,
            candidates=31
        )
        
        # Test LikeExportResult-like properties
        assert result.exported_count == 12
        assert result.skipped_count == 3
        assert result.error_count == 1
        assert result.already_liked == 15
        assert result.candidates == 31
        assert result.total_processed == 16
        assert result.success_rate == (12 / 16) * 100

    def test_workflow_result_compatibility(self):
        """Test that WorkflowResult can remain as backward compatibility alias."""
        tracks = [Track(id=1, title="Test", artists=[Artist(name="Artist")])]
        
        result = WorkflowResult(
            operation_name="Test Workflow",
            tracks=tracks,
            imported_count=5,
            exported_count=3
        )
        
        # Test WorkflowResult-specific property
        assert result.workflow_name == "Test Workflow"
        assert result.imported_count == 5
        assert result.exported_count == 3


class TestResultFactory:
    """Test the updated ResultFactory methods."""

    def test_create_import_result(self):
        """Test ResultFactory.create_import_result with unified fields."""
        import_data = ImportResultData(
            raw_data_count=100,
            imported_count=80,
            error_count=5,
            batch_id="batch_123"
        )
        
        result = ResultFactory.create_import_result(
            operation_name="Spotify Import",
            import_data=import_data,
            execution_time=45.0
        )
        
        # Should create unified OperationResult with import-specific fields
        assert isinstance(result, OperationResult)
        assert result.operation_name == "Spotify Import"
        assert result.imported_count == 80
        assert result.skipped_count == 15  # raw_data_count - imported - error
        assert result.error_count == 5
        assert result.execution_time == 45.0

    def test_create_sync_result(self):
        """Test ResultFactory.create_sync_result with unified fields."""
        sync_data = SyncResultData(
            imported_count=10,
            exported_count=15,
            skipped_count=5,
            error_count=2,
            already_liked=8,
            candidates=40,
            batch_id="sync_456"
        )
        
        result = ResultFactory.create_sync_result(
            operation_name="Like Sync",
            sync_data=sync_data,
            execution_time=30.0
        )
        
        # Should create unified OperationResult with sync-specific fields
        assert isinstance(result, OperationResult)
        assert result.operation_name == "Like Sync"
        assert result.imported_count == 10
        assert result.exported_count == 15
        assert result.skipped_count == 5
        assert result.error_count == 2
        assert result.already_liked == 8
        assert result.candidates == 40
        assert result.total_processed == 32
        assert result.success_rate == ((10 + 15) / 32) * 100
        assert result.efficiency_rate == (8 / 40) * 100

    def test_create_error_result(self):
        """Test ResultFactory.create_error_result with unified fields."""
        result = ResultFactory.create_error_result(
            operation_name="Failed Operation",
            error_message="Connection timeout",
            batch_id="error_789"
        )
        
        # Should create unified OperationResult with error state
        assert isinstance(result, OperationResult)
        assert result.operation_name == "Failed Operation"
        assert result.error_count == 1
        assert result.imported_count == 0
        assert result.exported_count == 0
        assert result.skipped_count == 0
        assert result.success_rate == 0.0

    def test_create_empty_result(self):
        """Test ResultFactory.create_empty_result with unified fields."""
        result = ResultFactory.create_empty_result(
            operation_name="No-op Operation",
            batch_id="empty_000"
        )
        
        # Should create unified OperationResult with all zeros
        assert isinstance(result, OperationResult)
        assert result.operation_name == "No-op Operation"
        assert result.imported_count == 0
        assert result.exported_count == 0
        assert result.skipped_count == 0
        assert result.error_count == 0
        assert result.total_processed == 0
        assert result.success_rate == 0.0


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_negative_values_handled(self):
        """Test that negative values are handled gracefully."""
        result = OperationResult(
            imported_count=-1,  # Should not happen in practice
            exported_count=10,
            skipped_count=5,
            error_count=0
        )
        
        # Should still calculate correctly
        assert result.total_processed == 14

    def test_large_numbers_handled(self):
        """Test that large numbers are handled correctly."""
        result = OperationResult(
            imported_count=1000000,
            exported_count=500000,
            skipped_count=100000,
            error_count=50000,
            already_liked=200000,
            candidates=2000000
        )
        
        assert result.total_processed == 1650000
        assert result.success_rate == ((1000000 + 500000) / 1650000) * 100
        assert result.efficiency_rate == (200000 / 2000000) * 100

    def test_float_precision_in_rates(self):
        """Test that rate calculations handle float precision correctly."""
        result = OperationResult(
            imported_count=1,
            exported_count=1,
            skipped_count=1,
            already_liked=1,
            candidates=3
        )
        
        # Should handle float precision
        assert abs(result.success_rate - 66.66666666666667) < 1e-10
        assert abs(result.efficiency_rate - 33.33333333333333) < 1e-10