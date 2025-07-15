"""
Destination node implementations for workflow pipelines.

Destination nodes are the terminal points of our workflow system, responsible for
persisting processed data to various targets including internal databases and
external streaming services. These nodes implement consistent error handling,
transaction management, and result reporting patterns across different destination
types.

Key responsibilities:
- Track persistence with consistent database transaction management
- Playlist creation and updating in both internal and external systems
- Result metadata collection for workflow monitoring
- Standardized error handling for destination operations
"""

from src.domain.entities.track import Track, TrackList
from src.domain.workflows.playlist_operations import (
    calculate_track_persistence_stats,
    create_playlist_operation,
    create_spotify_playlist_operation,
    format_destination_result,
    format_spotify_destination_result,
    format_update_destination_result,
    update_playlist_tracks_operation,
)
from src.infrastructure.config import get_logger
from src.infrastructure.connectors.spotify import SpotifyConnector
from src.infrastructure.persistence.database.db_connection import get_session
from src.infrastructure.persistence.repositories.playlist.core import PlaylistRepository
from src.infrastructure.persistence.repositories.track import TrackRepositories

logger = get_logger(__name__)


async def persist_tracks(tracklist: TrackList) -> tuple[list[Track], dict]:
    """Persist tracks to database with metrics tracking.

    Infrastructure adapter that handles track persistence and delegates
    statistics calculation to pure domain logic.

    Args:
        tracklist: TrackList containing tracks to persist

    Returns:
        Tuple of (persisted_tracks, stats_dictionary)
    """
    # Infrastructure: persist tracks to database
    async with get_session() as session:
        track_repos = TrackRepositories(session)
        db_tracks = []

        for track in tracklist.tracks:
            try:
                saved_track = await track_repos.core.save_track(track)
                db_tracks.append(saved_track)
            except Exception as e:
                logger.error(f"Error persisting track {track.title}: {e}")
                db_tracks.append(track)

    # Domain: calculate statistics using pure business logic
    stats = calculate_track_persistence_stats(tracklist.tracks, db_tracks)

    return db_tracks, stats


async def handle_internal_destination(
    tracklist: TrackList,
    config: dict,
    _context: dict,  # Kept for consistent interface
) -> dict:
    """Create a playlist in the internal database.

    Infrastructure adapter that handles IO and delegates business logic
    to pure domain functions.
    """
    # Infrastructure: persist tracks to database
    db_tracks, stats = await persist_tracks(tracklist)

    # Domain: create playlist entity using pure business logic
    playlist = create_playlist_operation(tracklist, config, db_tracks)

    # Infrastructure: save playlist to database
    async with get_session() as session:
        playlist_repo = PlaylistRepository(session)
        saved_playlist = await playlist_repo.save_playlist(playlist)

    # Domain: format result using pure business logic
    return format_destination_result(
        operation_type="create_internal_playlist",
        playlist=saved_playlist,
        tracklist=tracklist,
        persisted_tracks=db_tracks,
        stats=stats,
    )


async def handle_spotify_destination(
    tracklist: TrackList,
    config: dict,
    _context: dict,  # Kept for consistent interface
) -> dict:
    """Create a new Spotify playlist.

    Infrastructure adapter that handles external API calls and database operations,
    delegating business logic to pure domain functions.
    """
    # Infrastructure: create playlist in Spotify via external API
    spotify = SpotifyConnector()
    spotify_id = await spotify.create_playlist(
        config.get("name", "Narada Playlist"),
        tracklist.tracks,
        config.get("description", "Created by Narada"),
    )

    # Infrastructure: persist tracks to database
    db_tracks, stats = await persist_tracks(tracklist)

    # Domain: create playlist entity using pure business logic
    playlist = create_spotify_playlist_operation(
        tracklist, config, db_tracks, spotify_id
    )

    # Infrastructure: save playlist to database
    async with get_session() as session:
        playlist_repo = PlaylistRepository(session)
        saved_playlist = await playlist_repo.save_playlist(playlist)

    # Domain: format result using pure business logic
    return format_spotify_destination_result(
        playlist=saved_playlist,
        tracklist=tracklist,
        persisted_tracks=db_tracks,
        stats=stats,
        spotify_id=spotify_id,
    )


async def handle_update_spotify_destination(
    tracklist: TrackList,
    config: dict,
    _context: dict,  # Kept for consistent interface
) -> dict:
    """Update an existing Spotify playlist.

    Infrastructure adapter that handles external API calls and database operations,
    delegating business logic to pure domain functions.
    """
    spotify_id = config.get("playlist_id")
    append = config.get("append", False)

    if not spotify_id:
        raise ValueError("Missing required playlist_id for update operation")

    # Infrastructure: persist tracks to database
    db_tracks, stats = await persist_tracks(tracklist)

    # Infrastructure: get existing playlist from database
    async with get_session() as session:
        playlist_repo = PlaylistRepository(session)
        existing = await playlist_repo.get_playlist_by_connector(
            "spotify", spotify_id, raise_if_not_found=False
        )

        if not existing:
            raise ValueError(
                f"Playlist with Spotify ID {spotify_id} not found in database"
            )

        # Domain: calculate updated playlist using pure business logic
        updated = update_playlist_tracks_operation(existing, db_tracks, append)

        # Infrastructure: update Spotify via external API
        spotify = SpotifyConnector()
        await spotify.update_playlist(spotify_id, updated, replace=not append)

        # Infrastructure: update database
        async with session.begin_nested():
            if existing.id is None:
                raise ValueError("Existing playlist has no ID")
            updated_playlist = await playlist_repo.update_playlist(existing.id, updated)

    # Domain: format result using pure business logic
    return format_update_destination_result(
        playlist=updated_playlist,
        tracklist=tracklist,
        persisted_tracks=db_tracks,
        stats=stats,
        spotify_id=spotify_id,
        append_mode=append,
        original_track_count=len(existing.tracks),
    )


# Export destination handler map for factory use
DESTINATION_HANDLERS = {
    "internal": handle_internal_destination,
    "spotify": handle_spotify_destination,
    "update_spotify": handle_update_spotify_destination,
}
