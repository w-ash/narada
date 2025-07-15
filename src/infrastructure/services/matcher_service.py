"""Lean orchestrator service for track matching.

This service coordinates between providers and handles database operations,
while delegating the actual matching logic to providers and domain algorithms.
"""

from typing import Any

from src.application.utilities.progress_integration import with_progress
from src.domain.entities import TrackList
from src.domain.matching.types import MatchResult, MatchResultsById
from src.infrastructure.config import get_config, get_logger
from src.infrastructure.persistence.repositories.track import TrackRepositories

from .matching.providers import create_provider

logger = get_logger(__name__)


class MatcherService:
    """Orchestrates track matching across providers and database operations.

    Coordinates database lookups, provider delegation, and result persistence
    without containing business logic.
    """

    def __init__(self, track_repos: TrackRepositories) -> None:
        """Initialize with repository container.

        Args:
            track_repos: Repository container for database operations.
        """
        self.track_repos = track_repos

    @with_progress(
        "Matching tracks to external service",
        estimate_total=lambda track_list: len(track_list.tracks),
    )
    async def match_tracks(
        self,
        track_list: TrackList,
        connector: str,
        connector_instance: Any,
        **additional_options: Any,
    ) -> MatchResultsById:
        """Match tracks to external service with database caching.

        Args:
            track_list: Tracks to match.
            connector: Target service name.
            connector_instance: Service connector implementation.
            **additional_options: Options forwarded to providers.

        Returns:
            Track IDs mapped to match results.
        """
        # Acknowledge additional options to satisfy linter
        _ = additional_options

        if not track_list.tracks:
            return {}

        # Extract valid tracks with IDs for processing
        valid_tracks = [t for t in track_list.tracks if t.id is not None]
        if not valid_tracks:
            return {}

        # Get all track IDs for database lookup
        track_ids = [t.id for t in valid_tracks if t.id is not None]

        # Use contextual logging for the entire operation
        with logger.contextualize(
            operation="match_tracks", connector=connector, track_count=len(track_ids)
        ):
            # Step 1: Check database for existing mappings
            db_results = await self._get_existing_mappings(track_ids, connector)

            # Find tracks that need matching
            tracks_to_match = [t for t in valid_tracks if t.id not in db_results]

            if not tracks_to_match:
                logger.info(f"All {len(db_results)} tracks already mapped in database")
                return db_results

            # Step 2: Match new tracks using provider
            logger.info(
                f"Need to match {len(tracks_to_match)} new tracks to {connector}"
            )

            # Create provider for this connector
            provider = create_provider(connector, connector_instance)

            # Use provider to find matches
            match_results = await provider.find_potential_matches(
                tracks_to_match, **additional_options
            )

            # Step 3: Save new matches to database if any found
            if match_results:
                await self._persist_matches(match_results, connector)

            # Combine results and return
            return {**db_results, **match_results}

    async def _get_existing_mappings(
        self,
        track_ids: list[int],
        connector: str,
    ) -> MatchResultsById:
        """Retrieve existing mappings from database.

        Args:
            track_ids: Track IDs to check for existing mappings.
            connector: Target service name.

        Returns:
            Track IDs mapped to MatchResult objects for existing mappings.
        """
        if not track_ids:
            return {}

        with logger.contextualize(
            operation="get_existing_mappings", connector=connector
        ):
            logger.info(f"Fetching existing mappings for {len(track_ids)} tracks")

            db_mapped_tracks = {}

            # Step 1: Get all mappings in a single batch call
            existing_mappings = await self.track_repos.connector.get_connector_mappings(
                track_ids, connector
            )

            # Early return if no mappings found
            if not existing_mappings:
                logger.info("No existing mappings found")
                return {}

            # Step 2: Create a list of track IDs with mappings and their connector IDs
            mapped_track_ids = []
            track_to_connector_id = {}

            for track_id in track_ids:
                if (
                    track_id in existing_mappings
                    and connector in existing_mappings[track_id]
                ):
                    connector_id = existing_mappings[track_id][connector]
                    mapped_track_ids.append(track_id)
                    track_to_connector_id[track_id] = connector_id

            if not mapped_track_ids:
                logger.info("No valid mappings found")
                return {}

            # Step 3: Get all tracks in a single batch call
            tracks_by_id = await self.track_repos.core.find_tracks_by_ids(
                mapped_track_ids
            )

            # Step 4: Get metadata for all tracks in a batch
            connector_metadata = (
                await self.track_repos.connector.get_connector_metadata(
                    mapped_track_ids, connector
                )
            )

            # Process tracks with existing mappings
            for track_id in mapped_track_ids:
                # Skip if track not found
                if track_id not in tracks_by_id:
                    continue

                track = tracks_by_id[track_id]
                connector_id = track_to_connector_id[track_id]

                # Get service data from connector metadata
                service_data = connector_metadata.get(track_id, {})

                # Get mapping information
                mapping_data = await self.track_repos.connector.get_mapping_info(
                    track_id=track_id,
                    connector=connector,
                    connector_id=connector_id,
                )

                if not mapping_data:
                    continue

                confidence = mapping_data.get("confidence", 80)
                match_method = mapping_data.get("match_method", "unknown")
                confidence_evidence_dict = mapping_data.get("confidence_evidence", {})

                # Create evidence object if available
                evidence = None
                if confidence_evidence_dict:
                    from src.domain.matching.types import ConfidenceEvidence

                    evidence = ConfidenceEvidence(
                        base_score=confidence_evidence_dict.get("base_score", 0),
                        title_score=confidence_evidence_dict.get("title_score", 0.0),
                        artist_score=confidence_evidence_dict.get("artist_score", 0.0),
                        duration_score=confidence_evidence_dict.get(
                            "duration_score", 0.0
                        ),
                        title_similarity=confidence_evidence_dict.get(
                            "title_similarity", 0.0
                        ),
                        artist_similarity=confidence_evidence_dict.get(
                            "artist_similarity", 0.0
                        ),
                        duration_diff_ms=confidence_evidence_dict.get(
                            "duration_diff_ms", 0
                        ),
                        final_score=confidence_evidence_dict.get("final_score", 0),
                    )

                # Create result with clean separation between service data and match assessment
                db_mapped_tracks[track_id] = MatchResult(
                    track=track,
                    success=True,
                    connector_id=connector_id,
                    confidence=confidence,
                    match_method=match_method,
                    service_data=service_data,
                    evidence=evidence,
                )

            logger.info(f"Found {len(db_mapped_tracks)} existing mappings in database")
            return db_mapped_tracks

    async def _persist_matches(
        self,
        matches: MatchResultsById,
        connector: str,
    ) -> None:
        """Save matches to database with confidence evidence.

        Args:
            matches: Track IDs mapped to MatchResult objects.
            connector: Target service name.
        """
        if not matches:
            return

        with logger.contextualize(operation="persist_matches", connector=connector):
            logger.info(f"Persisting {len(matches)} matches to database")

            # Get all track ids for batch lookup
            track_ids = [
                result.track.id
                for result in matches.values()
                if result.track.id is not None
            ]

            if not track_ids:
                logger.warning("No valid track IDs found in matches")
                return

            # Get all tracks in a single batch operation
            tracks_by_id = await self.track_repos.core.find_tracks_by_ids(track_ids)

            batch_size = get_config("DEFAULT_API_BATCH_SIZE", 50)
            success_count = 0

            # Process matches in batches for efficiency
            from src.application.utilities.simple_batching import process_in_batches

            async def process_batch(batch: list[MatchResult]) -> dict[int, bool]:
                nonlocal success_count
                batch_results = {}

                for result in batch:
                    if not result.track.id or result.track.id not in tracks_by_id:
                        continue

                    track = tracks_by_id[result.track.id]

                    try:
                        # Map track to connector
                        await self.track_repos.connector.map_track_to_connector(
                            track=track,
                            connector=connector,
                            connector_id=result.connector_id,
                            match_method=result.match_method,
                            confidence=result.confidence,
                            metadata=result.service_data.copy(),
                            confidence_evidence=result.evidence.as_dict()
                            if result.evidence
                            else None,
                        )
                        success_count += 1
                        batch_results[track.id] = True
                    except Exception as e:
                        # For database errors, fail fast instead of continuing
                        if "database is locked" in str(e) or "OperationalError" in str(
                            type(e)
                        ):
                            logger.error(
                                f"Database error encountered, stopping sync: {e}"
                            )
                            raise
                        # For other errors, log and continue
                        logger.error(f"Error mapping track {track.id}: {e}")

                return batch_results

            # Process all batches
            batch_items = list(matches.values())
            await process_in_batches(
                batch_items,
                process_batch,
                batch_size=batch_size,
                operation_name="persist_batch",
                connector=connector,
            )

            logger.info(f"Successfully persisted {success_count} matches")
