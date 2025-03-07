"""
Source node implementations for workflow pipelines.

Source nodes are the entry points for our workflow system, responsible for
fetching data from external systems and preparing it for processing. Unlike
transform nodes, source nodes don't have upstream dependencies and are
responsible for data preparation and persistence.
"""

from narada.config import get_logger
from narada.core.models import Playlist, TrackList
from narada.core.repositories import PlaylistRepository, TrackRepository
from narada.database.database import get_session
from narada.integrations.spotify import SpotifyConnector

logger = get_logger(__name__)


async def spotify_playlist_source(_context: dict, config: dict) -> dict:
    """Spotify playlist source node with immediate track persistence.

    This node fetches a playlist from Spotify and ensures all tracks have
    database IDs before being processed by downstream nodes. This pattern
    guarantees stable identifiers for cross-node operations like filtering
    and deduplication.

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

    # Track persistence metrics
    stats = {"new_tracks": 0, "updated_tracks": 0}

    # Persist tracks to guarantee database IDs
    async with get_session(rollback=False) as session:
        track_repo = TrackRepository(session)
        db_tracks = []

        # Process each track to ensure database presence
        for track in spotify_playlist.tracks:
            updated_track = await track_repo.save_track(track)
            db_tracks.append(updated_track)

            # Update persistence metrics
            if updated_track.id is not None and track.id is None:
                stats["new_tracks"] += 1
            else:
                stats["updated_tracks"] += 1

        # Create internal playlist reference
        playlist_repo = PlaylistRepository(session)
        internal_playlist = Playlist(
            name=spotify_playlist.name,
            tracks=db_tracks,
            description=f"Source: Spotify playlist {playlist_id}",
            connector_track_ids={"spotify": playlist_id},
        )

        # Create playlist association in database
        db_playlist_id = await playlist_repo.save_playlist(internal_playlist)

    # Build tracklist with rich metadata
    tracklist = TrackList(tracks=db_tracks)
    tracklist = tracklist.with_metadata("source_playlist_name", spotify_playlist.name)
    tracklist = tracklist.with_metadata("spotify_playlist_id", playlist_id)
    tracklist = tracklist.with_metadata("db_playlist_id", db_playlist_id)

    # Return comprehensive result
    return {
        "tracklist": tracklist,
        "source_id": playlist_id,
        "source_name": spotify_playlist.name,
        "track_count": len(tracklist.tracks),
        "db_playlist_id": db_playlist_id,
        **stats,
    }
