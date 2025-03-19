"""Service layer for track like synchronization.

This module provides high-level operations for synchronizing track likes
between different services, using repositories for persistence.
"""

from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from narada.config import get_logger
from narada.core.models import Track
from narada.database.db_connection import get_session
from narada.integrations.lastfm import LastFMConnector
from narada.integrations.spotify import SpotifyConnector
from narada.repositories.track import UnifiedTrackRepository
from narada.services.like_operations import (
    CheckpointManager,
    LikeOperation,
    SyncStats,
)

logger = get_logger(__name__)


async def import_spotify_likes(
    session: AsyncSession,
    user_id: str,
    limit: int = 50,
    max_imports: int | None = None,
) -> SyncStats:
    """Import liked tracks from Spotify to the local database.

    Args:
        session: Database session
        user_id: User identifier for checkpoint tracking
        limit: Batch size for API requests
        max_imports: Maximum number of tracks to import (None for unlimited)

    Returns:
        SyncStats containing operation metrics
    """
    # Initialize repositories and connector
    track_repo = UnifiedTrackRepository(session)
    spotify = SpotifyConnector()

    # Create checkpoint manager
    checkpoint_mgr = CheckpointManager(
        track_repo=track_repo,
        user_id=user_id,
        service="spotify",
        entity_type="likes",
    )

    # Get existing checkpoint
    checkpoint = await checkpoint_mgr.get_or_create_checkpoint()

    # Create like operation
    like_op = LikeOperation(
        track_repo=track_repo,
        source_service="spotify",
        target_service="narada",
    )

    # Track stats for reporting
    stats = SyncStats()
    cursor = checkpoint.cursor

    # Process in batches with pagination
    while True:
        # Exit if we've reached the maximum import count
        if max_imports is not None and stats.imported >= max_imports:
            logger.info(f"Reached maximum import count: {max_imports}")
            break

        # Fetch tracks from Spotify
        tracks, next_cursor = await spotify.get_liked_tracks(
            limit=limit,
            cursor=cursor,
        )

        if not tracks:
            logger.info("No more tracks to import from Spotify")
            break

        # Process each track
        batch_timestamp = datetime.now(UTC)
        for track in tracks:
            stats.total += 1

            try:
                # Save or update track in database
                db_track = await track_repo.find_track(
                    track_title=track.title,
                    artist_name=track.artists[0].name if track.artists else None,
                    connector_id=track.connector_track_ids.get("spotify"),
                    connector_name="spotify",
                )

                # If track doesn't exist, create it
                if not db_track:
                    db_track = await track_repo.save_track(track)
                    logger.debug(f"Created new track: {track.title}")

                # Ensure track_id is not None
                if db_track and db_track.id is not None:
                    # Save likes to both services in one operation
                    await like_op.save_like_to_services(
                        track_id=db_track.id,
                        timestamp=batch_timestamp,
                        services=["spotify", "narada"],
                    )
                else:
                    logger.warning(f"Could not save likes for track: {track.title} - No valid track ID")

                stats.imported += 1

            except Exception as e:
                logger.exception(f"Error importing track {track.title}: {e}")
                stats.errors += 1

        # Update checkpoint for resumability
        await checkpoint_mgr.update_checkpoint(
            timestamp=batch_timestamp,
            cursor=next_cursor,
        )

        # Break if no more pagination
        if not next_cursor:
            logger.info("Completed import of all Spotify likes")
            break

        # Update for next iteration
        cursor = next_cursor

    logger.info(
        f"Spotify likes import completed: {stats.imported} imported, "
        f"{stats.errors} errors out of {stats.total} total"
    )
    return stats


async def export_likes_to_lastfm(
    session: AsyncSession,
    user_id: str,
    batch_size: int = 20,
    max_exports: int | None = None,
) -> SyncStats:
    """Export liked tracks from Narada to Last.fm.

    Args:
        session: Database session
        user_id: User identifier for checkpoint tracking
        batch_size: Number of tracks to process in each batch
        max_exports: Maximum number of tracks to export (None for unlimited)

    Returns:
        SyncStats containing operation metrics
    """
    # Initialize repositories and connector
    track_repo = UnifiedTrackRepository(session)
    lastfm = LastFMConnector()

    # Create like operation helper
    like_op = LikeOperation(
        track_repo=track_repo,
        source_service="narada",
        target_service="lastfm",
        batch_size=batch_size,
    )

    # Create checkpoint manager for incremental export
    checkpoint_mgr = CheckpointManager(
        track_repo=track_repo,
        user_id=user_id,
        service="lastfm",
        entity_type="likes",
    )

    # Track stats for reporting
    stats = SyncStats()

    # Get existing checkpoint to determine last sync timestamp
    checkpoint = await checkpoint_mgr.get_or_create_checkpoint()
    last_sync_time = checkpoint.last_timestamp

    # Start likes export process

    # For incremental sync, only get likes updated since last sync
    if last_sync_time:
        logger.info(f"Performing incremental export since {last_sync_time}")
        # Use timestamp-based filtering for incremental sync
        liked_tracks = await like_op.get_unsynced_likes(
            is_liked=True, since_timestamp=last_sync_time
        )
    else:
        # Get all tracks that are liked in Narada but not marked as liked in Last.fm
        liked_tracks = await like_op.get_unsynced_likes(is_liked=True)

    logger.info(f"Found {len(liked_tracks)} tracks to export to Last.fm")
    stats.total = len(liked_tracks)

    # Process tracks in batches
    for i in range(0, len(liked_tracks), batch_size):
        # Exit if we've reached the maximum export count
        if max_exports is not None and stats.exported >= max_exports:
            logger.info(f"Reached maximum export count: {max_exports}")
            break

        batch = liked_tracks[i : i + batch_size]
        batch_timestamp = datetime.now(UTC)

        # Build a list of Track objects for batch matching
        tracks_to_match = []

        for track_like in batch:
            # Skip if we've hit the maximum
            if max_exports is not None and stats.exported >= max_exports:
                break

            try:
                # Get full track details
                track = await track_repo.get_track(id=track_like.track_id)
                if not track or not track.artists:
                    logger.warning(
                        f"Track not found or incomplete: {track_like.track_id}"
                    )
                    stats.skipped += 1
                    continue

                # Store for batch processing
                tracks_to_match.append(track)

            except Exception as e:
                logger.exception(f"Error preparing track {track_like.track_id}: {e}")
                stats.errors += 1

        if not tracks_to_match:
            continue

        # Define the track processing function
        async def process_track(track: Track, _match_result: Any) -> bool:
            """Process a single track after matching."""
            if not track.artists:
                return False

            artist_name = track.artists[0].name
            track_title = track.title

            # Love the track on Last.fm
            return await lastfm.love_track(
                artist_name=artist_name,
                track_title=track_title,
            )

        # Process the batch using our reusable component
        stats = await like_op.process_batch_with_matcher(
            tracks=tracks_to_match,
            connector=lastfm,
            batch_processor=process_track,
            stats=stats,
        )

        # Update checkpoint for future incremental implementation
        await checkpoint_mgr.update_checkpoint(timestamp=batch_timestamp)

    logger.info(
        f"Last.fm loves export completed: {stats.exported} exported, "
        f"{stats.skipped} skipped, {stats.errors} errors out of {stats.total} total"
    )
    return stats


# Higher-level functions that handle database sessions


async def run_with_session(
    service_func: Callable[..., Coroutine],
    **kwargs,
) -> SyncStats:
    """Run a service function with automatic session handling.

    Args:
        service_func: The async service function to run
        **kwargs: Arguments to pass to the service function

    Returns:
        The result from the service function
    """
    async with get_session() as session:
        return await service_func(session=session, **kwargs)


async def run_spotify_likes_import(
    user_id: str = "default",
    limit: int = 50,
    max_imports: int | None = None,
) -> SyncStats:
    """Import liked tracks from Spotify with session handling."""
    return await run_with_session(
        import_spotify_likes,
        user_id=user_id,
        limit=limit,
        max_imports=max_imports,
    )


async def run_lastfm_likes_export(
    user_id: str = "default",
    batch_size: int = 20,
    max_exports: int | None = None,
) -> SyncStats:
    """Export liked tracks to Last.fm with session handling."""
    return await run_with_session(
        export_likes_to_lastfm,
        user_id=user_id,
        batch_size=batch_size,
        max_exports=max_exports,
    )
