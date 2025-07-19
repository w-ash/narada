"""Connector metadata management service.

This service handles fetching, storing, and retrieving connector-specific track metadata.
It focuses solely on metadata operations without any identity resolution or freshness decisions.
"""

from typing import Any

from src.config import get_logger
from src.domain.matching.types import MatchResultsById
from src.infrastructure.persistence.repositories.track import TrackRepositories

logger = get_logger(__name__)


class ConnectorMetadataManager:
    """Manages connector-specific track metadata operations.

    This service is responsible only for metadata operations:
    - Fetching fresh metadata from connector APIs
    - Storing metadata with timestamps in the database
    - Retrieving cached metadata for tracks

    It does NOT handle:
    - Track identity resolution
    - Freshness policy decisions
    - Confidence scores or matching evidence
    """

    def __init__(self, track_repos: TrackRepositories) -> None:
        """Initialize with repository container.

        Args:
            track_repos: Repository container for database operations.
        """
        self.track_repos = track_repos

    async def fetch_fresh_metadata(
        self,
        identity_mappings: MatchResultsById,
        connector: str,
        connector_instance: Any,
        track_ids_to_refresh: list[int],
        **additional_options: Any,
    ) -> dict[int, dict[str, Any]]:
        """Fetch fresh metadata from connector API for specific tracks.

        Args:
            identity_mappings: Track identity mappings from TrackIdentityResolver.
            connector: Connector name.
            connector_instance: Connector implementation.
            track_ids_to_refresh: Track IDs that need fresh metadata.
            **additional_options: Options forwarded to connector.

        Returns:
            Dictionary mapping track IDs to fresh metadata.
        """
        if not track_ids_to_refresh:
            return {}

        with logger.contextualize(
            operation="fetch_fresh_metadata",
            connector=connector,
            track_count=len(track_ids_to_refresh),
        ):
            logger.info(
                f"Fetching fresh metadata for {len(track_ids_to_refresh)} tracks from {connector}"
            )

            # Filter identity mappings to only include tracks that need refresh
            tracks_to_refresh = {
                track_id: result
                for track_id, result in identity_mappings.items()
                if track_id in track_ids_to_refresh and result.success
            }

            if not tracks_to_refresh:
                logger.warning(
                    "No valid identity mappings found for tracks needing refresh"
                )
                return {}

            # CRITICAL FIX: Use direct metadata fetch for mapped tracks instead of expensive matching
            # All connectors should use direct API calls when we have existing mappings
            fresh_metadata = await self._fetch_direct_metadata_by_connector_ids(
                tracks_to_refresh, connector, connector_instance, **additional_options
            )

            # Store fresh metadata in database
            if fresh_metadata:
                await self._store_fresh_metadata(fresh_metadata, connector)

            return fresh_metadata

    async def get_cached_metadata(
        self,
        track_ids: list[int],
        connector: str,
    ) -> dict[int, dict[str, Any]]:
        """Get cached metadata for tracks from database.

        Args:
            track_ids: Track IDs to get metadata for.
            connector: Connector name.

        Returns:
            Dictionary mapping track IDs to cached metadata.
        """
        if not track_ids:
            return {}

        with logger.contextualize(
            operation="get_cached_metadata",
            connector=connector,
            track_count=len(track_ids),
        ):
            logger.debug(
                f"Retrieving cached metadata for {len(track_ids)} tracks from {connector}"
            )

            # Get metadata from database
            metadata = await self.track_repos.connector.get_connector_metadata(
                track_ids, connector
            )

            logger.debug(f"Retrieved cached metadata for {len(metadata)} tracks")
            return metadata

    async def get_all_metadata(
        self,
        track_ids: list[int],
        connector: str,
        fresh_metadata: dict[int, dict[str, Any]] | None = None,
    ) -> dict[int, dict[str, Any]]:
        """Get all metadata for tracks, combining fresh and cached data.

        Args:
            track_ids: Track IDs to get metadata for.
            connector: Connector name.
            fresh_metadata: Fresh metadata to merge with cached data.

        Returns:
            Dictionary mapping track IDs to complete metadata.
        """
        if not track_ids:
            return {}

        with logger.contextualize(
            operation="get_all_metadata",
            connector=connector,
            track_count=len(track_ids),
        ):
            # Get cached metadata
            cached_metadata = await self.get_cached_metadata(track_ids, connector)

            # Merge with fresh metadata if provided
            if fresh_metadata:
                all_metadata = {**cached_metadata, **fresh_metadata}
                logger.debug(
                    f"Combined {len(cached_metadata)} cached + {len(fresh_metadata)} fresh = {len(all_metadata)} total metadata entries"
                )
            else:
                all_metadata = cached_metadata
                logger.debug(f"Using {len(all_metadata)} cached metadata entries")

            return all_metadata

    async def _store_fresh_metadata(
        self,
        fresh_metadata: dict[int, dict[str, Any]],
        connector: str,
    ) -> None:
        """Store fresh metadata in database with current timestamp.

        Args:
            fresh_metadata: Fresh metadata to store.
            connector: Connector name.
        """
        if not fresh_metadata:
            return

        with logger.contextualize(
            operation="store_fresh_metadata",
            connector=connector,
            metadata_count=len(fresh_metadata),
        ):
            logger.info(f"Storing fresh metadata for {len(fresh_metadata)} tracks")

            # Get existing connector tracks to update their metadata
            track_ids = list(fresh_metadata.keys())
            logger.debug(f"Getting connector mappings for {len(track_ids)} tracks")
            existing_mappings = await self.track_repos.connector.get_connector_mappings(
                track_ids, connector
            )

            logger.debug(
                f"Found {len(existing_mappings) if existing_mappings else 0} existing mappings"
            )
            if not existing_mappings:
                logger.warning(
                    "No existing connector mappings found for metadata storage"
                )
                return

            # Process metrics for ALL tracks with fresh metadata (not just those with existing mappings)
            updates_count = 0
            metrics_processed_count = 0

            for track_id, metadata in fresh_metadata.items():
                logger.debug(
                    f"Processing track {track_id}, metadata keys: {list(metadata.keys()) if isinstance(metadata, dict) else type(metadata)}"
                )

                try:
                    # ALWAYS process metrics from fresh metadata (regardless of mapping status)
                    from src.infrastructure.persistence.repositories.track.metrics import (
                        process_metrics_for_track,
                    )

                    metrics_result = await process_metrics_for_track(
                        session=self.track_repos.connector.session,
                        track_id=track_id,
                        connector=connector,
                        metadata={track_id: metadata},
                    )
                    logger.debug(
                        f"Processed {len(metrics_result)} metrics for track {track_id}"
                    )
                    metrics_processed_count += 1

                    # Update connector mapping metadata (only if mapping exists)
                    if (
                        track_id in existing_mappings
                        and connector in existing_mappings[track_id]
                    ):
                        connector_id = existing_mappings[track_id][connector]
                        logger.debug(
                            f"Found mapping for track {track_id} -> connector_id {connector_id}"
                        )

                        # Update the connector track metadata
                        logger.debug(
                            f"Calling save_mapping_confidence for track {track_id}"
                        )
                        await self.track_repos.connector.save_mapping_confidence(
                            track_id=track_id,
                            connector=connector,
                            connector_id=connector_id,
                            confidence=80,  # Keep existing confidence
                            metadata=metadata,
                        )
                        updates_count += 1
                        logger.debug(
                            f"Successfully updated metadata for track {track_id}"
                        )
                    else:
                        logger.debug(
                            f"No mapping found for track {track_id}, but metrics still processed"
                        )

                except Exception as e:
                    logger.error(
                        f"Error processing track {track_id}: {e}", exc_info=True
                    )

            logger.info(
                f"Successfully stored fresh metadata for {updates_count} tracks and processed metrics for {metrics_processed_count} tracks"
            )

    def _convert_track_info_results(
        self, track_info_results: dict[int, Any]
    ) -> dict[int, dict[str, Any]]:
        """Convert track info objects to metadata dictionaries.

        Single source of truth for metadata conversion logic.
        Handles both to_dict() methods and attrs classes.

        Args:
            track_info_results: Dictionary mapping track IDs to track info objects

        Returns:
            Dictionary mapping track IDs to metadata dictionaries
        """
        metadata = {}

        for track_id, track_info in track_info_results.items():
            if track_info and hasattr(track_info, "to_dict"):
                metadata[track_id] = track_info.to_dict()
            elif track_info and isinstance(track_info, dict):
                # Handle case where track_info is already a dict
                metadata[track_id] = track_info
            elif track_info:
                # Handle attrs classes (like LastFMTrackInfo)
                try:
                    from attrs import asdict

                    metadata[track_id] = asdict(track_info)
                except (ImportError, TypeError):
                    # Fallback for unexpected types
                    metadata[track_id] = {}

        return metadata

    async def _fetch_direct_metadata_by_connector_ids(
        self,
        tracks_to_refresh: dict[int, Any],
        connector: str,
        connector_instance: Any,
        **additional_options: Any,
    ) -> dict[int, dict[str, Any]]:
        """Fetch metadata directly using connector IDs, bypassing expensive matching.

        This method is the key performance optimization - instead of running expensive
        matching for tracks that already have connector mappings, we use direct API
        calls with the existing connector IDs.

        Args:
            tracks_to_refresh: Dict of track_id -> MatchResult for tracks needing refresh
            connector: Connector name
            connector_instance: Connector implementation
            **additional_options: Additional options forwarded to connector

        Returns:
            Dictionary mapping track IDs to fresh metadata
        """
        if not tracks_to_refresh:
            return {}

        fresh_metadata = {}

        with logger.contextualize(
            operation="fetch_direct_metadata_by_connector_ids",
            connector=connector,
            track_count=len(tracks_to_refresh),
        ):
            logger.info(
                f"PERFORMANCE OPTIMIZATION: Fetching metadata directly for {len(tracks_to_refresh)} {connector} tracks with existing mappings"
            )

            # Get connector track information for direct API calls
            track_ids = list(tracks_to_refresh.keys())
            existing_mappings = await self.track_repos.connector.get_connector_mappings(
                track_ids, connector
            )

            if not existing_mappings:
                logger.warning(f"No connector mappings found for {connector} tracks")
                return {}

            # Build list of tracks for direct API calls
            tracks_for_api = []
            track_id_to_connector_id = {}

            for track_id, result in tracks_to_refresh.items():
                if (
                    track_id in existing_mappings
                    and connector in existing_mappings[track_id]
                ):
                    connector_id = existing_mappings[track_id][connector]
                    track_id_to_connector_id[track_id] = connector_id

                    # Use the track from the MatchResult
                    track = result.track
                    tracks_for_api.append(track)

            if not tracks_for_api:
                logger.warning(f"No valid connector mappings found for {connector}")
                return {}

            logger.info(
                f"Making direct API calls for {len(tracks_for_api)} {connector} tracks"
            )

            try:
                # Batch-first architecture: Only use batch method (single operations are degenerate case)
                if not (
                    hasattr(connector_instance, "batch_get_track_info")
                    and callable(connector_instance.batch_get_track_info)
                ):
                    logger.error(
                        f"Connector {connector} must implement batch_get_track_info method"
                    )
                    return {}

                # Use batch method for all operations (batch-first design)
                batch_method = connector_instance.batch_get_track_info
                track_info_results = await batch_method(
                    tracks_for_api, **additional_options
                )

                # Convert results to our format (single conversion logic)
                fresh_metadata.update(
                    self._convert_track_info_results(track_info_results)
                )

                logger.info(
                    f"Successfully fetched direct metadata for {len(fresh_metadata)} tracks"
                )

            except Exception as e:
                logger.error(f"Error fetching direct metadata from {connector}: {e}")
                return {}

        return fresh_metadata
