"""Synchronization commands for Narada CLI."""

import asyncio
from typing import Annotated

from rich.console import Console
import typer

from narada.cli.command_registry import register_command
from narada.cli.ui import command_error_handler, display_sync_stats
from narada.config import get_logger
from narada.services.like_sync import (
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


@command_error_handler
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
    # Display progress spinner
    with console.status("[bold blue]Importing liked tracks from Spotify...") as status:
        # Run the operation
        stats = asyncio.run(
            run_spotify_likes_import(
                user_id=user_id,
                limit=batch_size,
                max_imports=limit,
            )
        )

        # Update status based on result
        status.update("[bold green]Import completed!")

    # Display results
    display_sync_stats(
        stats=stats,
        title="Spotify Likes Import Results",
        next_step_message=(
            "[yellow]Tip:[/yellow] Run [cyan]narada export-likes-to-lastfm[/cyan] "
            "to sync your likes to Last.fm"
        ),
    )


@command_error_handler
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
    # Display progress spinner
    with console.status("[bold blue]Exporting liked tracks to Last.fm...") as status:
        # Run the operation
        stats = asyncio.run(
            run_lastfm_likes_export(
                user_id=user_id,
                batch_size=batch_size,
                max_exports=limit,
            )
        )

        # Update status based on result
        status.update("[bold green]Export completed!")

    # Display results
    display_sync_stats(
        stats=stats,
        title="Last.fm Loves Export Results",
    )
