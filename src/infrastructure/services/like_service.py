"""Consolidated like service that merges like_operations and like_sync functionality.

This service eliminates the functional overlap between like_operations.py and like_sync.py
by consolidating all like-related operations into a single, cohesive service.
"""

from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any, Literal

# attrs import removed - no longer needed with unified result classes
from src.application.utilities.progress_integration import with_db_progress
from src.application.utilities.results import ResultFactory
from src.domain.entities import OperationResult, SyncCheckpoint, Track
from src.infrastructure.config import get_config, get_logger
from src.infrastructure.connectors.lastfm import LastFMConnector
from src.infrastructure.connectors.spotify import SpotifyConnector
from src.infrastructure.persistence.repositories.track import TrackRepositories

logger = get_logger(__name__)


# LikeImportResult and LikeExportResult classes removed
# All functionality is now available in the unified OperationResult class


class LikeService:
    """Consolidated service for all like-related operations.
    
    Merges functionality from like_operations.py and like_sync.py to eliminate
    duplication and provide a single coherent interface for like management.
    """
    
    def __init__(self, repositories: TrackRepositories) -> None:
        """Initialize with repository access."""
        self.repositories = repositories
        self._spotify_connector = None
        self._lastfm_connector = None
    
    @property
    def spotify_connector(self) -> SpotifyConnector:
        """Lazy-loaded Spotify connector."""
        if self._spotify_connector is None:
            self._spotify_connector = SpotifyConnector()
        return self._spotify_connector
    
    @property
    def lastfm_connector(self) -> LastFMConnector:
        """Lazy-loaded Last.fm connector."""
        if self._lastfm_connector is None:
            self._lastfm_connector = LastFMConnector()
        return self._lastfm_connector
    
    async def import_spotify_likes(
        self,
        user_id: str,
        limit: int | None = None,
        max_imports: int | None = None,
    ) -> OperationResult:
        """Import liked tracks from Spotify to the local database.
        
        Consolidates session handling and progress management that was previously
        scattered across like_sync.py wrapper functions.
        
        Args:
            user_id: User identifier for checkpoint tracking
            limit: Batch size for API requests (None for config default)
            max_imports: Maximum number of tracks to import (None for unlimited)
            
        Returns:
            LikeImportResult with operation metrics
        """
        # Apply progress decorator for consistent UI
        @with_db_progress(
            description="Importing Spotify liked tracks...",
            success_text="Spotify likes imported successfully!",
            display_title="Spotify Likes Import Results",
            next_step_message="[yellow]Tip:[/yellow] Export to Last.fm with [cyan]narada likes export[/cyan]",
        )
        async def _import_operation(_repositories: TrackRepositories) -> OperationResult:
            return await self._import_spotify_likes_internal(user_id, limit, max_imports)
        
        return await _import_operation(self.repositories)
    
    async def export_likes_to_lastfm(
        self,
        user_id: str,
        batch_size: int | None = None,
        max_exports: int | None = None,
    ) -> OperationResult:
        """Export liked tracks from Narada to Last.fm.
        
        Consolidates batch processing and checkpoint management that was
        previously duplicated across like_sync.py and like_operations.py.
        
        Args:
            user_id: User identifier for checkpoint tracking
            batch_size: Number of tracks to process in each batch (None for config default)
            max_exports: Maximum number of tracks to export (None for unlimited)
            
        Returns:
            LikeExportResult with operation metrics
        """
        # Apply progress decorator for consistent UI
        @with_db_progress(
            description="Exporting likes to Last.fm...",
            success_text="Likes exported to Last.fm successfully!",
            display_title="Last.fm Likes Export Results",
            next_step_message="[yellow]Tip:[/yellow] Likes are now synced across services",
        )
        async def _export_operation(_repositories: TrackRepositories) -> OperationResult:
            return await self._export_likes_to_lastfm_internal(user_id, batch_size, max_exports)
        
        return await _export_operation(self.repositories)
    
    async def _import_spotify_likes_internal(
        self,
        user_id: str,
        limit: int | None = None,
        max_imports: int | None = None,
    ) -> OperationResult:
        """Internal implementation of Spotify likes import."""
        # Get optimal batch size from config
        api_batch_size = limit or get_config("SPOTIFY_API_BATCH_SIZE", 50)
        
        # Create checkpoint for tracking
        checkpoint = await self.get_or_create_checkpoint(user_id, "spotify", "likes")
        
        # Track stats for reporting
        imported_count = 0
        tracks_found_in_db = 0
        batches_processed = 0
        cursor = None
        
        # Process in batches with pagination
        while True:
            # Exit if we've reached the maximum import count
            if max_imports is not None and imported_count >= max_imports:
                logger.info(f"Reached maximum import count: {max_imports}")
                break
            
            # Fetch connector tracks from Spotify
            connector_tracks, next_cursor = await self.spotify_connector.get_liked_tracks(
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
                    existing_track = await self.repositories.connector.find_track_by_connector(
                        connector="spotify",
                        connector_id=connector_track.connector_track_id,
                    )
                    
                    if existing_track and existing_track.id is not None:
                        # Check if it's already liked in both services
                        if await self._is_track_already_liked(existing_track.id, ["spotify", "narada"]):
                            tracks_found_in_db += 1
                            logger.debug(f"Track already synced: {connector_track.title}")
                            continue
                        else:
                            # Track exists but not properly liked, process it
                            successful_tracks.append(existing_track.id)
                            continue
                    
                    # Track doesn't exist, ingest it
                    db_track = await self.repositories.connector.ingest_external_track(
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
                    else:
                        logger.warning(f"Could not ingest track: {connector_track.title}")
                
                except Exception as e:
                    logger.exception(f"Error importing track {connector_track.title}: {e}")
            
            # Save likes for all successful tracks
            for track_id in successful_tracks:
                try:
                    await self._save_like_to_services(
                        track_id=track_id,
                        timestamp=batch_timestamp,
                        services=["spotify", "narada"],
                    )
                    imported_count += 1
                except Exception as e:
                    logger.exception(f"Error saving likes for track {track_id}: {e}")
            
            batches_processed += 1
            
            # Early termination logic for incremental efficiency
            if (
                new_tracks_in_batch == 0
                and tracks_found_in_db > len(connector_tracks) * 0.8
            ):
                logger.info("Reached previously synced tracks, stopping incremental sync")
                break
            
            # Update checkpoint periodically
            if batches_processed % 10 == 0 or not next_cursor:
                await self.update_checkpoint(
                    checkpoint=checkpoint,
                    timestamp=batch_timestamp,
                    cursor=next_cursor,
                )
            
            # Break if no more pagination
            if not next_cursor:
                logger.info("Completed import of all Spotify likes")
                break
            
            cursor = next_cursor
        
        logger.info(
            f"Spotify likes import completed: {imported_count} imported, "
            f"{tracks_found_in_db} already synced"
        )
        
        return OperationResult(
            operation_name="Spotify Likes Import",
            imported_count=imported_count,
            already_liked=tracks_found_in_db,
            candidates=imported_count + tracks_found_in_db,
        )
    
    async def _export_likes_to_lastfm_internal(
        self,
        user_id: str,
        batch_size: int | None = None,
        max_exports: int | None = None,
    ) -> OperationResult:
        """Internal implementation of Last.fm likes export."""
        # Use Last.fm specific batch size from config
        api_batch_size = batch_size or get_config("LASTFM_API_BATCH_SIZE", 20)
        
        # Create checkpoint for tracking
        checkpoint = await self.get_or_create_checkpoint(user_id, "lastfm", "likes")
        last_sync_time = checkpoint.last_timestamp
        
        # Get likes that need exporting
        if last_sync_time:
            logger.info(f"Performing incremental export since {last_sync_time}")
            liked_tracks = await self._get_unsynced_likes(
                source_service="narada",
                target_service="lastfm",
                is_liked=True,
                since_timestamp=last_sync_time,
            )
        else:
            liked_tracks = await self._get_unsynced_likes(
                source_service="narada",
                target_service="lastfm",
                is_liked=True,
            )
        
        # Calculate metrics
        total_liked_in_narada = len(await self.repositories.likes.get_all_liked_tracks(
            service="narada", is_liked=True
        ))
        candidates = len(liked_tracks)
        already_loved = total_liked_in_narada - candidates
        
        logger.info(
            f"Export analysis: {total_liked_in_narada} total liked tracks, "
            f"{already_loved} already loved on Last.fm ({already_loved / total_liked_in_narada * 100:.1f}%), "
            f"{candidates} candidates for export"
        )
        
        exported_count = 0
        skipped_count = 0
        error_count = 0
        
        # Process tracks in batches using unified batch processor
        for i in range(0, len(liked_tracks), api_batch_size):
            if max_exports is not None and exported_count >= max_exports:
                logger.info(f"Reached maximum export count: {max_exports}")
                break
            
            batch = liked_tracks[i : i + api_batch_size]
            batch_timestamp = datetime.now(UTC)
            
            # Build tracks to match
            tracks_to_match = []
            for track_like in batch:
                if max_exports is not None and exported_count >= max_exports:
                    break
                
                try:
                    track = await self.repositories.core.get_by_id(track_like.track_id)
                    if track and track.artists:
                        tracks_to_match.append(track)
                except Exception as e:
                    logger.exception(f"Error preparing track {track_like.track_id}: {e}")
                    error_count += 1
            
            if not tracks_to_match:
                continue
            
            # Process batch with unified processor
            batch_results = await self._process_batch_with_unified_processor(
                tracks=tracks_to_match,
                connector=self.lastfm_connector,
                processor_func=self._love_track_on_lastfm,
            )
            
            # Update counters based on results
            for result in batch_results:
                if result["status"] == "exported":
                    exported_count += 1
                elif result["status"] == "skipped":
                    skipped_count += 1
                else:
                    error_count += 1
            
            # Update checkpoint
            await self.update_checkpoint(
                checkpoint=checkpoint,
                timestamp=batch_timestamp,
            )
        
        logger.info(
            f"Last.fm loves export completed: {exported_count} exported, "
            f"{skipped_count} skipped out of {candidates} candidates"
        )
        
        return OperationResult(
            operation_name="Last.fm Likes Export",
            exported_count=exported_count,
            skipped_count=skipped_count,
            error_count=error_count,
            already_liked=already_loved,
            candidates=candidates,
        )
    
    # Consolidated utility methods that eliminate duplication
    
    async def get_or_create_checkpoint(
        self,
        user_id: str,
        service: str,
        entity_type: Literal["likes", "plays"],
    ) -> SyncCheckpoint:
        """Get existing checkpoint or create a new one."""
        checkpoint = await self.repositories.checkpoints.get_sync_checkpoint(
            user_id=user_id,
            service=service,
            entity_type=entity_type,
        )
        
        if not checkpoint:
            checkpoint = SyncCheckpoint(
                user_id=user_id,
                service=service,
                entity_type=entity_type,
            )
        
        return checkpoint
    
    async def update_checkpoint(
        self,
        checkpoint: SyncCheckpoint,
        timestamp: datetime | None = None,
        cursor: str | None = None,
    ) -> SyncCheckpoint:
        """Update the checkpoint with new timestamp and cursor."""
        updated = checkpoint.with_update(
            timestamp=timestamp or datetime.now(UTC),
            cursor=cursor,
        )
        
        return await self.repositories.checkpoints.save_sync_checkpoint(updated)
    
    async def _save_like_to_services(
        self,
        track_id: int,
        timestamp: datetime | None = None,
        is_liked: bool = True,
        services: list[str] | None = None,
    ) -> None:
        """Save like status to multiple services at once."""
        services = services or ["narada"]
        now = timestamp or datetime.now(UTC)
        
        for service in services:
            await self.repositories.likes.save_track_like(
                track_id=track_id,
                service=service,
                is_liked=is_liked,
                last_synced=now,
            )
    
    async def _get_unsynced_likes(
        self,
        source_service: str,
        target_service: str,
        is_liked: bool = True,
        since_timestamp: datetime | None = None,
    ) -> list[Any]:
        """Get tracks that need like status syncing."""
        return await self.repositories.likes.get_unsynced_likes(
            source_service=source_service,
            target_service=target_service,
            is_liked=is_liked,
            since_timestamp=since_timestamp,
        )
    
    async def _is_track_already_liked(
        self,
        track_id: int,
        services: list[str],
    ) -> bool:
        """Check if track is already liked in all specified services."""
        for service in services:
            likes = await self.repositories.likes.get_track_likes(
                track_id=track_id,
                services=[service],
            )
            if not any(like.is_liked for like in likes):
                return False
        return True
    
    async def _process_batch_with_unified_processor(
        self,
        tracks: list[Track],
        connector: Any,
        processor_func: Callable[[Track, Any], Coroutine[Any, Any, dict]],
    ) -> list[dict]:
        """Unified batch processor that replaces duplicate processing patterns."""
        results = []
        
        for track in tracks:
            try:
                result = await processor_func(track, connector)
                results.append(result)
            except Exception as e:
                logger.exception(f"Error processing track {track.id}: {e}")
                results.append({
                    "track_id": track.id,
                    "status": "error",
                    "error": str(e),
                })
        
        return results
    
    async def _love_track_on_lastfm(self, track: Track, connector: LastFMConnector) -> dict:
        """Process a single track for Last.fm loving."""
        if not track.artists:
            return {
                "track_id": track.id,
                "status": "error",
                "error": "No artists found",
            }
        
        artist_name = track.artists[0].name
        track_title = track.title
        
        try:
            success = await connector.love_track(
                artist_name=artist_name,
                track_title=track_title,
            )
            
            if success:
                # Save the like status
                if track.id is not None:
                    await self._save_like_to_services(
                        track_id=track.id,
                        services=["lastfm"],
                    )
                return {
                    "track_id": track.id,
                    "status": "exported",
                }
            else:
                return {
                    "track_id": track.id,
                    "status": "skipped",
                    "reason": "API call failed",
                }
        except Exception as e:
            return {
                "track_id": track.id,
                "status": "error",
                "error": str(e),
            }
    
    def _create_import_result(self, operation_name: str, data: dict) -> OperationResult:
        """Create import result using consolidated data."""
        return OperationResult(
            operation_name=operation_name,
            imported_count=data.get("imported_count", 0),
            skipped_count=data.get("skipped_count", 0),
            error_count=data.get("error_count", 0),
            already_liked=data.get("already_liked", 0),
            candidates=data.get("candidates", 0),
        )
    
    def _create_error_result(self, error_message: str, batch_id: str = "") -> OperationResult:
        """Create error result using ResultFactory."""
        return ResultFactory.create_error_result(
            operation_name="Like Operation",
            error_message=error_message,
            batch_id=batch_id,
        )