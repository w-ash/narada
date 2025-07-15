"""Base import service implementing Template Method pattern."""

from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from src.application.utilities.results import ImportResultData, ResultFactory
from src.domain.entities import OperationResult, TrackPlay
from src.infrastructure.config import get_logger
from src.infrastructure.persistence.repositories.track import TrackRepositories

logger = get_logger(__name__)


class BaseImportService(ABC):
    """Abstract base service implementing Template Method pattern for data imports.

    This class defines the skeleton of the import algorithm while allowing subclasses
    to override specific steps. The template method ensures consistent workflow across
    all import services while eliminating code duplication.

    Template Method Pattern:
    1. Generate batch ID and timestamp
    2. Fetch raw data (abstract - service-specific)
    3. Process data into TrackPlay objects (abstract - service-specific)
    4. Save data to database (concrete - always the same)
    5. Handle checkpoints (abstract - strategy-specific)
    6. Return OperationResult (concrete - standardized format)
    """

    def __init__(self, repositories: TrackRepositories) -> None:
        """Initialize with repository access."""
        self.repositories = repositories
        self.operation_name = "Base Import"  # Override in subclasses

    async def import_data(
        self,
        import_batch_id: str | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
        **kwargs,
    ) -> OperationResult:
        """Template method defining the import workflow skeleton.

        This method orchestrates the complete import process:
        1. Setup (batch ID, timestamp)
        2. Data fetching (delegated to subclass)
        3. Data processing (delegated to subclass)
        4. Database persistence (standardized)
        5. Checkpoint handling (delegated to subclass)
        6. Result creation (standardized)

        Args:
            import_batch_id: Optional batch ID for tracking related imports
            progress_callback: Optional callback for progress updates (current, total, message)
            **kwargs: Additional parameters passed to template steps

        Returns:
            OperationResult with import statistics
        """
        # Step 1: Setup import context
        batch_id = import_batch_id or str(uuid4())
        import_timestamp = datetime.now(UTC)

        if progress_callback:
            progress_callback(0, 100, "Starting import...")

        logger.info(
            f"Starting {self.operation_name}",
            batch_id=batch_id,
            service=self.__class__.__name__,
        )

        try:
            # Step 2: Fetch raw data (Strategy pattern - implemented by subclasses)
            if progress_callback:
                progress_callback(20, 100, "Fetching data...")

            raw_data = await self._fetch_data(
                progress_callback=progress_callback, **kwargs
            )

            if not raw_data:
                # Handle empty data case - still call checkpoints for consistency
                if progress_callback:
                    progress_callback(
                        90, 100, "No data to import - updating checkpoints..."
                    )

                await self._handle_checkpoints(raw_data=raw_data, **kwargs)

                if progress_callback:
                    progress_callback(100, 100, "No data to import")

                return self._create_empty_result(batch_id)

            # Step 3: Process raw data into TrackPlay objects (Strategy pattern)
            if progress_callback:
                progress_callback(60, 100, f"Processing {len(raw_data)} records...")

            track_plays = await self._process_data(
                raw_data=raw_data,
                batch_id=batch_id,
                import_timestamp=import_timestamp,
                progress_callback=progress_callback,
                **kwargs,
            )

            # Step 4: Save to database (Template - always the same)
            if progress_callback:
                progress_callback(
                    80, 100, f"Saving {len(track_plays)} plays to database..."
                )

            imported_count = await self._save_data(track_plays)

            # Step 5: Handle checkpoints (Strategy pattern - delegated to subclasses)
            if progress_callback:
                progress_callback(90, 100, "Updating checkpoints...")

            await self._handle_checkpoints(raw_data=raw_data, **kwargs)

            # Step 6: Create success result (Template - standardized format)
            if progress_callback:
                progress_callback(100, 100, "Import completed successfully")

            logger.info(
                f"{self.operation_name} completed successfully",
                batch_id=batch_id,
                processed=len(raw_data),
                imported=imported_count,
            )

            return self._create_success_result(
                raw_data=raw_data,
                track_plays=track_plays,
                imported_count=imported_count,
                batch_id=batch_id,
            )

        except Exception as e:
            # Standardized error handling
            error_msg = f"{self.operation_name} failed: {e}"
            logger.error(
                f"{self.operation_name} failed", batch_id=batch_id, error=str(e)
            )

            return self._create_error_result(error_msg, batch_id)

    @abstractmethod
    async def _fetch_data(
        self, progress_callback: Callable[[int, int, str], None] | None = None, **kwargs
    ) -> list[Any]:
        """Fetch raw data from external source.

        This method implements the data acquisition strategy specific to each service.
        It should return a list of raw data objects that will be processed in the next step.

        Args:
            progress_callback: Optional callback for progress updates
            **kwargs: Service-specific parameters

        Returns:
            List of raw data objects
        """

    @abstractmethod
    async def _process_data(
        self,
        raw_data: list[Any],
        batch_id: str,
        import_timestamp: datetime,
        progress_callback: Callable[[int, int, str], None] | None = None,
        **kwargs,
    ) -> list[TrackPlay]:
        """Process raw data into TrackPlay objects.

        This method implements the data transformation strategy specific to each service.
        It should convert raw data objects into standardized TrackPlay objects.

        Args:
            raw_data: List of raw data objects from _fetch_data
            batch_id: Unique identifier for this import batch
            import_timestamp: When this import was initiated
            progress_callback: Optional callback for progress updates
            **kwargs: Service-specific parameters

        Returns:
            List of TrackPlay objects ready for database insertion
        """

    @abstractmethod
    async def _handle_checkpoints(self, raw_data: list[Any], **kwargs) -> None:
        """Handle checkpoint updates for incremental imports.

        This method implements the checkpoint strategy specific to each service.
        It should update sync checkpoints based on the imported data.

        Args:
            raw_data: List of raw data objects that were processed
            **kwargs: Service-specific parameters including strategy
        """

    async def _save_data(self, track_plays: list[TrackPlay]) -> int:
        """Save TrackPlay objects to database (Template - concrete implementation).

        This method is the same for all import services, implementing the standard
        database persistence workflow.

        Args:
            track_plays: List of TrackPlay objects to save

        Returns:
            Number of plays actually imported (after deduplication)
        """
        if not track_plays:
            return 0

        return await self.repositories.plays.bulk_insert_plays(track_plays)

    def _create_success_result(
        self,
        raw_data: list[Any],
        track_plays: list[TrackPlay],
        imported_count: int,
        batch_id: str,
    ) -> OperationResult:
        """Create standardized success result using unified ResultFactory."""
        import_data = ImportResultData(
            raw_data_count=len(raw_data),
            imported_count=imported_count,
            batch_id=batch_id,
            tracks=track_plays,
        )
        return ResultFactory.create_import_result(
            operation_name=self.operation_name,
            import_data=import_data,
        )

    def _create_empty_result(self, batch_id: str) -> OperationResult:
        """Create standardized empty result using unified ResultFactory."""
        import_data = ImportResultData(
            raw_data_count=0,
            imported_count=0,
            batch_id=batch_id,
        )
        return ResultFactory.create_import_result(
            operation_name=self.operation_name,
            import_data=import_data,
        )

    def _create_error_result(self, error_msg: str, batch_id: str) -> OperationResult:
        """Create standardized error result using unified ResultFactory."""
        return ResultFactory.create_error_result(
            operation_name=self.operation_name,
            error_message=error_msg,
            batch_id=batch_id,
        )
