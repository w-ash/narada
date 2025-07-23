"""Tests for unified ResultFactory to eliminate result creation duplication."""

from datetime import UTC, datetime
from uuid import uuid4

from src.application.utilities.results import (
    ImportResultData,
    ResultFactory,
    SyncResultData,
)
from src.domain.entities import TrackPlay  # TODO: Move TrackPlay to domain
from src.domain.entities.operations import OperationResult


class TestResultFactory:
    """Test the unified result factory that eliminates duplicate result creation patterns."""

    def test_create_import_success_result(self):
        """Test creating standardized import success result."""
        # Arrange
        operation_name = "Test Import"
        batch_id = str(uuid4())
        raw_data_count = 100
        imported_count = 85
        
        import_data = ImportResultData(
            raw_data_count=raw_data_count,
            imported_count=imported_count,
            batch_id=batch_id
        )

        # Act
        result = ResultFactory.create_import_result(
            operation_name=operation_name,
            import_data=import_data
        )

        # Assert
        assert isinstance(result, OperationResult)
        assert result.operation_name == operation_name
        assert result.plays_processed == raw_data_count
        assert result.imported_count == imported_count
        assert result.skipped_count == raw_data_count - imported_count
        assert result.error_count == 0
        assert result.play_metrics["batch_id"] == batch_id

    def test_create_import_empty_result(self):
        """Test creating standardized empty import result."""
        # Arrange
        operation_name = "Empty Import"
        batch_id = str(uuid4())
        
        import_data = ImportResultData(
            raw_data_count=0,
            imported_count=0,
            batch_id=batch_id
        )

        # Act
        result = ResultFactory.create_import_result(
            operation_name=operation_name,
            import_data=import_data
        )

        # Assert
        assert result.plays_processed == 0
        assert result.imported_count == 0
        assert result.skipped_count == 0
        assert result.error_count == 0

    def test_create_import_error_result(self):
        """Test creating standardized import error result."""
        # Arrange
        operation_name = "Failed Import"
        batch_id = str(uuid4())
        error_message = "Database connection failed"

        # Act
        result = ResultFactory.create_error_result(
            operation_name=operation_name,
            error_message=error_message,
            batch_id=batch_id
        )

        # Assert
        assert result.operation_name == operation_name
        assert result.plays_processed == 0
        assert result.imported_count == 0
        assert result.skipped_count == 0
        assert result.error_count == 1
        assert result.play_metrics["batch_id"] == batch_id
        assert result.play_metrics["errors"] == [error_message]

    def test_create_sync_result(self):
        """Test creating standardized sync result."""
        # Arrange
        operation_name = "Like Sync"
        batch_id = str(uuid4())
        
        sync_data = SyncResultData(
            imported_count=45,
            exported_count=12,
            skipped_count=3,
            error_count=1,
            already_liked=100,
            candidates=61,
            batch_id=batch_id
        )

        # Act
        result = ResultFactory.create_sync_result(
            operation_name=operation_name,
            sync_data=sync_data
        )

        # Assert
        assert result.operation_name == operation_name
        assert result.plays_processed == sync_data.total_processed
        assert result.imported_count == 45
        assert result.exported_count == 12
        assert result.skipped_count == 3
        assert result.error_count == 1
        assert result.already_liked == 100
        assert result.candidates == 61
        assert result.play_metrics["batch_id"] == batch_id

    def test_create_incremental_result(self):
        """Test creating standardized incremental import result."""
        # Arrange
        operation_name = "Incremental Import"
        batch_id = str(uuid4())
        new_plays = 25
        checkpoint_timestamp = datetime.now(UTC)
        
        import_data = ImportResultData(
            raw_data_count=new_plays,
            imported_count=new_plays,
            batch_id=batch_id,
            checkpoint_timestamp=checkpoint_timestamp
        )

        # Act
        result = ResultFactory.create_import_result(
            operation_name=operation_name,
            import_data=import_data
        )

        # Assert
        assert result.operation_name == operation_name
        assert result.plays_processed == new_plays
        assert result.imported_count == new_plays
        assert result.play_metrics["checkpoint_timestamp"] == checkpoint_timestamp.isoformat()

    def test_with_execution_time(self):
        """Test adding execution time to results."""
        # Arrange
        operation_name = "Timed Operation"
        batch_id = str(uuid4())
        execution_time = 5.25
        
        import_data = ImportResultData(
            raw_data_count=10,
            imported_count=10,
            batch_id=batch_id
        )

        # Act
        result = ResultFactory.create_import_result(
            operation_name=operation_name,
            import_data=import_data,
            execution_time=execution_time
        )

        # Assert
        assert result.execution_time == execution_time

    def test_with_tracks_data(self):
        """Test including tracks in result."""
        # Arrange
        operation_name = "Import with Tracks"
        batch_id = str(uuid4())
        track_plays = [
            TrackPlay(track_id=1, service="test", played_at=datetime.now(UTC), import_batch_id=batch_id),
            TrackPlay(track_id=2, service="test", played_at=datetime.now(UTC), import_batch_id=batch_id),
        ]
        
        import_data = ImportResultData(
            raw_data_count=2,
            imported_count=2,
            batch_id=batch_id,
            tracks=track_plays
        )

        # Act
        result = ResultFactory.create_import_result(
            operation_name=operation_name,
            import_data=import_data
        )

        # Assert
        assert len(result.tracks) == 2
        assert all(isinstance(track, TrackPlay) for track in result.tracks)


class TestImportResultData:
    """Test the ImportResultData helper class."""

    def test_calculated_properties(self):
        """Test that skipped_count is calculated correctly."""
        # Arrange
        import_data = ImportResultData(
            raw_data_count=100,
            imported_count=85,
            batch_id="test"
        )

        # Assert
        assert import_data.skipped_count == 15
        assert import_data.error_count == 0

    def test_with_errors(self):
        """Test import data with error tracking."""
        # Arrange
        import_data = ImportResultData(
            raw_data_count=100,
            imported_count=85,
            batch_id="test",
            error_count=15
        )

        # Assert
        assert import_data.skipped_count == 0  # All non-imported are errors
        assert import_data.error_count == 15


class TestSyncResultData:
    """Test the SyncResultData helper class."""

    def test_total_processed_calculation(self):
        """Test that total_processed is calculated correctly."""
        # Arrange
        sync_data = SyncResultData(
            imported_count=45,
            exported_count=12,
            skipped_count=3,
            error_count=1,
            batch_id="test"
        )

        # Assert
        assert sync_data.total_processed == 61  # 45 + 12 + 3 + 1

    def test_efficiency_metrics(self):
        """Test sync efficiency calculations."""
        # Arrange
        sync_data = SyncResultData(
            imported_count=45,
            exported_count=12,
            skipped_count=3,
            error_count=1,
            already_liked=100,
            candidates=61,
            batch_id="test"
        )

        # Assert
        assert sync_data.success_count == 57  # imported + exported
        assert sync_data.total_processed == 61
        # Success rate would be 57/61 ≈ 93.4%