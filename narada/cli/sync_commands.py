"""Synchronization commands for Narada CLI."""

import asyncio
from typing import Annotated

from rich.console import Console
import typer

from narada.cli.ui import display_error, display_sync_stats
from narada.config import get_logger
from narada.services.like_sync import run_lastfm_likes_export, run_spotify_likes_import

# Initialize console and logger
console = Console()
logger = get_logger(__name__)


def register_sync_commands(app: typer.Typer) -> None:
    """Register synchronization commands with the Typer app."""
    app.command(name="import-spotify-likes")(import_spotify_likes)
    app.command(name="export-likes-to-lastfm")(export_likes_to_lastfm)


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
    try:
        # Display progress spinner
        with console.status(
            "[bold blue]Importing liked tracks from Spotify..."
        ) as status:
            # Run the import operation
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

    except Exception as e:
        display_error(e, "Spotify likes import")
        raise typer.Exit(1) from e


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
    try:
        # Display progress spinner
        with console.status(
            "[bold blue]Exporting liked tracks to Last.fm..."
        ) as status:
            # Run the export operation
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

    except Exception as e:
        display_error(e, "Last.fm likes export")
        raise typer.Exit(1) from e
