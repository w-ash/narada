"""Import orchestrator service providing unified interface for all import operations.

Handles business logic, validation, progress reporting, and error handling
for importing tracks from external services. Provides a unified interface
for different import modes and service types.
"""

from pathlib import Path
from typing import Literal

from src.application.utilities.progress_integration import DatabaseProgressContext
from src.config import get_logger
from src.domain.entities import OperationResult
from src.infrastructure.persistence.repositories.track import TrackRepositories
from src.infrastructure.services.lastfm_import import LastfmImportService
from src.infrastructure.services.spotify_import import SpotifyImportService

logger = get_logger(__name__)

ServiceType = Literal["lastfm", "spotify"]
ImportMode = Literal["recent", "incremental", "full", "file"]


class ImportOrchestrator:
    """Unified orchestrator for all import operations.

    Centralizes business logic, validation, and progress handling that was
    previously duplicated across CLI commands. Provides a clean, consistent
    interface for the CLI layer.
    """

    def __init__(self, repositories: TrackRepositories) -> None:
        """Initialize with repository access."""
        self.repositories = repositories
        self._lastfm_service = None
        self._spotify_service = None

    @property
    def lastfm_service(self) -> LastfmImportService:
        """Lazy-loaded LastFM import service."""
        if self._lastfm_service is None:
            self._lastfm_service = LastfmImportService(self.repositories)
        return self._lastfm_service

    @property
    def spotify_service(self) -> SpotifyImportService:
        """Lazy-loaded Spotify import service."""
        if self._spotify_service is None:
            self._spotify_service = SpotifyImportService(self.repositories)
        return self._spotify_service

    async def run_import(
        self, service: ServiceType, mode: ImportMode, **forwarded_params
    ) -> OperationResult:
        """Run import operation with unified interface.

        Args:
            service: Import service to use ("lastfm" or "spotify")
            mode: Import mode ("recent", "incremental", "full", or "file")
            **forwarded_params: Mode-specific parameters

        Returns:
            OperationResult with import statistics

        Raises:
            ValueError: For invalid service/mode combinations or missing parameters
        """
        match service:
            case "lastfm":
                return await self._run_lastfm_import(mode, **forwarded_params)
            case "spotify":
                return await self._run_spotify_import(mode, **forwarded_params)
            case _:
                raise ValueError(f"Unknown service: {service}")

    async def _run_lastfm_import(
        self, mode: ImportMode, **forwarded_params
    ) -> OperationResult:
        """Handle LastFM import operations."""
        match mode:
            case "recent":
                return await self._run_lastfm_recent(**forwarded_params)
            case "incremental":
                return await self._run_lastfm_incremental(**forwarded_params)
            case "full":
                return await self._run_lastfm_full_history(**forwarded_params)
            case _:
                raise ValueError(f"LastFM service doesn't support mode: {mode}")

    async def _run_spotify_import(
        self, mode: ImportMode, **forwarded_params
    ) -> OperationResult:
        """Handle Spotify import operations."""
        match mode:
            case "file":
                return await self._run_spotify_file(**forwarded_params)
            case _:
                raise ValueError(f"Spotify service doesn't support mode: {mode}")

    async def _run_lastfm_recent(
        self, limit: int = 1000, resolve_tracks: bool = False, **additional_options
    ) -> OperationResult:
        """Run LastFM recent plays import."""
        _ = additional_options  # Reserved for future extensibility

        # Use async context manager for session-per-operation pattern
        async with DatabaseProgressContext(
            description=f"Importing {limit:,} recent Last.fm plays...",
            success_text="Recent plays imported successfully!",
            display_title="Last.fm Recent Import Results",
            next_step_message="[yellow]Tip:[/yellow] Run [cyan]narada workflows[/cyan] to create playlists",
        ) as progress:

            async def _import_operation(
                repositories: TrackRepositories,
            ) -> OperationResult:
                service = LastfmImportService(repositories)
                if resolve_tracks:
                    return await service.import_recent_plays_with_resolution(
                        limit=limit
                    )
                else:
                    return await service.import_recent_plays(limit=limit)

            return await progress.run_with_repositories(_import_operation)

    async def _run_lastfm_incremental(
        self,
        user_id: str | None = None,
        resolve_tracks: bool = True,
        **additional_options,
    ) -> OperationResult:
        """Run LastFM incremental import."""
        _ = additional_options  # Reserved for future extensibility

        # Use async context manager for session-per-operation pattern
        async with DatabaseProgressContext(
            description="Running incremental Last.fm import...",
            success_text="Incremental import completed successfully!",
            display_title="Last.fm Incremental Import Results",
            next_step_message="[yellow]Tip:[/yellow] Run this regularly to stay up to date",
        ) as progress:

            async def _import_operation(
                repositories: TrackRepositories,
            ) -> OperationResult:
                service = LastfmImportService(repositories)
                return await service.import_incremental_plays(
                    user_id=user_id, resolve_tracks=resolve_tracks
                )

            return await progress.run_with_repositories(_import_operation)

    async def _run_lastfm_full_history(
        self,
        user_id: str | None = None,
        resolve_tracks: bool = True,
        confirm: bool = False,
        **additional_options,
    ) -> OperationResult:
        """Run LastFM full history import with checkpoint reset."""
        _ = additional_options  # Reserved for future extensibility
        # Confirmation logic moved to service layer
        if not confirm:
            from rich.console import Console
            import typer

            console = Console()
            console.print("[yellow]⚠️  Full History Import Warning[/yellow]")
            console.print("This will:")
            console.print("• Import your entire Last.fm play history")
            console.print("• Reset any existing sync checkpoint")
            console.print("• Make many API calls (may take 10+ minutes)")

            proceed = typer.confirm("Do you want to proceed?")
            if not proceed:
                console.print("[dim]Full history import cancelled[/dim]")
                # Return a cancelled result instead of raising Exit
                return OperationResult(
                    operation_name="Last.fm Full History Import",
                    plays_processed=0,
                    play_metrics={
                        "cancelled": True,
                    },
                    # Unified count fields
                    imported_count=0,
                    skipped_count=0,
                    error_count=0,
                )

        # Use async context manager for session-per-operation pattern
        async with DatabaseProgressContext(
            description="Running full Last.fm history import...",
            success_text="Full history import completed successfully!",
            display_title="Last.fm Full History Import Results",
            next_step_message="[yellow]Tip:[/yellow] Use incremental imports going forward",
        ) as progress:

            async def _import_operation(
                repositories: TrackRepositories,
            ) -> OperationResult:
                service = LastfmImportService(repositories)

                # Reset checkpoint before full import
                username = user_id or service.lastfm_connector.lastfm_username
                if username:
                    await self._reset_lastfm_checkpoint(username)

                # Use large limit for full history (API will stop when no more data)
                if resolve_tracks:
                    return await service.import_recent_plays_with_resolution(
                        limit=50000
                    )
                else:
                    return await service.import_recent_plays(limit=50000)

            return await progress.run_with_repositories(_import_operation)

    async def _run_spotify_file(
        self, file_path: Path, **additional_options
    ) -> OperationResult:
        """Run Spotify file import with validation."""
        _ = additional_options  # Reserved for future extensibility
        # File validation moved to service layer
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if not file_path.is_file():
            raise ValueError(f"Path is not a file: {file_path}")

        # Use async context manager for session-per-operation pattern
        async with DatabaseProgressContext(
            description="Importing Spotify play history from JSON...",
            success_text="Spotify plays imported successfully!",
            display_title="Spotify JSON Import Results",
            next_step_message="[yellow]Tip:[/yellow] Run [cyan]narada workflows[/cyan] to create playlists",
        ) as progress:

            async def _import_operation(
                repositories: TrackRepositories,
            ) -> OperationResult:
                service = SpotifyImportService(repositories)
                return await service.import_from_file(file_path)

            return await progress.run_with_repositories(_import_operation)

    async def _reset_lastfm_checkpoint(self, username: str) -> None:
        """Reset Last.fm checkpoint for full history import."""
        from src.domain.entities import SyncCheckpoint
        from src.infrastructure.persistence.database import get_session
        from src.infrastructure.persistence.repositories.track import TrackRepositories

        # Create a new checkpoint with no timestamp (forces full import)
        checkpoint = SyncCheckpoint(
            user_id=username, service="lastfm", entity_type="plays", last_timestamp=None
        )

        # Use session-per-operation pattern for consistency
        async with get_session() as session:
            repositories = TrackRepositories(session)
            await repositories.checkpoints.save_sync_checkpoint(checkpoint)

        logger.info(f"Reset Last.fm checkpoint for user {username}")


# Convenience function for CLI usage
async def run_import(
    service: ServiceType,
    mode: ImportMode,
    repositories: TrackRepositories,
    **forwarded_params,
) -> OperationResult:
    """Convenience function for running imports from CLI.

    This provides a simple interface for CLI commands while centralizing
    all business logic in the ImportOrchestrator.
    """
    orchestrator = ImportOrchestrator(repositories)
    return await orchestrator.run_import(service, mode, **forwarded_params)
