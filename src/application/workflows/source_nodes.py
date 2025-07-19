"""Source nodes for Narada workflows.

All nodes follow the batch-first design principle, processing data in bulk
and leveraging optimized bulk operations for maximum efficiency.
"""

from typing import Any

from src.application.use_cases.save_playlist import (
    EnrichmentConfig,
    PersistenceOptions,
    SavePlaylistCommand,
    SavePlaylistUseCase,
)
from src.config import get_logger
from src.domain.entities.track import Track, TrackList
from src.infrastructure.connectors.spotify import (
    SpotifyConnector,
    convert_spotify_track_to_connector,
)

logger = get_logger(__name__)


async def spotify_playlist_source(
    _context: dict, config: dict, spotify_connector: SpotifyConnector | None = None
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

    # 4. Convert all tracks to domain models
    domain_tracks = [
        _convert_connector_track_to_domain(
            convert_spotify_track_to_connector(track_data)
        )
        for track_data in track_data_map.values()
    ]

    logger.info(f"Retrieved {len(domain_tracks)}/{len(track_ids)} tracks in bulk")

    # 5. Create tracklist for use case
    tracklist = TrackList(tracks=domain_tracks)

    # 6. Save playlist using SavePlaylistUseCase (with track upsert)
    save_command = SavePlaylistCommand(
        tracklist=tracklist,
        enrichment_config=EnrichmentConfig(
            enabled=True,
            primary_provider="spotify",
            enrich_missing_only=True,
        ),
        persistence_options=PersistenceOptions(
            operation_type="create_internal",
            playlist_name=connector_playlist.name,
            playlist_description=connector_playlist.description
            or "Imported from Spotify",
            create_internal_playlist=True,
        ),
    )

    use_case = SavePlaylistUseCase()
    result = await use_case.execute(save_command)

    return {
        "tracklist": TrackList(tracks=result.enriched_tracks),
        "playlist_id": result.playlist.id,
        "playlist_name": result.playlist.name,
        "source": "spotify",
        "source_id": playlist_id,
        "operation": "spotify_playlist_source",
        "track_count": len(result.enriched_tracks),
    }


def _convert_connector_track_to_domain(connector_track) -> Track:
    """Convert ConnectorTrack to domain Track entity.

    Args:
        connector_track: ConnectorTrack from Spotify API

    Returns:
        Domain Track entity
    """
    return Track(
        title=connector_track.title,
        artists=connector_track.artists,
        album=connector_track.album,
        duration_ms=connector_track.duration_ms,
        release_date=connector_track.release_date,
        isrc=connector_track.isrc,
        connector_track_ids={
            connector_track.connector_name: connector_track.connector_track_id
        },
        connector_metadata={
            connector_track.connector_name: {
                "popularity": getattr(connector_track, "popularity", None),
                "preview_url": getattr(connector_track, "preview_url", None),
            }
        },
    )
