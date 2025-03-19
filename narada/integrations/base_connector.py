"""Base connector module providing shared functionality for music service connectors.

This module defines common abstractions and utilities for music service connectors
including standardized metric resolution, connector configuration, and error handling.

Key Components:
-------------
MetricResolverProtocol: Protocol defining the interface for metric resolvers
ConnectorConfig: TypedDict for standardized connector configuration
BaseMetricResolver: Abstract base class for resolving service-specific metrics
BatchProcessor: Utility for batch processing with concurrency control
register_metrics: Utility function to register metric resolvers

This module is designed to minimize code duplication across connector implementations
while enforcing consistent patterns for metric resolution and error handling.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar, Protocol, TypedDict, TypeVar, runtime_checkable

from attrs import define, field

from narada.config import get_logger
from narada.core.protocols import get_metric_freshness, register_metric_resolver
from narada.database.db_connection import get_session
from narada.repositories.track import UnifiedTrackRepository

# Get contextual logger
logger = get_logger(__name__).bind(service="connectors")

# Define type variables for generic operations
T = TypeVar("T")
R = TypeVar("R")


class ConnectorConfig(TypedDict, total=False):
    """Type definition for connector configuration.

    Fields:
    -------
    extractors: Mapping of metric names to extractor functions
    dependencies: List of connector dependencies
    factory: Factory function to create connector instance
    metrics: Mapping of metric names to connector metadata fields
    """

    extractors: dict[str, Callable[[Any], Any]]
    dependencies: list[str]
    factory: Callable[[dict[str, Any]], Any]
    metrics: dict[str, str]


@runtime_checkable
class MetricResolverProtocol(Protocol):
    """Protocol defining the interface for metric resolvers."""

    async def resolve(self, track_ids: list[int], metric_name: str) -> dict[str, Any]:
        """Fetch stored service metrics from the database.

        Args:
            track_ids: List of internal track IDs
            metric_name: Metric to resolve (used to determine field name)

        Returns:
            Dictionary mapping track_id strings to metric values
        """
        ...


@define(frozen=True, slots=True)
class BaseMetricResolver:
    """Base class for resolving service metrics from persistence layer."""

    # To be defined by subclasses - maps metric names to connector metadata fields
    FIELD_MAP: ClassVar[dict[str, str]] = {}

    # Connector name to be overridden by subclasses
    CONNECTOR: ClassVar[str] = ""

    async def resolve(self, track_ids: list[int], metric_name: str) -> dict[str, Any]:
        """Fetch stored service metrics from the database.

        This implementation:
        1. Retrieves the metadata field name from FIELD_MAP
        2. Gets metadata from connector_tracks table
        3. Saves to track_metrics table for future retrieval
        4. Returns standardized metric values

        Args:
            track_ids: List of internal track IDs
            metric_name: Metric to resolve

        Returns:
            Dictionary mapping track_id strings to metric values
        """
        if not track_ids:
            return {}

        # Get the connector field name
        field = self.FIELD_MAP.get(metric_name)
        if not field:
            return {}

        # Get metrics from connector metadata and store in track_metrics
        async with get_session() as session:
            track_repo = UnifiedTrackRepository(session)

            # Get metadata from connector tracks
            metadata = await track_repo.get_connector_metadata(
                track_ids=track_ids,
                connector=self.CONNECTOR,
                metadata_field=field,
            )

            # Debug log the retrieved metadata with more details
            non_zero_values = {k: v for k, v in metadata.items() if v != 0}
            logger.info(
                f"Retrieved {self.CONNECTOR} metadata for {field}",
                total_values=len(metadata),
                non_zero_values=len(non_zero_values),
                sample_values=list(non_zero_values.items())[:5]
                if non_zero_values
                else [],
                zero_sample=[
                    item for item in list(metadata.items())[:5] if item[1] == 0
                ],
                connector=self.CONNECTOR,
                metric_name=metric_name,
            )

            # Save metrics to database - store all numeric values including zeros
            metrics_to_save = [
                (track_id, self.CONNECTOR, metric_name, float(value))
                for track_id, value in metadata.items()
                if value is not None and isinstance(value, int | float)
            ]

            if metrics_to_save:
                await track_repo.save_track_metrics(metrics_to_save)
                # Get metric-specific freshness requirement
                max_age_hours = get_metric_freshness(metric_name)

                logger.info(
                    f"Saved {self.CONNECTOR} {field} metrics",
                    count=len(metrics_to_save),
                    metric_name=metric_name,
                    freshness_hours=max_age_hours,
                )
            elif metadata:
                # Log when we have metadata but no valid metrics to save
                logger.warning(
                    f"No valid {self.CONNECTOR} {field} metrics to save",
                    metric_name=metric_name,
                    metadata_count=len(metadata),
                    has_none_values=any(value is None for value in metadata.values()),
                    has_zero_values=any(
                        value == 0 for value in metadata.values() if value is not None
                    ),
                )

            # Get metric-specific freshness requirement for database query
            max_age_hours = get_metric_freshness(metric_name)

            # Get updated metrics from track_metrics table with appropriate freshness
            metrics_dict = await track_repo.get_track_metrics(
                track_ids=track_ids,
                metric_type=metric_name,
                connector=self.CONNECTOR,
                max_age_hours=max_age_hours,
            )

            # Identify tracks with missing metrics
            missing_tracks = [
                track_id for track_id in track_ids if track_id not in metrics_dict
            ]

            if missing_tracks:
                logger.info(
                    f"Found {len(missing_tracks)} tracks with missing {metric_name} data",
                    connector=self.CONNECTOR,
                    metric_name=metric_name,
                    track_count=len(track_ids),
                    missing_count=len(missing_tracks),
                    missing_sample=missing_tracks[:5],
                )

            # Return with integer keys with None for missing values (not 0)
            # This ensures the system can distinguish between "0 plays" and "unknown plays"
            return {
                track_id: metrics_dict.get(track_id, None)
                for track_id in track_ids
            }


@define(frozen=True, slots=True)
class BatchProcessor[T, R]:
    """Generic batch processor with concurrency control and backoff capabilities.

    This utility simplifies batch processing operations across all connectors,
    standardizing concurrency control, batching logic and error handling.
    Uses configuration values from config.py.
    """

    batch_size: int
    concurrency_limit: int
    retry_count: int
    retry_base_delay: float
    retry_max_delay: float
    request_delay: float
    logger_instance: Any = field(factory=lambda: get_logger(__name__))

    async def process(
        self,
        items: list[T],
        process_func: Callable[[T], Awaitable[R]],
    ) -> list[R]:
        """Process items in batches with controlled concurrency and exponential backoff.
        
        Args:
            items: List of items to process
            process_func: Async function that processes a single item
            
        Returns:
            List of results in the same order as input items
        """
        if not items:
            return []

        results: list[R] = []
        semaphore = asyncio.Semaphore(self.concurrency_limit)
        
        async def process_with_backoff(item: T) -> R:
            """Process an item with exponential backoff on failures."""
            retries = 0
            last_exception = None
            
            while retries <= self.retry_count:
                try:
                    async with semaphore:
                        # Add delay between requests to avoid rate limits
                        if self.request_delay > 0:
                            await asyncio.sleep(self.request_delay)
                        return await process_func(item)
                except Exception as e:
                    last_exception = e
                    retries += 1
                    
                    # Skip backoff on final attempt
                    if retries > self.retry_count:
                        break
                    
                    # Calculate exponential backoff delay with jitter
                    import random
                    delay = min(
                        self.retry_max_delay,
                        self.retry_base_delay * (2 ** (retries - 1))
                    )
                    # Add jitter (±25%)
                    jitter = random.uniform(0.75, 1.25)
                    delay = delay * jitter
                    
                    self.logger_instance.warning(
                        f"Batch processing error (attempt {retries}/{self.retry_count})",
                        error=str(last_exception),
                        retry_delay=f"{delay:.2f}s",
                    )
                    
                    await asyncio.sleep(delay)
            
            # If we got here, all retries failed
            self.logger_instance.error(
                f"All {self.retry_count} batch processing attempts failed",
                error=str(last_exception),
            )
            raise last_exception or RuntimeError("Batch processing failed")

        # Process in batches for memory efficiency and rate limit management
        for i in range(0, len(items), self.batch_size):
            batch = items[i : i + self.batch_size]
            self.logger_instance.debug(
                f"Processing batch {i//self.batch_size + 1}/{(len(items) + self.batch_size - 1)//self.batch_size}",
                batch_size=len(batch),
                total_items=len(items),
            )
            
            # Use gather with return_exceptions=True to handle errors without failing the whole batch
            batch_results = await asyncio.gather(
                *[process_with_backoff(item) for item in batch],
                return_exceptions=True
            )
            
            # Process results, keeping errors separate
            valid_results = []
            for result in batch_results:
                if isinstance(result, Exception):
                    self.logger_instance.error(
                        "Item processing failed",
                        error=str(result),
                        error_type=type(result).__name__,
                    )
                else:
                    valid_results.append(result)
                    
            results.extend(valid_results)
            
            # Log batch completion
            self.logger_instance.debug(
                f"Batch {i//self.batch_size + 1} complete",
                valid_results=len(valid_results),
                failures=len(batch_results) - len(valid_results),
            )

        return results


def register_metrics(
    metric_resolver: MetricResolverProtocol,
    field_map: dict[str, str],
) -> None:
    """Register all metrics defined in field_map with the given resolver.

    Args:
        metric_resolver: The resolver instance to register
        field_map: Mapping of metric names to connector fields
    """
    for metric_name in field_map:
        register_metric_resolver(metric_name, metric_resolver)
