"""Metadata freshness controller service.

This service determines when connector metadata needs refreshing based on configurable
freshness policies. It focuses solely on freshness decisions without any data fetching.
"""

from datetime import UTC, datetime, timedelta

from src.config import get_config, get_logger
from src.infrastructure.persistence.repositories.track import TrackRepositories

logger = get_logger(__name__)


class MetadataFreshnessController:
    """Controls when connector metadata needs refreshing based on configured policies.

    This service is responsible only for freshness decisions:
    - Determining which tracks have stale metadata
    - Applying connector-specific freshness policies
    - Cache invalidation logic based on timestamps

    It does NOT handle:
    - Actual metadata fetching or storage
    - Track identity resolution
    - Service-specific data extraction
    """

    def __init__(self, track_repos: TrackRepositories) -> None:
        """Initialize with repository container.

        Args:
            track_repos: Repository container for database operations.
        """
        self.track_repos = track_repos

    async def get_stale_tracks(
        self,
        track_ids: list[int],
        connector: str,
        max_age_hours: float | None = None,
    ) -> list[int]:
        """Get list of track IDs that have stale metadata needing refresh.

        Args:
            track_ids: Track IDs to check for staleness.
            connector: Connector name for freshness policy lookup.
            max_age_hours: Override freshness policy. If None, uses config default.

        Returns:
            List of track IDs that need metadata refresh.
        """
        if not track_ids:
            return []

        # Get freshness policy for this connector
        if max_age_hours is None:
            max_age_hours = self._get_freshness_policy(connector)

        # If no freshness policy defined, consider all data fresh
        if max_age_hours is None:
            logger.debug(
                f"No freshness policy for {connector}, considering all data fresh"
            )
            return []

        with logger.contextualize(
            operation="get_stale_tracks",
            connector=connector,
            max_age_hours=max_age_hours,
            track_count=len(track_ids),
        ):
            logger.info(
                f"Checking freshness for {len(track_ids)} tracks (max age: {max_age_hours}h)"
            )

            # Calculate cutoff time for freshness
            cutoff_time = datetime.now(UTC) - timedelta(hours=max_age_hours)
            logger.debug(f"Data older than {cutoff_time} considered stale")

            # Get both metadata timestamps and metrics timestamps
            metadata_with_timestamps = (
                await self.track_repos.connector.get_connector_metadata_with_timestamps(
                    track_ids, connector
                )
            )
            
            # Also check track metrics timestamps for this connector
            metrics_timestamps = await self._get_metrics_timestamps(track_ids, connector)

            stale_track_ids = []

            for track_id in track_ids:
                # Check both metadata and metrics timestamps to determine freshness
                metadata_info = metadata_with_timestamps.get(track_id)
                metrics_timestamp = metrics_timestamps.get(track_id)
                
                # Get the most recent timestamp from either source
                last_updated = None
                timestamp_source = "none"
                
                if metadata_info and metadata_info.get("last_updated"):
                    last_updated = metadata_info["last_updated"]
                    timestamp_source = "metadata"
                    
                    # Ensure timezone consistency - database stores UTC timestamps
                    # If no timezone info, assume it's already UTC (our standard)
                    if last_updated and last_updated.tzinfo is None:
                        last_updated = last_updated.replace(tzinfo=UTC)
                
                # If metrics timestamp is more recent, use that instead
                if metrics_timestamp and (last_updated is None or metrics_timestamp > last_updated):
                    last_updated = metrics_timestamp
                    timestamp_source = "metrics"

                if not last_updated or last_updated < cutoff_time:
                    # Data is stale or timestamp is missing
                    stale_track_ids.append(track_id)
                    logger.debug(
                        f"Track {track_id}: stale data (last_updated: {last_updated}, source: {timestamp_source})"
                    )
                else:
                    logger.debug(
                        f"Track {track_id}: fresh data (last_updated: {last_updated}, source: {timestamp_source})"
                    )

            logger.info(f"Found {len(stale_track_ids)} tracks with stale data out of {len(track_ids)} checked")
            return stale_track_ids

    async def _get_metrics_timestamps(
        self, track_ids: list[int], connector: str
    ) -> dict[int, datetime]:
        """Get most recent metrics collection timestamps for tracks from this connector.
        
        Args:
            track_ids: Track IDs to check metrics timestamps for.
            connector: Connector name to filter metrics by.
            
        Returns:
            Dictionary mapping track_id to most recent collected_at timestamp.
        """
        if not track_ids:
            return {}
            
        try:
            # Get the most recent metrics timestamp for each track from this connector
            from sqlalchemy import func, select

            from src.infrastructure.persistence.database.db_models import DBTrackMetric
            
            # Query for the most recent collected_at timestamp for each track
            stmt = (
                select(
                    DBTrackMetric.track_id,
                    func.max(DBTrackMetric.collected_at).label("latest_collected_at")
                )
                .where(
                    DBTrackMetric.track_id.in_(track_ids),
                    DBTrackMetric.connector_name == connector,
                    DBTrackMetric.is_deleted == False  # noqa: E712
                )
                .group_by(DBTrackMetric.track_id)
            )
            
            result = await self.track_repos.metrics.session.execute(stmt)
            rows = result.fetchall()
            
            timestamps = {}
            for row in rows:
                track_id = row[0]
                collected_at = row[1]
                
                # Ensure UTC timezone for consistency - database stores UTC timestamps
                # If no timezone info, assume it's already UTC (our standard)
                if collected_at and collected_at.tzinfo is None:
                    collected_at = collected_at.replace(tzinfo=UTC)
                    
                timestamps[track_id] = collected_at
            
            logger.debug(f"Retrieved metrics timestamps for {len(timestamps)}/{len(track_ids)} tracks from {connector}")
            return timestamps
            
        except Exception as e:
            logger.warning(f"Failed to get metrics timestamps for {connector}: {e}")
            return {}

    def _get_freshness_policy(self, connector: str) -> float | None:
        """Get freshness policy for a connector from configuration.

        Args:
            connector: Connector name.

        Returns:
            Maximum age in hours before data is considered stale, or None if no policy.
        """
        config_key = f"ENRICHER_DATA_FRESHNESS_{connector.upper()}"
        max_age_hours = get_config(config_key)

        if max_age_hours is not None:
            logger.debug(
                f"Using freshness policy for {connector}: {max_age_hours} hours"
            )
        else:
            logger.debug(f"No freshness policy configured for {connector}")

        return max_age_hours
