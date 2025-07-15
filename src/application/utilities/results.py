"""Unified result factory to eliminate duplicate result creation patterns.

This module provides standardized result creation for all service operations,
replacing the duplicate result creation methods scattered across services.
"""

from datetime import datetime
from typing import Any

from attrs import define, field

from src.domain.entities.operations import OperationResult


@define(frozen=True)
class ImportResultData:
    """Data structure for import operation results."""

    raw_data_count: int
    imported_count: int
    batch_id: str
    error_count: int = 0
    checkpoint_timestamp: datetime | None = None
    tracks: list[Any] = field(factory=list)

    @property
    def skipped_count(self) -> int:
        """Calculate skipped count from raw data and processed counts."""
        return self.raw_data_count - self.imported_count - self.error_count


@define(frozen=True)
class SyncResultData:
    """Data structure for sync operation results."""

    imported_count: int = 0
    exported_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    batch_id: str = ""
    already_liked: int = 0
    candidates: int = 0
    tracks: list[Any] = field(factory=list)

    @property
    def total_processed(self) -> int:
        """Calculate total processed items."""
        return (
            self.imported_count
            + self.exported_count
            + self.skipped_count
            + self.error_count
        )

    @property
    def success_count(self) -> int:
        """Calculate successful operations (imported + exported)."""
        return self.imported_count + self.exported_count


class ResultFactory:
    """Factory for creating standardized OperationResult instances.

    Eliminates duplicate result creation patterns across services and provides
    consistent structure for all operation results.
    """

    @staticmethod
    def create_import_result(
        operation_name: str,
        import_data: ImportResultData,
        execution_time: float = 0.0,
    ) -> OperationResult:
        """Create standardized import operation result.

        Args:
            operation_name: Name of the import operation
            import_data: Import statistics and metadata
            execution_time: Operation execution time in seconds

        Returns:
            OperationResult with standardized import metrics
        """
        play_metrics = {
            "batch_id": import_data.batch_id,
        }

        # Add checkpoint timestamp if available
        if import_data.checkpoint_timestamp:
            play_metrics["checkpoint_timestamp"] = (
                import_data.checkpoint_timestamp.isoformat()
            )

        return OperationResult(
            operation_name=operation_name,
            plays_processed=import_data.raw_data_count,
            play_metrics=play_metrics,
            tracks=import_data.tracks,
            execution_time=execution_time,
            # Unified fields for import operations
            imported_count=import_data.imported_count,
            skipped_count=import_data.skipped_count,
            error_count=import_data.error_count,
        )

    @staticmethod
    def create_sync_result(
        operation_name: str,
        sync_data: SyncResultData,
        execution_time: float = 0.0,
    ) -> OperationResult:
        """Create standardized sync operation result.

        Args:
            operation_name: Name of the sync operation
            sync_data: Sync statistics and metadata
            execution_time: Operation execution time in seconds

        Returns:
            OperationResult with standardized sync metrics
        """
        play_metrics = {
            "batch_id": sync_data.batch_id,
        }

        return OperationResult(
            operation_name=operation_name,
            plays_processed=sync_data.total_processed,
            play_metrics=play_metrics,
            tracks=sync_data.tracks,
            execution_time=execution_time,
            # Unified fields for sync operations
            imported_count=sync_data.imported_count,
            exported_count=sync_data.exported_count,
            skipped_count=sync_data.skipped_count,
            error_count=sync_data.error_count,
            already_liked=sync_data.already_liked,
            candidates=sync_data.candidates,
        )

    @staticmethod
    def create_error_result(
        operation_name: str,
        error_message: str,
        batch_id: str = "",
        execution_time: float = 0.0,
    ) -> OperationResult:
        """Create standardized error result.

        Args:
            operation_name: Name of the failed operation
            error_message: Description of the error
            batch_id: Batch identifier for tracking
            execution_time: Operation execution time before failure

        Returns:
            OperationResult representing the error state
        """
        return OperationResult(
            operation_name=operation_name,
            plays_processed=0,
            play_metrics={
                "batch_id": batch_id,
                "errors": [error_message],
            },
            execution_time=execution_time,
            # Unified fields for error state
            error_count=1,
        )

    @staticmethod
    def create_empty_result(
        operation_name: str,
        batch_id: str = "",
        execution_time: float = 0.0,
    ) -> OperationResult:
        """Create standardized empty result for no-op operations.

        Args:
            operation_name: Name of the operation
            batch_id: Batch identifier for tracking
            execution_time: Operation execution time

        Returns:
            OperationResult representing no work done
        """
        return OperationResult(
            operation_name=operation_name,
            plays_processed=0,
            play_metrics={
                "batch_id": batch_id,
            },
            execution_time=execution_time,
            # Unified fields all default to 0 for empty result
        )
