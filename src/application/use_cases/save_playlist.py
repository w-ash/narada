"""SavePlaylist use case implementing 2025 patterns for playlist persistence.

This module contains the core business logic for saving playlists with track enrichment,
following Clean Architecture principles and modern Python patterns including:
- Command pattern for rich context encapsulation
- Strategy pattern for pluggable track enrichment
- Async-first design for optimal I/O performance
- Result pattern for explicit error handling
"""

from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from attrs import define, field

from src.config import get_logger
from src.domain.entities.playlist import Playlist
from src.domain.entities.track import Track, TrackList
from src.domain.repositories.interfaces import PlaylistRepository, TrackRepository

logger = get_logger(__name__)

# Type definitions for configuration
OperationType = Literal["create_internal", "create_spotify", "update_spotify"]
ConnectorType = Literal["internal", "spotify", "lastfm", "musicbrainz"]


@define(frozen=True, slots=True)
class EnrichmentConfig:
    """Configuration for track enrichment operations.

    Specifies which enrichment providers to use, fallback strategies,
    and performance tuning parameters.
    """

    enabled: bool = True
    primary_provider: ConnectorType = "spotify"
    fallback_providers: list[ConnectorType] = field(factory=lambda: ["lastfm"])
    timeout_seconds: int = 30
    retry_attempts: int = 2
    parallel_enrichment: bool = True
    enrich_missing_only: bool = True


@define(frozen=True, slots=True)
class PersistenceOptions:
    """Options controlling playlist persistence behavior.

    Encapsulates transaction management, error handling,
    and persistence strategy configuration.
    """

    operation_type: OperationType
    playlist_name: str
    playlist_description: str = "Created by Narada"
    create_internal_playlist: bool = True
    spotify_playlist_id: str | None = None
    append_mode: bool = False
    batch_size: int = 100
    fail_on_track_error: bool = False


@define(frozen=True, slots=True)
class SavePlaylistCommand:
    """Rich command encapsulating playlist save operation with full context.

    Implements the Command pattern to encapsulate all information needed
    for playlist persistence, enabling queuing, retry, and audit capabilities.
    """

    tracklist: TrackList
    enrichment_config: EnrichmentConfig
    persistence_options: PersistenceOptions
    metadata: dict[str, Any] = field(factory=dict)
    timestamp: datetime = field(factory=lambda: datetime.now(UTC))

    def validate(self) -> bool:
        """Validate command business rules.

        Returns:
            True if command is valid for execution
        """
        if not self.tracklist.tracks:
            return False

        return not (
            self.persistence_options.operation_type == "update_spotify"
            and not self.persistence_options.spotify_playlist_id
        )


@define(frozen=True, slots=True)
class SavePlaylistResult:
    """Result of playlist save operation with comprehensive metadata.

    Contains the saved playlist, statistics, and operational metadata
    for monitoring and debugging purposes.
    """

    playlist: Playlist
    enriched_tracks: list[Track]
    operation_type: OperationType
    track_count: int
    enrichment_stats: dict[str, int] = field(factory=dict)
    persistence_stats: dict[str, int] = field(factory=dict)
    execution_time_ms: int = 0
    errors: list[str] = field(factory=list)


class TrackEnrichmentStrategy(Protocol):
    """Protocol for track enrichment strategies.

    Defines the interface for pluggable track enrichment implementations
    that can fetch updated metadata from various music services.
    """

    async def enrich_tracks(
        self, tracks: list[Track], config: EnrichmentConfig
    ) -> list[Track]:
        """Enrich tracks with updated metadata.

        Args:
            tracks: List of tracks to enrich
            config: Enrichment configuration and options

        Returns:
            List of tracks with enriched metadata
        """
        ...


@define(slots=True)
class BasicEnrichmentStrategy:
    """Basic enrichment strategy that preserves tracks as-is.

    Default implementation that performs no enrichment,
    serving as a fallback and example implementation.
    """

    async def enrich_tracks(
        self, tracks: list[Track], config: EnrichmentConfig
    ) -> list[Track]:
        """Return tracks without modification.

        Args:
            tracks: List of tracks to process
            config: Enrichment configuration (ignored)

        Returns:
            Original tracks unchanged
        """
        logger.info(f"Basic enrichment: preserving {len(tracks)} tracks as-is")
        return tracks


class TrackUpsertEnrichmentStrategy:
    """Track enrichment strategy that ensures all tracks have database IDs.

    Uses repository layer to upsert tracks, looking up existing tracks by
    connector IDs (especially Spotify ID) and creating new ones if not found.
    This ensures all tracks have database IDs for downstream processing.
    """

    def __init__(self, track_repo: TrackRepository):
        """Initialize with track repository interface.

        Args:
            track_repo: Repository interface for track operations
        """
        self.track_repo = track_repo

    async def enrich_tracks(
        self, tracks: list[Track], config: EnrichmentConfig
    ) -> list[Track]:
        """Enrich tracks by ensuring they all have database IDs through upsert.

        For each track:
        1. Call repository save_track() which handles upsert automatically
        2. Repository looks up existing track by Spotify ID if available
        3. Repository creates new track if not found
        4. Repository returns track with database ID populated

        Args:
            tracks: List of tracks to process (may not have database IDs)
            config: Enrichment configuration

        Returns:
            List of tracks where all have database IDs
        """
        if not tracks:
            return tracks

        logger.info(f"Track upsert enrichment: processing {len(tracks)} tracks")

        enriched_tracks = []
        upserted_count = 0

        for track in tracks:
            try:
                # Repository handles upsert automatically via Spotify ID
                saved_track = await self.track_repo.save_track(track)
                enriched_tracks.append(saved_track)

                if saved_track.id != track.id:
                    upserted_count += 1

            except Exception as e:
                logger.warning(f"Failed to upsert track '{track.title}': {e}")
                # Keep original track as fallback
                enriched_tracks.append(track)

        logger.info(
            f"Track upsert enrichment completed: {upserted_count} tracks upserted, {len(enriched_tracks)} total"
        )
        return enriched_tracks


@define(slots=True)
class SavePlaylistUseCase:
    """Use case for playlist persistence with track enrichment.

    Orchestrates the complete playlist save workflow including:
    1. Track enrichment from external services
    2. Database persistence with transaction management
    3. Result aggregation and error handling

    Follows Clean Architecture principles by depending only on
    abstractions (protocols) and delegating infrastructure concerns.
    """

    track_repo: TrackRepository
    playlist_repo: PlaylistRepository
    enrichment_strategy: TrackEnrichmentStrategy | None = field(default=None)

    async def execute(self, command: SavePlaylistCommand) -> SavePlaylistResult:
        """Execute playlist save operation.

        Args:
            command: Rich command with operation context

        Returns:
            Result with saved playlist and operational metadata

        Raises:
            ValueError: If command validation fails
        """
        if not command.validate():
            raise ValueError("Invalid command: failed business rule validation")

        start_time = datetime.now(UTC)

        logger.info(
            "Starting playlist save operation",
            operation_type=command.persistence_options.operation_type,
            track_count=len(command.tracklist.tracks),
            enrichment_enabled=command.enrichment_config.enabled,
        )

        try:
            # Step 1: Enrich tracks if enabled
            enriched_tracks = await self._enrich_tracks(command)

            # Step 2: Persist playlist and tracks
            saved_playlist = await self._persist_playlist(command, enriched_tracks)

            # Step 3: Calculate execution metrics
            execution_time = int(
                (datetime.now(UTC) - start_time).total_seconds() * 1000
            )

            result = SavePlaylistResult(
                playlist=saved_playlist,
                enriched_tracks=enriched_tracks,
                operation_type=command.persistence_options.operation_type,
                track_count=len(enriched_tracks),
                execution_time_ms=execution_time,
            )

            logger.info(
                "Playlist save operation completed successfully",
                playlist_id=saved_playlist.id,
                track_count=result.track_count,
                execution_time_ms=execution_time,
            )

            return result

        except Exception as e:
            logger.error(
                "Playlist save operation failed",
                error=str(e),
                operation_type=command.persistence_options.operation_type,
            )
            raise

    async def _enrich_tracks(self, command: SavePlaylistCommand) -> list[Track]:
        """Enrich tracks using configured strategy.

        Args:
            command: Save command with enrichment configuration

        Returns:
            List of enriched tracks
        """
        if not command.enrichment_config.enabled:
            logger.debug("Track enrichment disabled, returning original tracks")
            return command.tracklist.tracks

        # Set up enrichment strategy if not provided
        if self.enrichment_strategy is None:
            # Use injected track repository for upsert enrichment
            strategy = TrackUpsertEnrichmentStrategy(self.track_repo)

            logger.debug(
                f"Using TrackUpsertEnrichmentStrategy to enrich {len(command.tracklist.tracks)} tracks",
                provider=command.enrichment_config.primary_provider,
            )

            return await strategy.enrich_tracks(
                command.tracklist.tracks, command.enrichment_config
            )
        else:
            # Use provided strategy
            logger.debug(
                f"Using provided enrichment strategy to enrich {len(command.tracklist.tracks)} tracks",
                provider=command.enrichment_config.primary_provider,
            )

            return await self.enrichment_strategy.enrich_tracks(
                command.tracklist.tracks, command.enrichment_config
            )

    async def _persist_playlist(
        self, command: SavePlaylistCommand, enriched_tracks: list[Track]
    ) -> Playlist:
        """Persist playlist and tracks to database.

        Args:
            command: Save command with persistence options
            enriched_tracks: Tracks to include in playlist

        Returns:
            Saved playlist entity
        """
        options = command.persistence_options

        # Step 1: Persist all tracks in bulk using repository
        logger.debug(f"Persisting {len(enriched_tracks)} tracks")
        persisted_tracks = []

        for track in enriched_tracks:
            try:
                saved_track = await self.track_repo.save_track(track)
                persisted_tracks.append(saved_track)
            except Exception as e:
                if options.fail_on_track_error:
                    raise
                logger.warning(f"Failed to persist track {track.title}: {e}")
                persisted_tracks.append(track)  # Keep original if persist fails

        # Step 2: Create playlist based on operation type
        if options.operation_type == "create_internal":
            playlist = await self._create_internal_playlist(options, persisted_tracks)
        elif options.operation_type == "create_spotify":
            playlist = await self._create_spotify_playlist(options, persisted_tracks)
        elif options.operation_type == "update_spotify":
            playlist = await self._update_spotify_playlist(options, persisted_tracks)
        else:
            raise ValueError(f"Unsupported operation type: {options.operation_type}")

        logger.debug(
            "Successfully persisted playlist",
            playlist_id=playlist.id,
            operation_type=options.operation_type,
            track_count=len(persisted_tracks),
        )

        return playlist

    async def _create_internal_playlist(
        self, options: PersistenceOptions, tracks: list[Track]
    ) -> Playlist:
        """Create new internal playlist."""
        from src.domain.workflows.playlist_operations import create_playlist_operation

        # Create playlist entity using domain logic
        playlist = create_playlist_operation(
            TrackList(tracks=tracks),
            {
                "name": options.playlist_name,
                "description": options.playlist_description,
            },
            tracks,
        )

        # Save to database
        return await self.playlist_repo.save_playlist(playlist)

    async def _create_spotify_playlist(
        self, options: PersistenceOptions, tracks: list[Track]
    ) -> Playlist:
        """Create new Spotify-connected playlist."""
        from src.domain.workflows.playlist_operations import (
            create_spotify_playlist_operation,
        )

        if not options.spotify_playlist_id:
            raise ValueError(
                "Spotify playlist ID required for create_spotify operation"
            )

        # Create playlist entity using domain logic
        playlist = create_spotify_playlist_operation(
            TrackList(tracks=tracks),
            {
                "name": options.playlist_name,
                "description": options.playlist_description,
            },
            tracks,
            options.spotify_playlist_id,
        )

        # Save to database
        return await self.playlist_repo.save_playlist(playlist)

    async def _update_spotify_playlist(
        self, options: PersistenceOptions, tracks: list[Track]
    ) -> Playlist:
        """Update existing Spotify playlist."""
        from src.domain.workflows.playlist_operations import (
            update_playlist_tracks_operation,
        )

        if not options.spotify_playlist_id:
            raise ValueError(
                "Spotify playlist ID required for update_spotify operation"
            )

        # Get existing playlist
        existing = await self.playlist_repo.get_playlist_by_connector(
            "spotify", options.spotify_playlist_id, raise_if_not_found=True
        )

        if existing is None:
            raise ValueError(
                f"Playlist with Spotify ID {options.spotify_playlist_id} not found"
            )

        # Update playlist using domain logic
        updated = update_playlist_tracks_operation(
            existing, tracks, options.append_mode
        )

        # Save updated playlist
        if existing.id is None:
            raise ValueError("Existing playlist has no ID")
        return await self.playlist_repo.update_playlist(existing.id, updated)
