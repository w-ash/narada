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

            # Get metadata with timestamps for freshness check
            metadata_with_timestamps = (
                await self.track_repos.connector.get_connector_metadata_with_timestamps(
                    track_ids, connector
                )
            )

            if not metadata_with_timestamps:
                # No metadata exists, all tracks need refresh
                logger.info(
                    f"No metadata found for any tracks, all {len(track_ids)} need refresh"
                )
                return track_ids

            # Calculate cutoff time for freshness
            cutoff_time = datetime.now(UTC) - timedelta(hours=max_age_hours)
            logger.debug(f"Metadata older than {cutoff_time} considered stale")

            stale_track_ids = []

            for track_id in track_ids:
                if track_id not in metadata_with_timestamps:
                    # No metadata exists for this track
                    stale_track_ids.append(track_id)
                    logger.debug(f"Track {track_id}: no metadata exists")
                else:
                    metadata_info = metadata_with_timestamps[track_id]
                    last_updated = metadata_info["last_updated"]

                    # Ensure timezone consistency for comparison
                    if last_updated and last_updated.tzinfo is None:
                        # Convert naive datetime to UTC for comparison
                        last_updated = last_updated.replace(tzinfo=UTC)

                    if not last_updated or last_updated < cutoff_time:
                        # Metadata is stale or timestamp is missing
                        stale_track_ids.append(track_id)
                        logger.debug(
                            f"Track {track_id}: stale metadata (last_updated: {last_updated})"
                        )

            logger.info(f"Found {len(stale_track_ids)} tracks with stale metadata")
            return stale_track_ids

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
