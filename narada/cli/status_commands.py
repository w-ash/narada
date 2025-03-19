"""Service status commands for Narada CLI."""

import asyncio
from typing import Annotated, Any

from rich.console import Console
from rich.table import Table
import typer

from narada.cli.command_registry import SERVICES
from narada.cli.ui import display_error
from narada.config import get_logger, resilient_operation

# Initialize console and logger
console = Console()
logger = get_logger(__name__)


def register_status_commands(app: typer.Typer) -> None:
    """Register status commands with the Typer app."""
    app.command()(status)


@resilient_operation("spotify_check")
async def _check_spotify() -> tuple[bool, str]:
    """Check Spotify API connectivity."""
    from narada.integrations.spotify import SpotifyConnector

    connector = SpotifyConnector()
    match connector.client.auth_manager:
        case None:
            return False, "Not configured - missing API credentials"
        case _:
            try:
                user = await asyncio.to_thread(connector.client.current_user)
                if user is None:
                    return False, "Failed to get user information"
                return True, f"Connected as {user['display_name']}"
            except Exception as e:
                return False, f"Authentication failed: {e}"


@resilient_operation("lastfm_check")
async def _check_lastfm() -> tuple[bool, str]:
    """Check Last.fm API connectivity."""
    from narada.integrations.lastfm import LastFMConnector

    connector = LastFMConnector()
    match connector:
        case _ if not connector.client:
            return False, "Not configured - missing API credentials"
        case _ if not connector.lastfm_username:
            return True, "API connected (no username configured)"
        case _:
            try:
                track_info = await connector.get_lastfm_track_info(
                    artist_name="Caribou",
                    track_title="Volume",
                    lastfm_username=connector.lastfm_username,
                )
                if track_info.lastfm_url:
                    return True, f"Connected as {connector.lastfm_username}"
                else:
                    return False, "Connected but failed to retrieve track data"
            except Exception as e:
                return False, f"API error: {e}"


@resilient_operation("musicbrainz_check")
async def _check_musicbrainz() -> tuple[bool, str]:
    """Check MusicBrainz connectivity."""
    from narada.integrations.musicbrainz import MusicBrainzConnector

    connector = MusicBrainzConnector()
    try:
        recording = await connector.batch_isrc_lookup(["USSM18900468"])
        match recording:
            case {"id": _}:
                return True, "API connected (rate limited to 1 req/sec)"
            case _:
                return False, "API error - failed to fetch test recording"
    except Exception as e:
        return False, f"Connection failed: {e}"


@resilient_operation("service_check")
async def _check_connections() -> list[tuple[str, bool, str]]:
    """Check all service connections concurrently.

    Returns:
        list[tuple[str, bool, str]]: List of (service_name, is_connected, details)
    """
    with logger.contextualize(operation="service_check"):
        # Define service checks with their coroutines
        service_checks = [
            _check_spotify(),
            _check_lastfm(),
            _check_musicbrainz(),
        ]

        # Gather results concurrently
        results = await asyncio.gather(*service_checks, return_exceptions=True)

        # Process results with pattern matching
        def process_result(service: str, result: Any) -> tuple[str, bool, str]:
            match result:
                case Exception() as e:
                    return service, False, f"Error: {e!s}"
                case (is_connected, details):
                    return service, is_connected, details
                case _:
                    return service, False, "Invalid response format"

        return [
            process_result(service, result)
            for service, result in zip(SERVICES, results, strict=False)
        ]


def status(
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Check connection status of music services."""
    with logger.contextualize(operation="status", verbose=verbose):
        try:
            # Create status table
            table = Table(title="Narada Service Status")
            table.add_column("Service", style="cyan")
            table.add_column("Status", style="bold")
            table.add_column("Details", style="dim")

            # Get service status with progress bar
            with typer.progressbar(
                length=len(SERVICES),
                label="Checking service connections",
            ) as progress:
                results = asyncio.run(_check_connections())
                progress.update(len(SERVICES))  # Complete the progress bar

            # Add results to table with emojis
            for service, connected, details in results:
                status_text = (
                    "[green]✓ Connected[/green]"
                    if connected
                    else "[red]✗ Not Connected[/red]"
                )
                table.add_row(service, status_text, details)

            # Print status summary
            console.print("\n")
            console.print(table)
            console.print("\n")

            # Show command help if issues found
            if not all(connected for _, connected, _ in results):
                console.print(
                    "[yellow]Some services not connected. "
                    "Run [bold]narada setup[/bold] to configure.[/yellow]",
                )
                console.print("\n")

            logger.success(
                "Service status check completed",
                connected=sum(1 for _, connected, _ in results if connected),
                total=len(SERVICES),
            )

        except Exception as e:
            display_error(e, "status check")
            raise typer.Exit(1) from e
