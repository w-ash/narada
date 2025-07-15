"""Service layer for track like synchronization.

This module provides high-level operations for synchronizing track likes
between different services, using repositories for persistence.
"""

from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities import OperationResult, Track
from src.infrastructure.config import get_config, get_logger
from src.infrastructure.connectors.lastfm import LastFMConnector
from src.infrastructure.connectors.spotify import SpotifyConnector
from src.infrastructure.persistence.database.db_connection import get_session
from src.infrastructure.persistence.repositories.track import TrackRepositories
from src.infrastructure.services.like_operations import (
    CheckpointManager,
    LikeOperation,
    add_track_result,
)
from src.domain.entities.operations import OperationResult

logger = get_logger(__name__)


async def import_spotify_likes(
    session: AsyncSession,
    user_id: str,
    limit: int | None = None,
    max_imports: int | None = None,
) -> OperationResult:
    """Import liked tracks from Spotify to the local database.

    Args:
        session: Database session
        user_id: User identifier for checkpoint tracking
        limit: Batch size for API requests (None for config default)
        max_imports: Maximum number of tracks to import (None for unlimited)

    Returns:
        OperationResult containing operation metrics
    """
    # Get optimal batch size from config
    api_batch_size = limit or get_config("SPOTIFY_API_BATCH_SIZE", 50)
    # Initialize repositories and connector
    track_repos = TrackRepositories(session)
    spotify = SpotifyConnector()

    # Create checkpoint manager
    checkpoint_mgr = CheckpointManager(
        track_repos=track_repos,
        user_id=user_id,
        service="spotify",
        entity_type="likes",
    )

    # Initialize checkpoint manager for future incremental sync improvements
    await checkpoint_mgr.get_or_create_checkpoint()

    # Create like operation
    like_op = LikeOperation(
        track_repos=track_repos,
        source_service="spotify",
        target_service="narada",
    )

    # Track stats for reporting
    stats = OperationResult()

    # For Spotify likes, start from the beginning (offset 0) to catch recent tracks
    # since Spotify returns saved tracks in reverse chronological order (newest first)
    cursor = None
    batches_processed = 0
    tracks_found_in_db = 0

    # Process in batches with pagination
    while True:
        # Exit if we've reached the maximum import count
        if max_imports is not None and stats.imported >= max_imports:
            logger.info(f"Reached maximum import count: {max_imports}")
            break

        # Fetch connector tracks from Spotify using optimal batch size
        connector_tracks, next_cursor = await spotify.get_liked_tracks(
            limit=api_batch_size,
            cursor=cursor,
        )

        if not connector_tracks:
            logger.info("No more tracks to import from Spotify")
            break

        # Process tracks in this batch
        batch_timestamp = datetime.now(UTC)
        successful_tracks = []
        new_tracks_in_batch = 0

        for connector_track in connector_tracks:
            try:
                # Check if this track already exists and is liked
                existing_track = await track_repos.connector.find_track_by_connector(
                    connector="spotify",
                    connector_id=connector_track.connector_track_id,
                )

                if existing_track and existing_track.id is not None:
                    # Check if it's already liked in both Spotify and Narada
                    spotify_likes = await track_repos.likes.get_track_likes(
                        track_id=existing_track.id,
                        services=["spotify"],
                    )
                    narada_likes = await track_repos.likes.get_track_likes(
                        track_id=existing_track.id,
                        services=["narada"],
                    )

                    spotify_liked = any(like.is_liked for like in spotify_likes)
                    narada_liked = any(like.is_liked for like in narada_likes)

                    if spotify_liked and narada_liked:
                        # Track already exists and is liked in both services
                        tracks_found_in_db += 1
                        logger.debug(f"Track already synced: {connector_track.title}")
                        continue
                    else:
                        # Track exists but not properly liked, process it
                        successful_tracks.append(existing_track.id)
                        stats.add_track_result(existing_track, "imported")
                        continue

                # Track doesn't exist, ingest it
                db_track = await track_repos.connector.ingest_external_track(
                    connector="spotify",
                    connector_id=connector_track.connector_track_id,
                    metadata=connector_track.raw_metadata,
                    title=connector_track.title,
                    artists=[a.name for a in connector_track.artists],
                    album=connector_track.album,
                    duration_ms=connector_track.duration_ms,
                    release_date=connector_track.release_date,
                    isrc=connector_track.isrc,
                )

                if db_track and db_track.id is not None:
                    successful_tracks.append(db_track.id)
                    new_tracks_in_batch += 1
                    stats.add_track_result(db_track, "imported")
                else:
                    logger.warning(f"Could not ingest track: {connector_track.title}")

            except Exception as e:
                logger.exception(f"Error importing track {connector_track.title}: {e}")

        # Save likes for all successful tracks
        for track_id in successful_tracks:
            try:
                await like_op.save_like_to_services(
                    track_id=track_id,
                    timestamp=batch_timestamp,
                    services=["spotify", "narada"],
                )
            except Exception as e:
                logger.exception(f"Error saving likes for track {track_id}: {e}")

        batches_processed += 1

        # If we haven't found any new tracks in this batch and most tracks already exist,
        # we've likely caught up to our previous sync point
        if (
            new_tracks_in_batch == 0
            and tracks_found_in_db > len(connector_tracks) * 0.8
        ):
            logger.info(
                f"Reached previously synced tracks (found {tracks_found_in_db} existing tracks in recent batches), stopping incremental sync"
            )
            break

        # Update checkpoint every 10 batches for better performance
        if batches_processed % 10 == 0 or not next_cursor:
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
        f"{tracks_found_in_db} already synced"
    )
    return stats


async def export_likes_to_lastfm(
    session: AsyncSession,
    user_id: str,
    batch_size: int | None = None,
    max_exports: int | None = None,
) -> OperationResult:
    """Export liked tracks from Narada to Last.fm.

    Args:
        session: Database session
        user_id: User identifier for checkpoint tracking
        batch_size: Number of tracks to process in each batch (None for config default)
        max_exports: Maximum number of tracks to export (None for unlimited)

    Returns:
        OperationResult containing operation metrics
    """
    # Use Last.fm specific batch size from config (more conservative due to rate limits)
    api_batch_size = batch_size or get_config("LASTFM_API_BATCH_SIZE", 20)
    # Initialize repositories and connector
    track_repos = TrackRepositories(session)
    lastfm = LastFMConnector()

    # Create like operation helper
    like_op = LikeOperation(
        track_repos=track_repos,
        source_service="narada",
        target_service="lastfm",
        batch_size=api_batch_size,
    )

    # Create checkpoint manager for incremental export
    checkpoint_mgr = CheckpointManager(
        track_repos=track_repos,
        user_id=user_id,
        service="lastfm",
        entity_type="likes",
    )

    # Track stats for reporting
    stats = OperationResult()

    # Get existing checkpoint to determine last sync timestamp
    checkpoint = await checkpoint_mgr.get_or_create_checkpoint()
    last_sync_time = checkpoint.last_timestamp

    # First, get total liked tracks in Narada for intelligence reporting
    all_narada_likes = await like_op.track_repos.likes.get_all_liked_tracks(
        service="narada", is_liked=True
    )
    total_liked_in_narada = len(all_narada_likes)

    # Start likes export process - get only tracks that need processing
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

    # Calculate intelligence metrics
    candidates = len(liked_tracks)
    already_liked = total_liked_in_narada - candidates

    # Update stats with intelligence using object setattr for frozen stats
    object.__setattr__(stats, "candidates", candidates)
    object.__setattr__(stats, "already_liked", already_liked)

    logger.info(
        f"Export analysis: {total_liked_in_narada} total liked tracks, "
        f"{already_liked} already loved on Last.fm ({already_liked / total_liked_in_narada * 100:.1f}%), "
        f"{candidates} candidates for export"
    )

    # Process tracks in batches
    for i in range(0, len(liked_tracks), api_batch_size):
        # Exit if we've reached the maximum export count
        if max_exports is not None and stats.exported >= max_exports:
            logger.info(f"Reached maximum export count: {max_exports}")
            break

        batch = liked_tracks[i : i + api_batch_size]
        batch_timestamp = datetime.now(UTC)

        # Build a list of Track objects for batch matching
        tracks_to_match = []

        for track_like in batch:
            # Skip if we've hit the maximum
            if max_exports is not None and stats.exported >= max_exports:
                break

            try:
                # Get full track details using the core repository
                track = await track_repos.core.get_by_id(track_like.track_id)
                if not track or not track.artists:
                    logger.warning(
                        f"Track not found or incomplete: {track_like.track_id}"
                    )
                    continue

                # Store for batch processing
                tracks_to_match.append(track)

            except Exception as e:
                logger.exception(f"Error preparing track {track_like.track_id}: {e}")

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
        f"{stats.skipped} skipped out of {candidates} candidates"
    )
    return stats


# Higher-level functions that handle database sessions


async def run_with_session(
    service_func: Callable[..., Coroutine],
    **kwargs,
) -> OperationResult:
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
    repositories: TrackRepositories,
    user_id: str = "default",
    limit: int | None = None,
    max_imports: int | None = None,
) -> OperationResult:
    """Import liked tracks from Spotify with provided repositories."""
    # Use the session from the repositories instead of creating a new one
    stats = await import_spotify_likes(
        session=repositories.session,
        user_id=user_id,
        limit=limit,
        max_imports=max_imports,
    )
    # OperationResult is returned directly with unified fields
    return stats


async def run_lastfm_likes_export(
    repositories: TrackRepositories,
    user_id: str = "default",
    batch_size: int | None = None,
    max_exports: int | None = None,
) -> OperationResult:
    """Export liked tracks to Last.fm with provided repositories."""
    # Use the session from the repositories instead of creating a new one
    stats = await export_likes_to_lastfm(
        session=repositories.session,
        user_id=user_id,
        batch_size=batch_size,
        max_exports=max_exports,
    )
    # OperationResult is returned directly with unified fields
    return stats
