"""Reusable operations for track like synchronization.

This module provides composable utilities and patterns for working with
track likes across different services, following DRY principles.
"""

from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any, Literal

from attrs import define, field

from src.domain.entities import OperationResult, SyncCheckpoint, Track, TrackList
from src.infrastructure.config import get_logger
from src.infrastructure.persistence.repositories.track import TrackRepositories
from src.infrastructure.services.matcher import match_tracks

logger = get_logger(__name__)

# Type for any track ID
TrackID = int


# SyncStats class removed - now using unified OperationResult directly
# All functionality is now available in the base OperationResult class

def add_track_result(
    result: OperationResult,
    track: Track,
    status: str,
    reason: str | None = None,
    confidence: float | None = None,
    error_message: str | None = None,
) -> None:
    """Add a detailed result for a single track to an OperationResult."""
    if not track.id:
        return

    # Update the tracks list if this track isn't already included
    if not any(t.id == track.id for t in result.tracks):
        new_tracks = list(result.tracks)
        new_tracks.append(track)
        object.__setattr__(result, "tracks", new_tracks)

    # Store detailed metrics for this track
    track_metrics = {
        "sync_status": {track.id: status},
        "sync_reason": {track.id: reason} if reason else {},
        "match_confidence": {track.id: confidence} if confidence else {},
        "error_message": {track.id: error_message} if error_message else {},
    }

    # Update metrics dictionary
    new_metrics = result.metrics.copy()
    for metric_name, metric_values in track_metrics.items():
        if metric_values:
            if metric_name in new_metrics:
                new_metrics[metric_name].update(metric_values)
            else:
                new_metrics[metric_name] = metric_values
    object.__setattr__(result, "metrics", new_metrics)
    
    # Update unified count fields based on status
    if status == "imported":
        object.__setattr__(result, "imported_count", result.imported_count + 1)
    elif status == "exported":
        object.__setattr__(result, "exported_count", result.exported_count + 1)
    elif status == "skipped":
        object.__setattr__(result, "skipped_count", result.skipped_count + 1)
    elif status == "error":
        object.__setattr__(result, "error_count", result.error_count + 1)


def get_track_status(result: OperationResult, track_id: int) -> str | None:
    """Get the sync status for a specific track."""
    return result.get_metric(track_id, "sync_status")


def get_tracks_by_status(result: OperationResult, status: str) -> list[Track]:
    """Get all tracks with a specific sync status."""
    status_metrics = result.metrics.get("sync_status", {})
    matching_track_ids = {
        track_id
        for track_id, track_status in status_metrics.items()
        if track_status == status
    }
    return [track for track in result.tracks if track.id in matching_track_ids]


@define
class LikeOperation:
    """Reusable component for like synchronization between services."""

    track_repos: TrackRepositories
    source_service: str
    target_service: str = field(default="narada")  # Narada is default target
    batch_size: int = 50

    async def save_like_to_services(
        self,
        track_id: TrackID,
        timestamp: datetime | None = None,
        is_liked: bool = True,
        services: list[str] | None = None,
    ) -> None:
        """Save like status to multiple services at once."""
        services = services or [self.target_service]
        now = timestamp or datetime.now(UTC)

        for service in services:
            await self.track_repos.likes.save_track_like(
                track_id=track_id,
                service=service,
                is_liked=is_liked,
                last_synced=now if service != self.source_service else None,
            )

    async def get_unsynced_likes(
        self, is_liked: bool = True, since_timestamp: datetime | None = None
    ) -> list[Any]:
        """Get tracks that need like status syncing from source to target.

        Args:
            is_liked: Whether to get liked (True) or unliked (False) tracks
            since_timestamp: If provided, only include likes updated since this time

        Returns:
            List of track likes that need synchronization
        """
        return await self.track_repos.likes.get_unsynced_likes(
            source_service=self.source_service,
            target_service=self.target_service,
            is_liked=is_liked,
            since_timestamp=since_timestamp,
        )

    async def process_batch_with_matcher(
        self,
        tracks: list[Track],
        connector: Any,
        batch_processor: Callable[[Track, Any], Coroutine[Any, Any, bool]],
        stats: OperationResult,
    ) -> OperationResult:
        """Process a batch of tracks with the matcher system.

        Args:
            tracks: List of tracks to process
            connector: Service connector to use
            batch_processor: Async function to process each track after matching
            stats: Stats object to update

        Returns:
            Updated stats object
        """
        if not tracks:
            return stats

        # Create a TrackList for the matcher
        track_list = TrackList(tracks=tracks)

        # Use the matcher to get accurate service matches
        logger.info(f"Matching {len(tracks)} tracks to {self.target_service}")

        # Match tracks to the target service using injected repository
        match_results = await match_tracks(
            track_list, self.target_service, connector, self.track_repos
        )

        # Process each matched track and save likes in a separate session
        batch_timestamp = datetime.now(UTC)

        # Collect successful operations for batch like saving
        successful_track_ids = []

        for track in tracks:
            if not track or not track.id:
                continue

            match_result = match_results.get(track.id)

            if match_result and match_result.success:
                # Check if track is already loved on the target service
                service_data = match_result.service_data
                if service_data.get('lastfm_user_loved', False):
                    # Track already loved, skip API call but mark as successful
                    successful_track_ids.append(track.id)
                    add_track_result(stats, track, "skipped", reason="already_loved", confidence=match_result.confidence)
                    logger.info(
                        f"Track already loved on {self.target_service}: {track.artists[0].name if track.artists else 'Unknown'} "
                        f"- {track.title} (confidence: {match_result.confidence}%)"
                    )
                else:
                    # Track not loved yet, process it
                    try:
                        success = await batch_processor(track, match_result)

                        if success:
                            successful_track_ids.append(track.id)
                            add_track_result(stats, track, "exported", confidence=match_result.confidence)
                            logger.info(
                                f"Processed track: {track.artists[0].name if track.artists else 'Unknown'} "
                                f"- {track.title} (confidence: {match_result.confidence}%)"
                            )
                        else:
                            add_track_result(stats, track, "error", error_message="Failed to process track")
                            logger.warning(
                                f"Failed to process track: "
                                f"{track.artists[0].name if track.artists else 'Unknown'} - {track.title}"
                            )
                    except Exception as e:
                        add_track_result(stats, track, "error", error_message=str(e))
                        logger.exception(f"Error processing track {track.id}: {e}")
            else:
                # No match found or low confidence
                add_track_result(stats, track, "skipped", reason="no_match")
                logger.warning(
                    f"No service match found for track: "
                    f"{track.artists[0].name if track.artists else 'Unknown'} - {track.title}"
                )

        # Save all likes using the existing session (SQLAlchemy 2.0 best practice)
        if successful_track_ids:
            for track_id in successful_track_ids:
                try:
                    await self.track_repos.likes.save_track_like(
                        track_id=track_id,
                        service=self.target_service,
                        is_liked=True,
                        last_synced=batch_timestamp,
                    )
                except Exception as e:
                    logger.exception(f"Error saving like for track {track_id}: {e}")

        return stats


@define
class CheckpointManager:
    """Manages sync checkpoints for resumable operations."""

    track_repos: TrackRepositories
    user_id: str
    service: str
    entity_type: Literal["likes", "plays"]

    async def get_or_create_checkpoint(self) -> SyncCheckpoint:
        """Get existing checkpoint or create a new one."""
        checkpoint = await self.track_repos.checkpoints.get_sync_checkpoint(
            user_id=self.user_id,
            service=self.service,
            entity_type=self.entity_type,
        )

        if not checkpoint:
            # Create a new checkpoint if one doesn't exist
            checkpoint = SyncCheckpoint(
                user_id=self.user_id,
                service=self.service,
                entity_type=self.entity_type,
            )

        return checkpoint

    async def update_checkpoint(
        self,
        timestamp: datetime | None = None,
        cursor: str | None = None,
    ) -> SyncCheckpoint:
        """Update the checkpoint with new timestamp and cursor."""
        checkpoint = await self.get_or_create_checkpoint()

        # Update the checkpoint
        updated = checkpoint.with_update(
            timestamp=timestamp or datetime.now(UTC),
            cursor=cursor,
        )

        # Save to database
        return await self.track_repos.checkpoints.save_sync_checkpoint(updated)
