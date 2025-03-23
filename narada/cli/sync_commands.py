"""Synchronization commands for Narada CLI."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Annotated

from rich.console import Console
import typer

from narada.cli.command_registry import register_command
from narada.cli.ui import display_error, display_sync_stats
from narada.config import get_logger
from narada.services.like_sync import (
    SyncStats,
    run_lastfm_likes_export,
    run_spotify_likes_import,
)

# Initialize console and logger
console = Console()
logger = get_logger(__name__)


def register_sync_commands(app: typer.Typer) -> None:
    """Register synchronization commands with the Typer app."""
    register_command(
        app=app,
        name="import-spotify-likes",
        help_text="Import liked tracks from Spotify to Narada database",
        category="Operations",
        examples=["import-spotify-likes", "import-spotify-likes --limit 100"],
    )(import_spotify_likes)

    register_command(
        app=app,
        name="export-likes-to-lastfm",
        help_text="Export liked tracks from Narada to Last.fm",
        category="Operations",
        examples=["export-likes-to-lastfm", "export-likes-to-lastfm --limit 50"],
    )(export_likes_to_lastfm)


def _run_sync_operation(
    operation_name: str,
    operation_fn: Callable[[], Awaitable[SyncStats]],
    spinner_text: str,
    title: str,
    next_step_message: str | None = None,
) -> None:
    """Run a synchronization operation with standard UI patterns."""
    try:
        # Display progress spinner
        with console.status(spinner_text) as status:
            # Run the operation
            async def main():
                return await operation_fn()

            stats = asyncio.run(main())

            # Update status based on result
            status.update("[bold green]Operation completed!")

        # Display results
        display_sync_stats(
            stats=stats,
            title=title,
            next_step_message=next_step_message,
        )
    except Exception as e:
        display_error(e, operation_name)
        raise typer.Exit(1) from e


def import_spotify_likes(
    limit: Annotated[
        int | None,
        typer.Option("--limit", "-l", help="Maximum number of tracks to import"),
    ] = None,
    batch_size: Annotated[
        int,
        typer.Option(
            "--batch-size", "-b", help="Number of tracks to fetch per API request"
        ),
    ] = 50,
    user_id: Annotated[
        str,
        typer.Option("--user-id", "-u", help="User ID for checkpoint tracking"),
    ] = "default",
) -> None:
    """Import liked tracks from Spotify to Narada database.

    This command fetches tracks that you've liked/saved on Spotify and
    imports them into the Narada database, preserving their like status.
    The operation is resumable and can be run incrementally.
    """
    _run_sync_operation(
        operation_name="Spotify likes import",
        operation_fn=lambda: run_spotify_likes_import(
            user_id=user_id,
            limit=batch_size,
            max_imports=limit,
        ),
        spinner_text="[bold blue]Importing liked tracks from Spotify...",
        title="Spotify Likes Import Results",
        next_step_message=(
            "[yellow]Tip:[/yellow] Run [cyan]narada export-likes-to-lastfm[/cyan] "
            "to sync your likes to Last.fm"
        ),
    )


def export_likes_to_lastfm(
    limit: Annotated[
        int | None,
        typer.Option("--limit", "-l", help="Maximum number of tracks to export"),
    ] = None,
    batch_size: Annotated[
        int,
        typer.Option(
            "--batch-size", "-b", help="Number of tracks to process in each batch"
        ),
    ] = 20,
    user_id: Annotated[
        str,
        typer.Option("--user-id", "-u", help="User ID for checkpoint tracking"),
    ] = "default",
) -> None:
    """Export liked tracks from Narada to Last.fm.

    This command looks for tracks that are liked in Narada but not yet
    loved on Last.fm, and marks them as loved on Last.fm. Narada is
    considered the source of truth for liked tracks.
    """
    _run_sync_operation(
        operation_name="Last.fm likes export",
        operation_fn=lambda: run_lastfm_likes_export(
            user_id=user_id,
            batch_size=batch_size,
            max_exports=limit,
        ),
        spinner_text="[bold blue]Exporting liked tracks to Last.fm...",
        title="Last.fm Loves Export Results",
    )
