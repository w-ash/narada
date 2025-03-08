"""
Source node implementations for workflow pipelines.

Source nodes are the entry points for our workflow system, responsible for
fetching data from external systems and preparing it for processing. Unlike
transform nodes, source nodes don't have upstream dependencies and are
responsible for data preparation and persistence.
"""

from narada.config import get_logger
from narada.core.models import Playlist, TrackList
from narada.core.repositories import PlaylistRepository
from narada.database.database import get_session
from narada.integrations.spotify import SpotifyConnector

logger = get_logger(__name__)


async def spotify_playlist_source(_context: dict, config: dict) -> dict:
    """Spotify playlist source node.

    Fetches a playlist from Spotify and creates a tracklist for downstream nodes.
    The save_playlist method automatically ensures all tracks have database IDs,
    simplifying the source node implementation.

    Args:
        context: Workflow context (unused in source nodes)
        config: Node configuration with playlist_id

    Returns:
        Node result with tracklist and metadata

    Raises:
        ValueError: If playlist_id is missing
    """
    if "playlist_id" not in config:
        raise ValueError("Missing required config parameter: playlist_id")

    playlist_id = config["playlist_id"]
    logger.info(f"Fetching Spotify playlist: {playlist_id}")

    # Fetch playlist from Spotify API
    spotify = SpotifyConnector()
    spotify_playlist = await spotify.get_spotify_playlist(playlist_id)

    # Create internal playlist (tracks will be saved automatically by save_playlist)
    async with get_session(rollback=False) as session:
        playlist_repo = PlaylistRepository(session)

        internal_playlist = Playlist(
            name=spotify_playlist.name,
            tracks=spotify_playlist.tracks,  # Original tracks without database IDs
            description=f"Source: Spotify playlist {playlist_id}",
            connector_track_ids={"spotify": playlist_id},
        )

        # Create playlist association in database (automatically saves tracks)
        db_playlist_id = await playlist_repo.save_playlist(internal_playlist)

    # Build tracklist with enriched tracks that now have IDs
    # We need to reload the playlist to get the tracks with IDs
    async with get_session() as session:
        playlist_repo = PlaylistRepository(session)
        saved_playlist = await playlist_repo.get_playlist("internal", db_playlist_id)

        if not saved_playlist:
            raise ValueError(
                f"Failed to retrieve saved playlist with ID {db_playlist_id}",
            )

        tracklist = TrackList(tracks=saved_playlist.tracks)

    # Add metadata
    tracklist = tracklist.with_metadata("source_playlist_name", spotify_playlist.name)
    tracklist = tracklist.with_metadata("spotify_playlist_id", playlist_id)
    tracklist = tracklist.with_metadata("db_playlist_id", db_playlist_id)

    return {
        "tracklist": tracklist,
        "source_id": playlist_id,
        "source_name": spotify_playlist.name,
        "track_count": len(tracklist.tracks),
        "db_playlist_id": db_playlist_id,
    }
