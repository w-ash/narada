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

from src.application.use_cases.save_playlist import (
    EnrichmentConfig,
    PersistenceOptions,
    SavePlaylistCommand,
    SavePlaylistUseCase,
)
from src.application.use_cases.update_playlist import (
    UpdatePlaylistCommand,
    UpdatePlaylistOptions,
    UpdatePlaylistUseCase,
)
from src.domain.entities.track import TrackList
from src.infrastructure.config import get_logger
from src.infrastructure.connectors.spotify import SpotifyConnector

logger = get_logger(__name__)


# NOTE: persist_tracks function removed - now handled by SavePlaylistUseCase


async def handle_internal_destination(
    tracklist: TrackList,
    config: dict,
    _context: dict,  # Kept for consistent interface
) -> dict:
    """Create a playlist in the internal database using SavePlaylistUseCase."""
    # Create command for internal playlist creation
    command = SavePlaylistCommand(
        tracklist=tracklist,
        enrichment_config=EnrichmentConfig(enabled=config.get("enrich_tracks", True)),
        persistence_options=PersistenceOptions(
            operation_type="create_internal",
            playlist_name=config.get("name", "Narada Playlist"),
            playlist_description=config.get("description", "Created by Narada"),
        ),
    )

    # Execute using SavePlaylistUseCase
    use_case = SavePlaylistUseCase()
    result = await use_case.execute(command)

    # Return result in expected format for backward compatibility
    return {
        "operation": "create_internal_playlist",
        "operation_type": "create_internal_playlist",
        "playlist": result.playlist,
        "playlist_name": result.playlist.name,
        "playlist_id": result.playlist.id,
        "tracklist": tracklist,
        "persisted_tracks": result.enriched_tracks,
        "track_count": result.track_count,
        "execution_time_ms": result.execution_time_ms,
    }


async def handle_spotify_destination(
    tracklist: TrackList,
    config: dict,
    _context: dict,  # Kept for consistent interface
) -> dict:
    """Create a new Spotify playlist using SavePlaylistUseCase."""
    # Infrastructure: create playlist in Spotify via external API
    spotify = SpotifyConnector()
    spotify_id = await spotify.create_playlist(
        config.get("name", "Narada Playlist"),
        tracklist.tracks,
        config.get("description", "Created by Narada"),
    )

    # Create command for Spotify playlist creation
    command = SavePlaylistCommand(
        tracklist=tracklist,
        enrichment_config=EnrichmentConfig(
            enabled=config.get("enrich_tracks", True),
            primary_provider="spotify",
        ),
        persistence_options=PersistenceOptions(
            operation_type="create_spotify",
            playlist_name=config.get("name", "Narada Playlist"),
            playlist_description=config.get("description", "Created by Narada"),
            spotify_playlist_id=spotify_id,
        ),
    )

    # Execute using SavePlaylistUseCase
    use_case = SavePlaylistUseCase()
    result = await use_case.execute(command)

    # Return result in expected format for backward compatibility
    return {
        "operation": "create_spotify_playlist",
        "playlist": result.playlist,
        "playlist_name": result.playlist.name,
        "playlist_id": result.playlist.id,
        "tracklist": tracklist,
        "persisted_tracks": result.enriched_tracks,
        "track_count": result.track_count,
        "spotify_id": spotify_id,
        "execution_time_ms": result.execution_time_ms,
    }


async def handle_update_spotify_destination(
    tracklist: TrackList,
    config: dict,
    _context: dict,  # Kept for consistent interface
) -> dict:
    """Update an existing Spotify playlist using SavePlaylistUseCase."""
    spotify_id = config.get("playlist_id")
    append = config.get("append", False)

    if not spotify_id:
        raise ValueError("Missing required playlist_id for update operation")

    # Create command for Spotify playlist update
    command = SavePlaylistCommand(
        tracklist=tracklist,
        enrichment_config=EnrichmentConfig(
            enabled=config.get("enrich_tracks", True),
            primary_provider="spotify",
        ),
        persistence_options=PersistenceOptions(
            operation_type="update_spotify",
            playlist_name="",  # Will be determined from existing playlist
            spotify_playlist_id=spotify_id,
            append_mode=append,
        ),
    )

    # Execute using SavePlaylistUseCase
    use_case = SavePlaylistUseCase()
    result = await use_case.execute(command)

    # Infrastructure: update Spotify via external API
    spotify = SpotifyConnector()
    await spotify.update_playlist(spotify_id, result.playlist, replace=not append)

    # Return result in expected format for backward compatibility
    return {
        "playlist": result.playlist,
        "tracklist": tracklist,
        "persisted_tracks": result.enriched_tracks,
        "track_count": result.track_count,
        "spotify_id": spotify_id,
        "append_mode": append,
        "execution_time_ms": result.execution_time_ms,
    }


async def handle_update_playlist_destination(
    tracklist: TrackList,
    config: dict,
    _context: dict,  # Kept for consistent interface
) -> dict:
    """Update an existing playlist using UpdatePlaylistUseCase.
    
    This destination node enables differential playlist updates that preserve
    track addition timestamps and minimize API operations through sophisticated
    add/remove/reorder algorithms.
    
    Config parameters:
        playlist_id (str): ID of playlist to update (internal or connector ID)
        operation_type (str): "update_internal", "update_spotify", or "sync_bidirectional"
        conflict_resolution (str): "local_wins", "remote_wins", "user_prompt", "merge_intelligent"
        dry_run (bool): Preview changes without executing (default: False)
        preserve_order (bool): Maintain existing track order where possible (default: True)
        enable_spotify_sync (bool): Sync changes to Spotify if playlist is linked (default: True)
    """
    playlist_id = config.get("playlist_id")
    if not playlist_id:
        raise ValueError("Missing required playlist_id for update operation")
    
    operation_type = config.get("operation_type", "update_internal")
    if operation_type not in ["update_internal", "update_spotify", "sync_bidirectional"]:
        raise ValueError(f"Invalid operation_type: {operation_type}")
    
    # Create command for playlist update
    command = UpdatePlaylistCommand(
        playlist_id=playlist_id,
        new_tracklist=tracklist,
        options=UpdatePlaylistOptions(
            operation_type=operation_type,
            conflict_resolution=config.get("conflict_resolution", "local_wins"),
            track_matching_strategy=config.get("track_matching_strategy", "comprehensive"),
            dry_run=config.get("dry_run", False),
            force_update=config.get("force_update", False),
            preserve_order=config.get("preserve_order", True),
            batch_size=min(config.get("batch_size", 100), 100),  # Enforce Spotify limit
            max_api_calls=config.get("max_api_calls", 50),
            enable_spotify_sync=config.get("enable_spotify_sync", True),
        ),
        metadata={
            "workflow_source": "destination_node",
            "original_config": config,
        }
    )
    
    # Execute using UpdatePlaylistUseCase
    use_case = UpdatePlaylistUseCase()
    result = await use_case.execute(command)
    
    # Return result in expected format for backward compatibility
    return {
        "operation": "update_playlist",
        "operation_type": operation_type,
        "playlist": result.playlist,
        "playlist_name": result.playlist.name,
        "playlist_id": result.playlist.id,
        "tracklist": tracklist,
        "updated_tracks": result.playlist.tracks,
        "track_count": len(result.playlist.tracks),
        "operations_performed": len(result.operations_performed),
        "tracks_added": result.tracks_added,
        "tracks_removed": result.tracks_removed,
        "tracks_moved": result.tracks_moved,
        "api_calls_made": result.api_calls_made,
        "execution_time_ms": result.execution_time_ms,
        "dry_run": command.options.dry_run,
        "conflicts_detected": result.conflicts_detected,
        "conflicts_resolved": result.conflicts_resolved,
    }


# Export destination handler map for factory use
DESTINATION_HANDLERS = {
    "internal": handle_internal_destination,
    "spotify": handle_spotify_destination,
    "update_spotify": handle_update_spotify_destination,
    "update_playlist": handle_update_playlist_destination,
}
