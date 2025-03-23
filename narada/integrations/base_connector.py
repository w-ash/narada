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
import backoff

from narada.config import get_logger
from narada.core.protocols import get_metric_freshness, register_metric_resolver
from narada.database.db_connection import get_session

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

    CONNECTOR: ClassVar[str]

    async def resolve(self, track_ids: list[int], metric_name: str) -> dict[int, Any]:
        """Fetch stored service metrics from the database.

        Args:
            track_ids: List of internal track IDs
            metric_name: Metric to resolve (used to determine field name)

        Returns:
            Dictionary mapping track_id integers to metric values
        """
        ...


@define(frozen=True, slots=True)
class BaseMetricResolver:
    """Base class for resolving service metrics from persistence layer."""

    # To be defined by subclasses - maps metric names to connector metadata fields
    FIELD_MAP: ClassVar[dict[str, str]] = {}

    # Connector name to be overridden by subclasses
    CONNECTOR: ClassVar[str] = ""

    async def resolve(self, track_ids: list[int], metric_name: str) -> dict[int, Any]:
        """Resolve a metric for multiple tracks.

        This implementation:
        1. Checks for cached values using TrackMetricsRepository
        2. For missing values, fetches from connector_metadata
        3. Saves any new values found back to the track_metrics table
        4. Returns all values
        """
        from narada.config import get_logger
        from narada.repositories.track.connector import TrackConnectorRepository
        from narada.repositories.track.metrics import TrackMetricsRepository

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
            self.logger_instance.debug(
                f"Processing batch {i // self.batch_size + 1}/{(len(items) + self.batch_size - 1) // self.batch_size}",
                batch_size=len(batch),
                total_items=len(items),
            )

            # Use gather with return_exceptions=True to handle errors without failing the whole batch
            batch_results = await asyncio.gather(
                *[process_with_backoff(item) for item in batch], return_exceptions=True
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
                f"Batch {i // self.batch_size + 1} complete",
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
