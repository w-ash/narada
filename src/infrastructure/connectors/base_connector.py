"""Base connector module providing shared functionality for music service connectors.

This module defines common abstractions and utilities for music service connectors
including standardized metric resolution, batch processing, and error handling.

Key Components:
- BaseMetricResolver: Abstract base class for resolving service-specific metrics
- BatchProcessor: Generic utility for batch processing with concurrency control
- register_metrics: Function to register metric resolvers with the global registry

These components establish a consistent foundation for all connector implementations,
reducing code duplication while enforcing standardized patterns for metric resolution,
error handling, and batch processing operations.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar, TypeVar

from attrs import define, field
import backoff

from src.infrastructure.config import get_logger
from src.infrastructure.connectors.metrics_registry import (
    MetricResolverProtocol,
    get_metric_freshness,
    register_metric_resolver,
)
from src.infrastructure.persistence.database.db_connection import get_session

# Get contextual logger
logger = get_logger(__name__).bind(service="connectors")

# Define type variables for generic operations
T = TypeVar("T")
R = TypeVar("R")


# ConnectorPlaylistItem is now imported from src.domain.entities where needed


@define(frozen=True, slots=True)
class BaseMetricResolver:
    """Base class for resolving service metrics from persistence layer.

    This abstract base class provides a standard implementation for resolving
    service-specific metrics from the persistence layer with caching awareness.
    Subclasses define connector-specific field mappings and override the
    CONNECTOR class variable.

    Attributes:
        FIELD_MAP: Mapping of metric names to connector metadata fields
        CONNECTOR: Identifier for the connector (overridden by subclasses)
    """

    # To be defined by subclasses - maps metric names to connector metadata fields
    FIELD_MAP: ClassVar[dict[str, str]] = {}

    # Connector name to be overridden by subclasses
    CONNECTOR: ClassVar[str] = ""

    async def resolve(self, track_ids: list[int], metric_name: str) -> dict[int, Any]:
        """Resolve a metric for multiple tracks.

        Implements a caching strategy that:
        1. Checks for cached values using TrackMetricsRepository
        2. For missing values, fetches from connector_metadata
        3. Saves new values back to the track_metrics table
        4. Returns all values with appropriate type conversion

        Args:
            track_ids: List of internal track IDs to resolve metrics for
            metric_name: Name of the metric to resolve

        Returns:
            Dictionary mapping track IDs to their metric values
        """
        from src.infrastructure.config import get_logger
        from src.infrastructure.persistence.repositories.track.connector import (
            TrackConnectorRepository,
        )
        from src.infrastructure.persistence.repositories.track.metrics import (
            TrackMetricsRepository,
        )

        logger = get_logger(__name__).bind(
            service="connectors",
            module="narada.integrations.base_connector",
            connector=self.CONNECTOR,
            metric_name=metric_name,
        )

        if not track_ids:
            return {}

        # Get current value to respect TTL
        max_age = get_metric_freshness(metric_name)

        async with get_session() as session:
            metrics_repo = TrackMetricsRepository(session)
            # Get cached metrics that aren't stale
            cached_values = await metrics_repo.get_track_metrics(
                track_ids,
                metric_type=metric_name,
                connector=self.CONNECTOR,
                max_age_hours=max_age,
            )

            # Find IDs with missing metrics
            missing_ids = [tid for tid in track_ids if tid not in cached_values]

            if missing_ids:
                logger.info(
                    f"Found {len(missing_ids)} tracks with missing {metric_name} data",
                    track_count=len(track_ids),
                    missing_count=len(missing_ids),
                    missing_sample=missing_ids[:5],
                )

                # Get the source field from mapping
                field_name = self.FIELD_MAP.get(metric_name)
                if not field_name:
                    logger.warning(f"No field mapping for {metric_name}")
                    return cached_values

                # Retrieve metadata for missing tracks
                connector_repo = TrackConnectorRepository(session)
                metadata = await connector_repo.get_connector_metadata(
                    missing_ids, self.CONNECTOR, field_name
                )

                # Save new metrics
                metrics_to_save = []
                for track_id, value in metadata.items():
                    if value is not None and not isinstance(value, dict):
                        try:
                            float_value = float(value)
                            metrics_to_save.append((
                                track_id,
                                self.CONNECTOR,
                                metric_name,
                                float_value,
                            ))
                            cached_values[track_id] = value
                        except (ValueError, TypeError):
                            logger.warning(
                                f"Cannot convert {value} to float for {metric_name}"
                            )

                # Batch save all metrics
                if metrics_to_save:
                    saved_count = await metrics_repo.save_track_metrics(metrics_to_save)
                    await session.commit()  # Important: commit the changes
                    logger.info(f"Saved {saved_count} new metrics for {metric_name}")

        return cached_values


@define(frozen=True, slots=True)
class BatchProcessor[T, R]:
    """Generic batch processor with concurrency control and backoff capabilities.

    This utility simplifies batch processing operations across all connectors,
    standardizing concurrency control, batching logic and error handling.
    Uses configuration values from config.py.

    Attributes:
        batch_size: Maximum number of items to process in a single batch
        concurrency_limit: Maximum number of concurrent processing tasks
        retry_count: Maximum number of retry attempts on failure
        retry_base_delay: Base delay between retries (seconds)
        retry_max_delay: Maximum delay between retries (seconds)
        request_delay: Delay between individual requests (seconds)
        logger_instance: Logger for recording processing events
    """

    batch_size: int
    concurrency_limit: int
    retry_count: int
    retry_base_delay: float
    retry_max_delay: float
    request_delay: float
    logger_instance: Any = field(factory=lambda: get_logger(__name__))

    def _on_backoff(self, details):
        """Log backoff event."""
        wait = details["wait"]
        tries = details["tries"]
        target = details["target"].__name__
        args = details["args"]
        kwargs = details["kwargs"]

        self.logger_instance.warning(
            f"Backing off {target} (attempt {tries})",
            retry_delay=f"{wait:.2f}s",
            args=args,
            kwargs=kwargs,
        )

    def _on_giveup(self, details):
        """Log when we give up retrying."""
        target = details["target"].__name__
        tries = details["tries"]
        elapsed = details["elapsed"]
        exception = details.get("exception")

        self.logger_instance.error(
            f"All {tries} attempts failed for {target}",
            elapsed_time=f"{elapsed:.2f}s",
            error=str(exception) if exception else "Unknown error",
            error_type=type(exception).__name__ if exception else "Unknown",
        )

    async def process(
        self,
        items: list[T],
        process_func: Callable[[T], Awaitable[R]],
        progress_callback: Callable[[str, dict], None] | None = None,
        progress_task_name: str = "batch_processing",
        progress_description: str = "Processing items",
    ) -> list[R]:
        """Process items in batches with controlled concurrency and exponential backoff.

        Args:
            items: List of items to process
            process_func: Async function that processes a single item
            progress_callback: Optional callback for progress updates
            progress_task_name: Task name for progress tracking
            progress_description: Human-readable description for progress

        Returns:
            List of results in the same order as input items
        """
        if not items:
            return []

        results: list[R] = []
        semaphore = asyncio.Semaphore(self.concurrency_limit)
        total_batches = (len(items) + self.batch_size - 1) // self.batch_size
        total_items = len(items)
        processed_items = 0
        
        # Emit batch processing started event
        if progress_callback:
            progress_callback("batch_started", {
                "task_name": progress_task_name,
                "total_batches": total_batches,
                "total_items": total_items,
                "description": progress_description,
            })

        @backoff.on_exception(
            backoff.expo,
            Exception,  # Catch all exceptions - can be customized for specific error types
            max_tries=self.retry_count + 1,  # +1 because first attempt counts
            max_time=None,  # No time limit, just use max_tries
            factor=self.retry_base_delay,
            max_value=self.retry_max_delay,
            jitter=backoff.full_jitter,
            on_backoff=self._on_backoff,
            on_giveup=self._on_giveup,
        )
        async def process_with_backoff(item: T) -> R:
            """Process an item with automatic backoff on failures."""
            async with semaphore:
                # Add delay between requests to avoid rate limits
                if self.request_delay > 0:
                    await asyncio.sleep(self.request_delay)
                return await process_func(item)

        # Process in batches for memory efficiency and rate limit management
        for i in range(0, len(items), self.batch_size):
            batch = items[i : i + self.batch_size]
            current_batch = i // self.batch_size + 1
            batch_start_items = processed_items
            
            self.logger_instance.debug(
                f"Processing batch {current_batch}/{total_batches}",
                batch_size=len(batch),
                total_items=len(items),
            )
            
            # Emit batch started event
            if progress_callback:
                progress_callback("batch_progress", {
                    "task_name": progress_task_name,
                    "batch_number": current_batch,
                    "total_batches": total_batches,
                    "batch_size": len(batch),
                    "items_processed": processed_items,
                    "total_items": total_items,
                    "description": f"{progress_description} (batch {current_batch}/{total_batches})",
                })

            # Create a progress-aware wrapper for individual item processing
            async def process_item_with_progress(item: T, item_index: int, batch_start: int = batch_start_items, batch_num: int = current_batch) -> R:
                """Process item and emit progress event."""
                result = await process_with_backoff(item)
                
                # Emit individual item progress every 10 items to avoid spam
                current_item = batch_start + item_index + 1
                if progress_callback and (current_item % 10 == 0 or current_item == total_items):
                    # Try to get a meaningful description from the item
                    item_desc = ""
                    try:
                        if hasattr(item, 'title') and hasattr(item, 'artists'):
                            artists = getattr(item, 'artists', [])
                            if artists and hasattr(artists[0], 'name'):
                                artist_name = artists[0].name
                            else:
                                artist_name = "Unknown Artist"
                            item_desc = f"{artist_name} - {getattr(item, 'title', 'Unknown Track')}"
                        elif hasattr(item, 'name'):
                            item_desc = str(getattr(item, 'name', ''))
                        elif hasattr(item, 'id'):
                            item_desc = f"Item {getattr(item, 'id', '')}"
                    except (AttributeError, IndexError):
                        # Fallback if item structure is unexpected
                        item_desc = f"Item {item_index + 1}"
                    
                    progress_callback("track_processed", {
                        "task_name": progress_task_name,
                        "items_processed": current_item,
                        "total_items": total_items,
                        "current_batch": batch_num,
                        "item_description": item_desc,
                        "description": f"Processed {current_item}/{total_items} items",
                    })
                
                return result

            # Use gather with return_exceptions=True to handle errors without failing the whole batch
            batch_results = await asyncio.gather(
                *[process_item_with_progress(item, idx) for idx, item in enumerate(batch)], 
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
            processed_items += len(batch)

            # Emit batch completed event
            if progress_callback:
                progress_callback("batch_completed", {
                    "task_name": progress_task_name,
                    "batch_number": current_batch,
                    "total_batches": total_batches,
                    "items_processed": processed_items,
                    "total_items": total_items,
                    "batch_results": len(valid_results),
                    "batch_failures": len(batch_results) - len(valid_results),
                })

            # Log batch completion
            self.logger_instance.debug(
                f"Batch {current_batch} complete",
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
