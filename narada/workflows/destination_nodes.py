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

from narada.config import get_logger
from narada.core.models import Playlist, Track, TrackList
from narada.database.db_connection import get_session
from narada.integrations.spotify import SpotifyConnector
from narada.repositories.playlist import PlaylistRepository
from narada.repositories.track import UnifiedTrackRepository

logger = get_logger(__name__)


async def persist_tracks(tracklist: TrackList) -> tuple[list[Track], dict]:
    """Persist tracks to database with metrics tracking.

    Common utility used by all destination strategies to ensure
    consistent track persistence behavior.

    Args:
        tracklist: TrackList containing tracks to persist

    Returns:
        Tuple of (persisted_tracks, stats_dictionary)
    """
    stats = {"new_tracks": 0, "updated_tracks": 0}

    async with get_session() as session:
        track_repo = UnifiedTrackRepository(session)
        db_tracks = []

        for track in tracklist.tracks:
            try:
                original_id = track.id
                saved_track = await track_repo.save_track(track)

                if original_id != saved_track.id:
                    if original_id is None:
                        stats["new_tracks"] += 1
                    else:
                        stats["updated_tracks"] += 1

                db_tracks.append(saved_track)
            except Exception as e:
                logger.error(f"Error persisting track {track.title}: {e}")
                db_tracks.append(track)

        await session.commit()
        return db_tracks, stats


async def handle_internal_destination(
    tracklist: TrackList,
    config: dict,
    _context: dict,  # Kept for consistent interface
) -> dict:
    """Create a playlist in the internal database."""
    name = config.get("name", "Narada Playlist")
    description = config.get("description", "Created by Narada")

    # Persist tracks
    db_tracks, stats = await persist_tracks(tracklist)

    # Create playlist
    async with get_session() as session:
        playlist_repo = PlaylistRepository(session)
        track_repo = UnifiedTrackRepository(session)

        playlist = Playlist(
            name=name,
            description=description,
            tracks=db_tracks,
        )

        saved_playlist = await playlist_repo.save_playlist(playlist, track_repo)
        await session.commit()

    # Preserve original metadata in result
    result_tracklist = TrackList(tracks=db_tracks, metadata=tracklist.metadata)

    return {
        "playlist_id": saved_playlist.id,
        "playlist_name": name,
        "track_count": len(db_tracks),
        "operation": "create_internal_playlist",
        "tracklist": result_tracklist,
        **stats,
    }


async def handle_spotify_destination(
    tracklist: TrackList,
    config: dict,
    _context: dict,  # Kept for consistent interface
) -> dict:
    """Create a new Spotify playlist."""
    name = config.get("name", "Narada Playlist")
    description = config.get("description", "Created by Narada")

    # Create Spotify playlist
    spotify = SpotifyConnector()
    spotify_id = await spotify.create_playlist(name, tracklist.tracks, description)

    # Persist tracks and create internal representation
    db_tracks, stats = await persist_tracks(tracklist)

    async with get_session() as session:
        playlist_repo = PlaylistRepository(session)
        track_repo = UnifiedTrackRepository(session)

        # Create playlist with Spotify ID
        playlist = Playlist(
            name=name,
            description=description,
            tracks=db_tracks,
            connector_playlist_ids={"spotify": spotify_id},
        )

        saved_playlist = await playlist_repo.save_playlist(playlist, track_repo)
        await session.commit()

    # Preserve original metadata in result
    result_tracklist = TrackList(tracks=db_tracks, metadata=tracklist.metadata)

    return {
        "playlist_id": saved_playlist.id,
        "spotify_playlist_id": spotify_id,
        "playlist_name": name,
        "track_count": len(db_tracks),
        "operation": "create_spotify_playlist",
        "tracklist": result_tracklist,
        **stats,
    }


async def handle_update_spotify_destination(
    tracklist: TrackList,
    config: dict,
    _context: dict,  # Kept for consistent interface
) -> dict:
    """Update an existing Spotify playlist."""
    spotify_id = config.get("playlist_id")
    append = config.get("append", False)

    if not spotify_id:
        raise ValueError("Missing required playlist_id for update operation")

    # Persist tracks
    db_tracks, stats = await persist_tracks(tracklist)

    # Update playlist in database and Spotify
    async with get_session() as session:
        track_repo = UnifiedTrackRepository(session)
        playlist_repo = PlaylistRepository(session)

        # Get existing playlist by connector ID
        existing = await playlist_repo.get_playlist_by_connector(
            "spotify", 
            spotify_id,
            raise_if_not_found=False,
        )
        
        if not existing:
            raise ValueError(f"Playlist with Spotify ID {spotify_id} not found in database")
            
        # Update tracks based on append mode
        updated_tracks = existing.tracks + db_tracks if append else db_tracks
        updated = existing.with_tracks(updated_tracks)

        # Update Spotify first
        spotify = SpotifyConnector()
        await spotify.update_playlist(spotify_id, updated, replace=not append)

        # Then update database
        if existing.id is None:
            raise ValueError("Existing playlist has no ID")
            
        updated_playlist = await playlist_repo.update_playlist(
            existing.id,
            updated,
            track_repo,
        )
        await session.commit()

    # Preserve original metadata in result
    result_tracklist = TrackList(tracks=db_tracks, metadata=tracklist.metadata)

    return {
        "playlist_id": updated_playlist.id,
        "spotify_playlist_id": spotify_id,
        "track_count": len(updated.tracks),
        "original_count": len(existing.tracks),
        "operation": "update_spotify_playlist",
        "append_mode": append,
        "tracklist": result_tracklist,
        **stats,
    }


# Export destination handler map for factory use
DESTINATION_HANDLERS = {
    "internal": handle_internal_destination,
    "spotify": handle_spotify_destination,
    "update_spotify": handle_update_spotify_destination,
}
