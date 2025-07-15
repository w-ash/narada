"""Service status commands for Narada CLI."""

import asyncio
from typing import Annotated

from rich.console import Console
from rich.table import Table
import typer

from src.infrastructure.cli.async_helpers import async_operation
from src.infrastructure.cli.command_registry import SERVICES
from src.infrastructure.config import get_logger, resilient_operation

# Initialize console and logger
console = Console()
logger = get_logger(__name__)


def register_status_commands(app: typer.Typer) -> None:
    """Register status commands with the Typer app."""
    app.command(
        name="status",
        help="Check connection status of music services",
        rich_help_panel="⚙️ System",
    )(status)


@resilient_operation("spotify_check")
async def _check_spotify() -> tuple[bool, str]:
    """Check Spotify API connectivity."""
    from src.infrastructure.connectors.spotify import SpotifyConnector

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
    from src.infrastructure.connectors.lastfm import LastFMConnector

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
    from src.infrastructure.connectors.musicbrainz import MusicBrainzConnector

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
    # Define service checks with their coroutines
    service_checks = [
        _check_spotify(),
        _check_lastfm(),
        _check_musicbrainz(),
    ]

    # Gather results concurrently
    results = await asyncio.gather(*service_checks, return_exceptions=True)

    # Process results with pattern matching
    def process_result(service: str, result: object) -> tuple[str, bool, str]:
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
    _run_status_check(verbose)


@async_operation(
    progress_text="Checking service connections...",
    success_text="Service status check completed",
)
async def _run_status_check(verbose: bool) -> None:
    """Run the status check operation."""
    with logger.contextualize(operation="status", verbose=verbose):
        # Get service status
        results = await _check_connections()

        # Create status table
        table = Table(title="Narada Service Status")
        table.add_column("Service", style="cyan")
        table.add_column("Status", style="bold")
        table.add_column("Details", style="dim")

        # Add results to table
        for service, connected, details in results:
            status_text = (
                "[green]✓ Connected[/green]"
                if connected
                else "[red]✗ Not Connected[/red]"
            )
            table.add_row(service, status_text, details)

        # Display results
        console.print(table)

        # Show help if needed
        if not all(connected for _, connected, _ in results):
            console.print(
                "\n[yellow]Some services not connected. "
                "Run [bold]narada setup[/bold] to configure.[/yellow]"
            )

        logger.success(
            "Service status check completed",
            connected=sum(1 for _, connected, _ in results if connected),
            total=len(SERVICES),
        )
