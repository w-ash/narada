"""Spotify-specific implementation of PlaylistSyncService.

This module provides the concrete implementation for synchronizing playlists
with Spotify while maintaining Clean Architecture separation of concerns.
"""

from typing import Any

from attrs import define

from src.application.use_cases.update_playlist import (
    PlaylistOperation,
    PlaylistOperationType,
    PlaylistSyncService,
    UpdatePlaylistOptions,
)
from src.config import get_logger
from src.domain.entities.playlist import Playlist

logger = get_logger(__name__)


@define(slots=True)
class SpotifyPlaylistSyncService(PlaylistSyncService):
    """Concrete implementation of PlaylistSyncService for Spotify.

    Handles synchronization of playlist operations with Spotify API
    while maintaining platform-agnostic interface for the use case layer.
    """

    spotify_connector: Any  # SpotifyConnector from infrastructure layer

    async def sync_playlist(
        self,
        playlist: Playlist,
        operations: list[PlaylistOperation],
        options: UpdatePlaylistOptions,
    ) -> tuple[dict[str, Any], int]:
        """Synchronize playlist operations with Spotify API.

        Args:
            playlist: Internal playlist being updated
            operations: List of operations to apply
            options: Update configuration

        Returns:
            Tuple of (updated_metadata, api_calls_made)
        """
        _ = options  # Options available for future Spotify-specific configuration
        if not operations:
            return {}, 0

        # Get Spotify playlist ID
        spotify_playlist_id = playlist.connector_playlist_ids.get("spotify")
        if not spotify_playlist_id:
            logger.warning("No Spotify playlist ID found, skipping sync")
            return {}, 0

        # Get current snapshot ID for conflict detection
        current_snapshot = playlist.metadata.get("spotify_snapshot_id")

        logger.info(
            f"Syncing playlist {spotify_playlist_id} with {len(operations)} operations",
            snapshot_id=current_snapshot,
        )

        try:
            # Execute operations via Spotify connector
            new_snapshot = await self.spotify_connector.execute_playlist_operations(
                spotify_playlist_id,
                operations,
                current_snapshot,
            )

            # Calculate actual API calls made
            api_calls_made = self._count_spotify_api_calls(operations)

            # Return updated metadata
            metadata_updates = {}
            if new_snapshot:
                metadata_updates["spotify_snapshot_id"] = new_snapshot

            logger.info(
                "Spotify sync completed successfully",
                new_snapshot_id=new_snapshot,
                api_calls=api_calls_made,
            )

            return metadata_updates, api_calls_made

        except Exception as e:
            logger.error(f"Spotify sync failed: {e}")
            raise

    def supports_playlist(self, playlist: Playlist) -> bool:
        """Check if this service can sync the given playlist."""
        return "spotify" in playlist.connector_playlist_ids

    def _count_spotify_api_calls(self, operations: list[PlaylistOperation]) -> int:
        """Count actual Spotify API calls based on operations executed.

        This accounts for Spotify-specific batching and operation grouping.
        """
        remove_ops = sum(
            1 for op in operations if op.operation_type == PlaylistOperationType.REMOVE
        )
        add_ops = sum(
            1 for op in operations if op.operation_type == PlaylistOperationType.ADD
        )
        move_ops = sum(
            1 for op in operations if op.operation_type == PlaylistOperationType.MOVE
        )

        api_calls = 0

        # Removes can be batched efficiently in Spotify API
        if remove_ops > 0:
            api_calls += max(1, (remove_ops + 99) // 100)  # Batch in groups of 100

        # Adds need individual API calls for position accuracy in Spotify
        if add_ops > 0:
            api_calls += max(
                1, (add_ops + 99) // 100
            )  # Actually, adds can be batched too

        # Moves are individual operations in Spotify
        api_calls += move_ops

        return api_calls
