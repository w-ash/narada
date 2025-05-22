"""Track metrics repository for tracking play counts and other metrics."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from attrs import define
from sqlalchemy.ext.asyncio import AsyncSession

from narada.config import get_logger, resilient_operation
from narada.database.db_connection import get_session
from narada.database.db_models import DBTrackMetric
from narada.integrations.metrics_registry import connector_metrics, metric_resolvers
from narada.repositories.base_repo import BaseModelMapper, BaseRepository
from narada.repositories.repo_decorator import db_operation

logger = get_logger(__name__)

# Global queue for pending metrics operations
# This allows us to batch metrics operations and avoid database locks
# Format: list of (track_id, connector, metric_name, value)
_METRICS_QUEUE: list[tuple[int, str, str, float]] = []
_METRICS_LOCK = asyncio.Lock()
_METRICS_TASK = None


@define(frozen=True, slots=True)
class TrackMetricMapper(BaseModelMapper[DBTrackMetric, dict[str, Any]]):
    """Mapper for track metrics to simple dictionaries."""

    @staticmethod
    async def to_domain(db_model: DBTrackMetric) -> dict[str, Any]:
        """Convert DB metric to dictionary representation."""
        if not db_model:
            return None

        return {
            "id": db_model.id,
            "track_id": db_model.track_id,
            "connector_name": db_model.connector_name,
            "metric_type": db_model.metric_type,
            "value": db_model.value,
            "collected_at": db_model.collected_at,
        }

    @staticmethod
    def to_db(domain_model: dict[str, Any]) -> DBTrackMetric:
        """Convert dictionary to DB model."""
        return DBTrackMetric(
            track_id=domain_model.get("track_id"),
            connector_name=domain_model.get("connector_name"),
            metric_type=domain_model.get("metric_type"),
            value=domain_model.get("value"),
            collected_at=domain_model.get("collected_at", datetime.now(UTC)),
        )

    @staticmethod
    def get_default_relationships() -> list[str]:
        """Get default relationships to load.

        DBTrackMetric has no relationships that need eager loading.
        """
        return []


class TrackMetricsRepository(BaseRepository[DBTrackMetric, dict[str, Any]]):
    """Repository for track metrics operations."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with session."""
        super().__init__(
            session=session,
            model_class=DBTrackMetric,
            mapper=TrackMetricMapper(),
        )

    # -------------------------------------------------------------------------
    # PUBLIC API METHODS
    # -------------------------------------------------------------------------

    @db_operation("get_track_metrics")
    async def get_track_metrics(
        self,
        track_ids: list[int],
        metric_type: str = "play_count",
        connector: str = "lastfm",
        max_age_hours: int = 24,
    ) -> dict[int, Any]:
        """Get cached metrics with TTL awareness."""
        if not track_ids:
            return {}

        # Calculate cutoff time
        cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)

        # Use find_by with optimized conditions
        result = await self.find_by(
            conditions=[
                self.model_class.track_id.in_(track_ids),
                self.model_class.connector_name == connector,
                self.model_class.metric_type == metric_type,
                self.model_class.collected_at >= cutoff,
            ],
            order_by=("collected_at", False),  # DESC order
        )

        # Process results - only keep most recent value per track
        metrics_dict = {}
        for metric in result:
            track_id = metric["track_id"]
            if track_id not in metrics_dict:
                # Keep the original type - important for non-integer metrics like spotify_popularity
                metrics_dict[track_id] = metric["value"]

        logger.debug(
            f"Retrieved {len(metrics_dict)}/{len(track_ids)} track metrics",
            metric_type=metric_type,
            connector=connector,
        )

        return metrics_dict

    @db_operation("save_track_metrics")
    async def save_track_metrics(
        self,
        metrics: list[tuple[int, str, str, float]],
    ) -> int:
        """Save metrics for multiple tracks efficiently with SQLite upsert.

        Prevents duplicate metrics by using the unique constraint defined in
        the DBTrackMetric model and SQLite's ON CONFLICT clause to perform
        an update when a constraint violation occurs.
        """
        if not metrics:
            return 0

        now = datetime.now(UTC)

        # Use SQLAlchemy's dialect-specific upsert functionality
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        # Prepare values for insertion
        values = [
            {
                "track_id": track_id,
                "connector_name": connector_name,
                "metric_type": metric_type,
                "value": value,
                "collected_at": now,
            }
            for track_id, connector_name, metric_type, value in metrics
        ]

        # Build the insert statement with ON CONFLICT clause
        # This uses the unique constraint defined in the DBTrackMetric model
        stmt = sqlite_insert(DBTrackMetric).values(values)

        # Add the ON CONFLICT clause to update existing metrics
        stmt = stmt.on_conflict_do_update(
            index_elements=["track_id", "connector_name", "metric_type"],
            set_={
                "value": stmt.excluded.value,
                "collected_at": stmt.excluded.collected_at,
            },
        )

        await self.session.execute(stmt)
        await self.session.flush()

        return len(metrics)

    @db_operation("get_metric_history")
    async def get_metric_history(
        self,
        track_id: int,
        metric_type: str = "play_count",
        connector: str = "lastfm",
        days: int = 30,
    ) -> list[tuple[datetime, float]]:
        """Get history of a metric over time."""
        # Calculate cutoff time
        cutoff = datetime.now(UTC) - timedelta(days=days)

        # Use find_by with ordering
        metrics = await self.find_by(
            conditions=[
                self.model_class.track_id == track_id,
                self.model_class.connector_name == connector,
                self.model_class.metric_type == metric_type,
                self.model_class.collected_at >= cutoff,
            ],
            order_by=("collected_at", True),  # ASC order
        )

        # Convert to tuples of (timestamp, value)
        return [(m["collected_at"], m["value"]) for m in metrics]


async def process_metrics_for_track(
    session: AsyncSession,
    track_id: int,
    connector: str,
    metadata: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Process and save metrics for a track within an existing transaction.

    This version is designed to be called within an existing transaction,
    using the same session to maintain transaction integrity.

    Args:
        session: The active SQLAlchemy session (within an existing transaction)
        track_id: The track ID to process metrics for
        connector: The connector name (spotify, lastfm, etc.)
        metadata: Optional pre-fetched metadata (to avoid redundant lookups)

    Returns:
        Dictionary mapping metric names to values
    """
    if connector not in connector_metrics or not connector_metrics[connector]:
        return {}

    # Track metrics to avoid redundant lookups
    results = {}
    metric_batch = []

    try:
        # Step 1: Get metadata if not provided
        if metadata is None:
            from narada.repositories.track.connector import TrackConnectorRepository

            connector_repo = TrackConnectorRepository(session)
            metadata = await connector_repo.get_connector_metadata(
                [track_id], connector
            )

        if not metadata or track_id not in metadata:
            return {}

        # Step 2: Extract metric values from metadata
        for metric_name in connector_metrics[connector]:
            if metric_name not in metric_resolvers:
                continue

            # Get field name from resolver
            resolver = metric_resolvers[metric_name]
            resolver_impl = resolver  # type: ignore
            field_name = getattr(resolver_impl, "FIELD_MAP", {}).get(metric_name)

            if not field_name:
                continue

            # Extract and convert value
            value = metadata[track_id].get(field_name)
            if value is None:
                continue

            try:
                float_value = float(value)
                metric_batch.append((
                    track_id,
                    connector,
                    metric_name,
                    float_value,
                ))
                results[metric_name] = float_value
            except (ValueError, TypeError):
                logger.warning(f"Cannot convert {value} to float for {metric_name}")

        # Step 3: Save metrics within the same transaction
        if metric_batch:
            metrics_repo = TrackMetricsRepository(session)

            # Process in small batches for better performance
            max_batch_size = 5
            for i in range(0, len(metric_batch), max_batch_size):
                batch_slice = metric_batch[i : i + max_batch_size]
                await metrics_repo.save_track_metrics(batch_slice)

            logger.debug(
                f"Saved {len(metric_batch)} metrics for track {track_id} in existing transaction",
                connector=connector,
                metrics=[m[2] for m in metric_batch],
            )
    except Exception as e:
        logger.error(
            f"Error processing metrics for track {track_id} from {connector}: {e}",
            exc_info=True,
        )
        # We don't raise the exception since this would roll back the parent transaction

    return results


@resilient_operation("resolve_connector_metrics")
async def resolve_connector_metrics(track_id: int, connector: str) -> dict[str, Any]:
    """Resolve and save all metrics for a track from a specific connector.

    This function efficiently triggers metric resolution for all metrics
    associated with a specific connector for a single track. It creates its
    own transaction to perform the operation.

    For operations within an existing transaction, use process_metrics_for_track
    instead to maintain transaction integrity.

    Args:
        track_id: The track ID to resolve metrics for
        connector: The connector name (spotify, lastfm, etc.)

    Returns:
        Dictionary of resolved metrics {metric_name: value}
    """
    if connector not in connector_metrics or not connector_metrics[connector]:
        return {}

    # Use a single session for the entire operation to maintain transaction integrity
    async with get_session() as session:
        # Get metadata using the same session
        from narada.repositories.track.connector import TrackConnectorRepository

        connector_repo = TrackConnectorRepository(session)
        metadata = await connector_repo.get_connector_metadata([track_id], connector)

        if not metadata or track_id not in metadata:
            logger.debug(f"No metadata found for track {track_id} from {connector}")
            return {}

        # Process metrics using the same session
        results = await process_metrics_for_track(
            session, track_id, connector, metadata
        )

        # Commit after all operations are complete
        await session.commit()

    return results
