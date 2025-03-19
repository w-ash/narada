"""Source nodes for Narada workflows."""

from typing import Any

from narada.config import get_logger
from narada.core.models import TrackList
from narada.database.db_connection import get_session
from narada.integrations.spotify import SpotifyConnector
from narada.repositories.playlist import PlaylistRepository
from narada.repositories.track import UnifiedTrackRepository

logger = get_logger(__name__)


async def spotify_playlist_source(_context: dict, config: dict) -> dict[str, Any]:
    """Fetch Spotify playlist and convert to TrackList.

    Loads playlist from Spotify, stores to database, and returns as TrackList.
    Empty playlists are handled gracefully with a warning.

    Args:
        context: Workflow context (unused by source nodes)
        config: Node configuration with required keys:
            - playlist_id: Spotify playlist ID to fetch

    Returns:
        Dictionary containing:
            - tracklist: TrackList for downstream nodes
            - playlist_id: Internal database ID of saved playlist
            - playlist_name: Name of the playlist
    """
    playlist_id = config.get("playlist_id")
    if not playlist_id:
        raise ValueError("Missing required config parameter: playlist_id")

    logger.info(f"Fetching Spotify playlist: {playlist_id}")

    # Initialize Spotify connector
    spotify = SpotifyConnector()

    # Fetch playlist from Spotify with full track details
    playlist = await spotify.get_spotify_playlist(playlist_id)

    if not playlist:
        raise ValueError(f"Failed to retrieve Spotify playlist {playlist_id}")

    if not playlist.tracks:
        logger.warning(f"Playlist '{playlist.name}' ({playlist_id}) has no tracks")
        # Return empty tracklist instead of raising an error
        empty_tracklist = TrackList()

        return {
            "tracklist": empty_tracklist,
            "playlist_id": None,
            "playlist_name": playlist.name,
            "source": "spotify",
            "source_id": playlist_id,
            "operation": "spotify_playlist_source",
            "track_count": 0,
        }

    logger.info(
        f"Retrieved {len(playlist.tracks)} tracks from playlist '{playlist.name}'",
    )

    # Save playlist and tracks to database
    async with get_session() as session:
        # Create repository instances
        track_repo = UnifiedTrackRepository(session)
        playlist_repo = PlaylistRepository(session)

        # First, try to get by connector ID
        existing_playlist = await playlist_repo.get_playlist_by_connector(
            "spotify",
            playlist_id,
            raise_if_not_found=False,  # Don't raise an exception if not found
        )

        if existing_playlist:
            logger.info(
                f"Found existing playlist in database with ID {existing_playlist.id}",
            )

            # Update with fresh data from Spotify
            if existing_playlist.id is not None:
                updated_playlist = await playlist_repo.update_playlist(
                    existing_playlist.id,
                    playlist,
                    track_repo,
                )
            else:
                # Handle case where ID is None
                logger.warning("Existing playlist has no ID, creating new instead")
                updated_playlist = await playlist_repo.save_playlist(
                    playlist,
                    track_repo,
                )

            logger.info(
                f"Updated playlist {updated_playlist.id} with {len(updated_playlist.tracks)} tracks",
            )
            saved_playlist = updated_playlist
        else:
            # Not found, create new playlist
            logger.info("Creating new playlist in database")
            saved_playlist = await playlist_repo.save_playlist(playlist, track_repo)
            logger.info(f"Created playlist with ID {saved_playlist.id}")

        # Create tracklist for downstream nodes
        tracklist = TrackList.from_playlist(saved_playlist)
        
        # Verify all tracks have IDs - this should now be guaranteed by our repository pattern
        missing_ids = [i for i, t in enumerate(tracklist.tracks) if t.id is None]
        if missing_ids:
            logger.error(f"Found {len(missing_ids)} tracks without IDs after playlist persistence")
            for i in missing_ids[:5]:  # Log details for up to 5 missing IDs
                track = tracklist.tracks[i]
                logger.error(f"Track missing ID: {track.title} by {[a.name for a in track.artists]}")
            raise ValueError(
                f"Critical error: {len(missing_ids)}/{len(tracklist.tracks)} tracks missing IDs. "
                "Check repository implementation and eager loading configuration.",
            )

        return {
            "tracklist": tracklist,
            "playlist_id": saved_playlist.id,
            "playlist_name": saved_playlist.name,
            "source": "spotify",
            "source_id": playlist_id,
            "operation": "spotify_playlist_source",
            "track_count": len(tracklist.tracks),
        }
