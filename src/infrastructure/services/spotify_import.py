"""Refactored Spotify import service using BaseImportService template method pattern."""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from src.application.utilities.results import ImportResultData, ResultFactory
from src.config import get_logger
from src.domain.entities import OperationResult, TrackPlay
from src.infrastructure.connectors.spotify import SpotifyConnector
from src.infrastructure.connectors.spotify_personal_data import (
    SpotifyPlayRecord,
    parse_spotify_personal_data,
)
from src.infrastructure.persistence.repositories.track import TrackRepositories
from src.infrastructure.services.base_import import BaseImportService
from src.infrastructure.services.spotify_play_resolver import SpotifyPlayResolver

logger = get_logger(__name__)


class SpotifyImportService(BaseImportService):
    """Service for importing Spotify personal data exports using template method pattern."""

    def __init__(self, repositories: TrackRepositories) -> None:
        """Initialize with repository access."""
        super().__init__(repositories)
        self.operation_name = "Spotify Import"
        self.spotify_connector = SpotifyConnector()
        self.resolver = SpotifyPlayResolver(
            spotify_connector=self.spotify_connector, track_repos=repositories
        )

    # Public interface method - delegate to template method

    async def import_from_file(
        self,
        file_path: Path,
        import_batch_id: str | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> OperationResult:
        """Import Spotify play data from a JSON export file.

        Args:
            file_path: Path to the Spotify export JSON file
            import_batch_id: Optional batch ID for tracking related imports
            progress_callback: Optional callback for progress updates (current, total, message)

        Returns:
            OperationResult with play processing statistics and affected tracks
        """
        return await self.import_data(
            file_path=file_path,
            import_batch_id=import_batch_id,
            progress_callback=progress_callback,
        )

    # Template method implementations

    async def _fetch_data(
        self,
        progress_callback: Callable[[int, int, str], None] | None = None,
        file_path: Path | None = None,
        **additional_options,
    ) -> list[SpotifyPlayRecord]:
        """Fetch raw play data from Spotify JSON export file."""
        _ = additional_options  # Reserved for future extensibility
        if file_path is None:
            raise ValueError("file_path is required for Spotify import")

        if progress_callback:
            progress_callback(20, 100, "Parsing Spotify export file...")

        try:
            play_records = parse_spotify_personal_data(file_path)
            logger.info(
                "Parsed Spotify export",
                file_path=str(file_path),
                count=len(play_records),
            )
            return play_records
        except Exception as e:
            logger.error(
                "Failed to parse Spotify export file",
                file_path=str(file_path),
                error=str(e),
            )
            # Re-raise so template method can handle error consistently
            raise

    async def _process_data(
        self,
        raw_data: list[SpotifyPlayRecord],
        batch_id: str,
        import_timestamp: datetime,
        progress_callback: Callable[[int, int, str], None] | None = None,
        **additional_options,
    ) -> list[TrackPlay]:
        """Process Spotify play records into TrackPlay objects with track resolution."""
        _ = additional_options  # Reserved for future extensibility
        if progress_callback:
            progress_callback(60, 100, f"Resolving {len(raw_data)} track URIs...")

        # Use enhanced resolver for comprehensive track resolution
        resolution_results = await self.resolver.resolve_with_fallback(raw_data)

        if progress_callback:
            progress_callback(75, 100, "Creating play records with resolution...")

        track_plays = []
        resolution_stats = {
            "direct_id": 0,
            "relinked_id": 0,
            "search_match": 0,
            "preserved_metadata": 0,
            "total_with_track_id": 0,
        }

        for record in raw_data:
            resolution = resolution_results.get(record.track_uri)

            if resolution:
                track_id = resolution.track_id
                resolution_method = resolution.resolution_method
                confidence = resolution.confidence

                # Update statistics
                resolution_stats[resolution_method] += 1
                if track_id is not None:
                    resolution_stats["total_with_track_id"] += 1

                # Create enhanced context with resolution info
                context = {
                    # Behavioral data
                    "platform": record.platform,
                    "country": record.country,
                    "reason_start": record.reason_start,
                    "reason_end": record.reason_end,
                    "shuffle": record.shuffle,
                    "skipped": record.skipped,
                    "offline": record.offline,
                    "incognito_mode": record.incognito_mode,
                    # Original track metadata
                    "spotify_track_uri": record.track_uri,
                    "track_name": record.track_name,
                    "artist_name": record.artist_name,
                    "album_name": record.album_name,
                    # Resolution tracking
                    "resolution_method": resolution_method,
                    "resolution_confidence": confidence,
                }

                # Add resolution-specific metadata
                if resolution.metadata:
                    context["resolution_metadata"] = resolution.metadata

                track_play = TrackPlay(
                    track_id=track_id,
                    service="spotify",
                    played_at=record.timestamp,
                    ms_played=record.ms_played,
                    context=context,
                    import_timestamp=import_timestamp,
                    import_source="spotify_export",
                    import_batch_id=batch_id,
                )

                track_plays.append(track_play)

                if track_id is None:
                    logger.debug(
                        "Created play record without track ID",
                        uri=record.track_uri,
                        track=record.track_name,
                        method=resolution_method,
                    )
            else:
                # This should never happen with comprehensive resolver, but handle gracefully
                logger.warning(f"No resolution result for {record.track_uri}")
                resolution_stats["preserved_metadata"] += 1

        # Store resolution stats for result creation
        self._resolution_stats = resolution_stats
        self._resolution_results = resolution_results

        return track_plays

    async def _handle_checkpoints(
        self, raw_data: list[SpotifyPlayRecord], **additional_options
    ) -> None:
        """Handle checkpoint updates for Spotify imports.

        For file imports, checkpoints are not relevant since we process complete files.
        This is a no-op implementation.
        """
        _ = raw_data  # Reserved for future checkpoint tracking
        _ = additional_options  # Reserved for future extensibility
        # No checkpoints needed for file-based imports

    def _create_success_result(
        self,
        raw_data: list[Any],
        track_plays: list[TrackPlay],
        imported_count: int,
        batch_id: str,
    ) -> OperationResult:
        """Override to include Spotify-specific metrics using ResultFactory."""
        _ = track_plays  # Used in resolution results processing below
        # Collect affected tracks from resolution results
        affected_tracks = []
        if hasattr(self, "_resolution_results"):
            # Get unique tracks that were affected by this import
            unique_track_ids = {
                resolution.track_id
                for resolution in self._resolution_results.values()
                if resolution.track_id is not None
            }

            # Create minimal Track objects with just IDs for affected tracks
            from src.domain.entities import Artist, Track

            affected_tracks = [
                Track(
                    title="Imported Track",
                    artists=[Artist(name="Unknown")],
                    id=track_id,
                )
                for track_id in unique_track_ids
            ]

        import_data = ImportResultData(
            raw_data_count=len(raw_data),
            imported_count=imported_count,
            batch_id=batch_id,
            tracks=affected_tracks,  # Use affected tracks instead of track_plays
        )

        result = ResultFactory.create_import_result(
            operation_name=self.operation_name,
            import_data=import_data,
        )

        # Add Spotify-specific resolution metrics
        if hasattr(self, "_resolution_stats"):
            resolution_stats = self._resolution_stats
            result.play_metrics.update({
                "resolution_stats": resolution_stats,
                "resolution_rate_percent": round(
                    (resolution_stats["total_with_track_id"] / len(raw_data)) * 100, 1
                )
                if len(raw_data) > 0
                else 0,
            })

        return result
