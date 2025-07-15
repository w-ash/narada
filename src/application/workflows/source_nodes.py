"""Source nodes for Narada workflows.

All nodes follow the batch-first design principle, processing data in bulk
and leveraging optimized bulk operations for maximum efficiency.
"""

from typing import Any

from src.domain.entities.track import TrackList
from src.infrastructure.config import get_logger
from src.infrastructure.connectors.spotify import (
    SpotifyConnector,
    convert_spotify_track_to_connector,
)
from src.infrastructure.persistence.database.db_connection import get_session
from src.infrastructure.persistence.repositories.playlist import PlaylistRepositories
from src.infrastructure.persistence.repositories.track import TrackRepositories

logger = get_logger(__name__)


async def spotify_playlist_source(
    _context: dict, 
    config: dict, 
    spotify_connector: SpotifyConnector | None = None
) -> dict[str, Any]:
    """Fetch Spotify playlist and convert to TrackList using bulk operations."""
    playlist_id = config.get("playlist_id")
    if not playlist_id:
        raise ValueError("Missing required config parameter: playlist_id")

    logger.info(f"Fetching Spotify playlist: {playlist_id}")
    if spotify_connector is None:
        spotify_connector = SpotifyConnector()

    # 1. Fetch playlist with its items in a single API call
    connector_playlist = await spotify_connector.get_spotify_playlist(playlist_id)

    if not connector_playlist or not connector_playlist.items:
        logger.warning(f"Playlist empty or not found: {playlist_id}")
        return {
            "tracklist": TrackList(),
            "playlist_id": None,
            "playlist_name": connector_playlist.name
            if connector_playlist
            else "Unknown",
            "source": "spotify",
            "source_id": playlist_id,
            "operation": "spotify_playlist_source",
            "track_count": 0,
        }

    # 2. Extract all track IDs for bulk fetch
    track_ids = connector_playlist.track_ids
    logger.info(f"Fetching {len(track_ids)} tracks in bulk from Spotify")

    # 3. Bulk fetch all track data (this uses the tracks endpoint)
    track_data_map = await spotify_connector.get_tracks_by_ids(track_ids)

    # 4. Convert all tracks to connector models
    connector_tracks = [
        convert_spotify_track_to_connector(track_data)
        for track_data in track_data_map.values()
    ]

    logger.info(f"Retrieved {len(connector_tracks)}/{len(track_ids)} tracks in bulk")

    # 5. Process in database with a single session transaction
    # (SQLAlchemy automatically begins a transaction when the session is used)
    async with get_session() as session:
        track_repos = TrackRepositories(session)
        playlist_repos = PlaylistRepositories(session)

        # 6. Bulk ingest all tracks at once
        domain_tracks = await track_repos.connector.ingest_external_tracks_bulk(
            connector="spotify", tracks=connector_tracks
        )

        # 7. Ingest playlist with all its tracks using the complete connector playlist
        _, domain_playlist = await playlist_repos.connector.ingest_connector_playlist(
            connector_playlist=connector_playlist,
            create_internal_playlist=True,
            tracks=domain_tracks,
        )

        # 8. Create tracklist from domain playlist
        if domain_playlist is None:
            tracklist = TrackList()
            playlist_id = None
            playlist_name = "Unknown"
        else:
            tracklist = TrackList.from_playlist(domain_playlist)
            playlist_id = domain_playlist.id
            playlist_name = domain_playlist.name

        return {
            "tracklist": tracklist,
            "playlist_id": playlist_id,
            "playlist_name": playlist_name,
            "source": "spotify",
            "source_id": playlist_id,
            "operation": "spotify_playlist_source",
            "track_count": len(tracklist.tracks),
        }
