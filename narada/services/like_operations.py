"""Reusable operations for track like synchronization.

This module provides composable utilities and patterns for working with
track likes across different services, following DRY principles.
"""

from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any, Literal

from attrs import define, field

from narada.config import get_logger
from narada.core.matcher import match_tracks
from narada.core.models import SyncCheckpoint, Track, TrackList
from narada.repositories.track import UnifiedTrackRepository

logger = get_logger(__name__)

# Type for any track ID
TrackID = int


@define
class SyncStats:
    """Statistics from a synchronization operation."""

    imported: int = 0
    exported: int = 0
    skipped: int = 0
    errors: int = 0
    total: int = 0


@define
class LikeOperation:
    """Reusable component for like synchronization between services."""

    track_repo: UnifiedTrackRepository
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
            await self.track_repo.save_track_like(
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
        return await self.track_repo.get_unsynced_likes(
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
        stats: SyncStats,
    ) -> SyncStats:
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

        # Match tracks to the target service
        match_results = await match_tracks(track_list, self.target_service, connector)

        # Process each matched track
        batch_timestamp = datetime.now(UTC)

        for track in tracks:
            if not track or not track.id:
                continue

            match_result = match_results.get(track.id)

            if match_result and match_result.success:
                # We have a good match, process it
                try:
                    success = await batch_processor(track, match_result)

                    if success:
                        # Mark the track as liked in the target service
                        await self.save_like_to_services(
                            track_id=track.id,
                            timestamp=batch_timestamp,
                            services=[self.target_service],
                        )
                        stats.exported += 1
                        logger.info(
                            f"Processed track: {track.artists[0].name if track.artists else 'Unknown'} "
                            f"- {track.title} (confidence: {match_result.confidence}%)"
                        )
                    else:
                        stats.errors += 1
                        logger.warning(
                            f"Failed to process track: "
                            f"{track.artists[0].name if track.artists else 'Unknown'} - {track.title}"
                        )
                except Exception as e:
                    stats.errors += 1
                    logger.exception(f"Error processing track {track.id}: {e}")
            else:
                # No match found or low confidence
                stats.skipped += 1
                logger.warning(
                    f"No service match found for track: "
                    f"{track.artists[0].name if track.artists else 'Unknown'} - {track.title}"
                )

        return stats


@define
class CheckpointManager:
    """Manages sync checkpoints for resumable operations."""

    track_repo: UnifiedTrackRepository
    user_id: str
    service: str
    entity_type: Literal["likes", "plays"]

    async def get_or_create_checkpoint(self) -> SyncCheckpoint:
        """Get existing checkpoint or create a new one."""
        checkpoint = await self.track_repo.get_sync_checkpoint(
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
        return await self.track_repo.save_sync_checkpoint(updated)
