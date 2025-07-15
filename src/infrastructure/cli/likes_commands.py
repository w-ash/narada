"""Likes data commands for Narada CLI."""

from typing import Annotated

import typer

from src.application.use_cases.sync_likes import (
    run_lastfm_likes_export,
    run_spotify_likes_import,
)
from src.domain.entities import OperationResult
from src.infrastructure.cli.async_helpers import async_db_operation
from src.infrastructure.persistence.repositories.track import TrackRepositories

# Create likes subcommand app
app = typer.Typer(help="Manage liked tracks data")


@app.command(name="import-likes-from-spotify-api")
def import_likes_from_spotify_api(
    limit: Annotated[
        int | None,
        typer.Option("--limit", "-l", help="Maximum number of tracks to import"),
    ] = None,
    batch_size: Annotated[
        int | None,
        typer.Option("--batch-size", "-b", help="API batch size"),
    ] = None,
    user_id: Annotated[
        str,
        typer.Option("--user-id", "-u", help="User ID for checkpoint tracking"),
    ] = "default",
) -> None:
    """Import liked tracks from Spotify API."""
    _run_spotify_api_likes_import(user_id, batch_size, limit)


@app.command(name="export-likes-to-lastfm")
def export_likes_to_lastfm(
    limit: Annotated[
        int | None,
        typer.Option("--limit", "-l", help="Maximum number of tracks to export"),
    ] = None,
    batch_size: Annotated[
        int | None,
        typer.Option("--batch-size", "-b", help="Batch size for processing"),
    ] = None,
    user_id: Annotated[
        str,
        typer.Option("--user-id", "-u", help="User ID for checkpoint tracking"),
    ] = "default",
) -> None:
    """Export liked tracks to Last.fm via API."""
    _run_lastfm_likes_export(user_id, batch_size, limit)


@async_db_operation(
    progress_text="Importing liked tracks from Spotify API...",
    success_text="Spotify likes imported successfully!",
    display_title="Spotify API Likes Import Results",
    next_step_message="[yellow]Tip:[/yellow] Run [cyan]narada export-likes-to-lastfm[/cyan] to sync your likes to Last.fm",
)
async def _run_spotify_api_likes_import(
    user_id: str,
    batch_size: int | None,
    limit: int | None,
    repositories: "TrackRepositories",
) -> OperationResult:
    """Run Spotify API likes import operation."""
    return await run_spotify_likes_import(
        repositories=repositories,
        user_id=user_id,
        limit=batch_size,  # This is API batch size
        max_imports=limit,  # This is max total imports
    )


@async_db_operation(
    progress_text="Exporting liked tracks to Last.fm...",
    success_text="Likes exported to Last.fm successfully!",
    display_title="Last.fm Likes Export Results",
)
async def _run_lastfm_likes_export(
    user_id: str,
    batch_size: int | None,
    limit: int | None,
    repositories: TrackRepositories,
) -> OperationResult:
    """Run Last.fm likes export operation."""
    return await run_lastfm_likes_export(
        repositories=repositories,
        user_id=user_id,
        batch_size=batch_size,
        max_exports=limit,
    )
