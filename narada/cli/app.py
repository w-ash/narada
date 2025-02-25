"""Narada CLI - Cross-service music integration platform."""

import asyncio
import sys
from typing import Optional

import typer
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text

from narada.config import get_config, log_startup_info, setup_loguru_logger
from narada.integrations.lastfm import LastFmConnector
from narada.integrations.musicbrainz import MusicBrainzConnector
from narada.integrations.spotify import SpotifyConnector

# Initialize Typer app with Rich styling
app = typer.Typer(
    help="Narada - Your personal music integration platform",
    add_completion=False,
)

console = Console()

# Set up event loop policy for Windows if needed
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@app.callback()
def callback():
    """Narada - Connect your music universe.

    Seamlessly integrate Spotify, Last.fm, and MusicBrainz
    to create the ultimate music experience.
    """
    # Configure logging
    setup_loguru_logger()
    log_startup_info()


@app.command()
def status():
    """Check connection status of music services."""
    console.print("\n[bold cyan]Checking music service connections...[/bold cyan]\n")

    # Create a progress display
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}[/bold blue]"),
        console=console,
    ) as progress:
        # Run async checks in asyncio event loop
        spotify_task = progress.add_task("Checking Spotify connection...", total=None)
        lastfm_task = progress.add_task("Checking Last.fm connection...", total=None)
        mb_task = progress.add_task("Checking MusicBrainz connection...", total=None)

        # Run the async status check
        result = asyncio.run(
            _check_connections(progress, spotify_task, lastfm_task, mb_task)
        )

    # Display results in a table
    table = Table(title="Music Service Status", show_header=True)
    table.add_column("Service", style="cyan")
    table.add_column("Status", style="white")
    table.add_column("Details", style="green")

    for service, connected, details in result:
        status_text = (
            "[bold green]Connected[/bold green]"
            if connected
            else "[bold red]Not Connected[/bold red]"
        )
        table.add_row(service, status_text, details)

    console.print("\n")
    console.print(table)
    console.print("\n")


async def _check_connections(progress, spotify_task, lastfm_task, mb_task):
    """Asynchronously check all service connections."""
    results = []

    # Check Spotify connection
    spotify_status = await _check_spotify()
    progress.update(
        spotify_task, description="[bold green]Spotify checked[/bold green]"
    )
    results.append(("Spotify", spotify_status[0], spotify_status[1]))

    # Check Last.fm connection
    lastfm_status = await _check_lastfm()
    progress.update(lastfm_task, description="[bold green]Last.fm checked[/bold green]")
    results.append(("Last.fm", lastfm_status[0], lastfm_status[1]))

    # Check MusicBrainz connection
    mb_status = await _check_musicbrainz()
    progress.update(mb_task, description="[bold green]MusicBrainz checked[/bold green]")
    results.append(("MusicBrainz", mb_status[0], mb_status[1]))

    return results


async def _check_spotify():
    """Check Spotify API connectivity."""
    try:
        connector = SpotifyConnector()
        client_id = get_config("SPOTIFY_CLIENT_ID")

        if not client_id:
            return False, "API credentials not configured"

        # Get current user to verify connection
        current_user = await asyncio.to_thread(connector.client.current_user)
        if current_user and current_user.get("id"):
            return (
                True,
                f"Connected as {current_user.get('display_name') or current_user.get('id')}",
            )
        return False, "Failed to get user info"
    except Exception as e:
        return False, str(e)


async def _check_lastfm():
    """Check Last.fm API connectivity."""
    try:
        connector = LastFmConnector()
        api_key = get_config("LASTFM_API_KEY")
        username = get_config("LASTFM_USERNAME")

        if not api_key:
            return False, "API credentials not configured"

        if not username:
            return True, "API connected (no username configured)"

        # Test with a popular track
        play_count = await connector.get_track_play_count(
            "The Beatles", "Let It Be", username
        )
        if play_count.track_url:
            return True, f"Connected as {username}"
        return False, "API request failed"
    except Exception as e:
        return False, str(e)


async def _check_musicbrainz():
    """Check MusicBrainz connectivity."""
    try:
        connector = MusicBrainzConnector()

        # Try a test ISRC lookup (Michael Jackson's Thriller)
        isrc = "USSM18900468"
        recording = await connector.get_recording_by_isrc(isrc)

        if recording and "id" in recording:
            return True, "API connection successful"
        return False, "API request failed"
    except Exception as e:
        return False, str(e)


@app.command()
def setup():
    """Set up Narada with your music service accounts."""
    # Display a nicely formatted panel
    console.print(
        Panel(
            "[bold green]Welcome to Narada Setup![/bold green]\n\n"
            "To connect your music services, you'll need to update your .env file with API keys.\n"
            "Follow these steps:\n\n"
            "1. [cyan]Create a Spotify Developer App[/cyan] at developer.spotify.com\n"
            "2. [cyan]Get a Last.fm API Key[/cyan] at last.fm/api\n"
            "3. [yellow]Add these credentials to your .env file[/yellow]",
            title="[bold]Narada Setup[/bold]",
            border_style="green",
            expand=False,
        )
    )

    # Show current configuration
    console.print("\n[bold cyan]Current Configuration:[/bold cyan]")

    config_table = Table(show_header=True)
    config_table.add_column("Service", style="cyan")
    config_table.add_column("Setting", style="green")
    config_table.add_column("Status", style="yellow")

    for service, key, config_key in [
        ("Spotify", "Client ID", "SPOTIFY_CLIENT_ID"),
        ("Spotify", "Client Secret", "SPOTIFY_CLIENT_SECRET"),
        ("Last.fm", "API Key", "LASTFM_API_KEY"),
        ("Last.fm", "API Secret", "LASTFM_API_SECRET"),
        ("Last.fm", "Username", "LASTFM_USERNAME"),
    ]:
        value = get_config(config_key)
        status = "[green]✓ Configured[/green]" if value else "[red]✗ Not Set[/red]"
        config_table.add_row(service, key, status)

    console.print(config_table)
    console.print("\n")


@app.command()
def sort_playlist(
    source_id: str = typer.Option(..., help="Spotify playlist ID to sort"),
    username: str = typer.Option(..., help="Last.fm username for play counts"),
    create_new: bool = typer.Option(
        True, help="Create new playlist instead of updating existing"
    ),
    target_name: Optional[str] = typer.Option(
        None, help="Name for the sorted playlist"
    ),
):
    """Sort a Spotify playlist by Last.fm play counts.

    This command fetches a Spotify playlist, retrieves play counts from Last.fm,
    sorts tracks by play count, and creates a new sorted playlist.
    """
    # Visually engaging status indicator
    with Live(
        Panel(
            "[bold blue]Initializing playlist sort operation...[/bold blue]",
            title="[bold cyan]Narada Playlist Sort[/bold cyan]",
            border_style="blue",
        ),
        console=console,
        refresh_per_second=4,
    ) as live:
        # Set up the parameters for the sort operation
        target = target_name or f"{source_id} (Sorted by plays)"
        live.update(
            Panel(
                f"[bold green]Source Playlist:[/bold green] {source_id}\n"
                f"[bold green]Last.fm Username:[/bold green] {username}\n"
                f"[bold green]Target Playlist:[/bold green] {target}\n"
                f"[bold green]Create New:[/bold green] {'Yes' if create_new else 'No'}\n\n"
                "[yellow]Sorting operation not yet implemented[/yellow]",
                title="[bold cyan]Narada Playlist Sort[/bold cyan]",
                border_style="blue",
            )
        )

        # Simulate progress for now
        console.print("\n[yellow]This feature is coming soon![/yellow]\n")


@app.command()
def dashboard():
    """Launch interactive music dashboard."""
    console.print(
        Panel(
            "[bold yellow]The Narada Dashboard is coming soon![/bold yellow]\n\n"
            "This interactive interface will show your:\n"
            "• [cyan]Top artists across platforms[/cyan]\n"
            "• [cyan]Listening history visualizations[/cyan]\n"
            "• [cyan]Smart playlist recommendations[/cyan]",
            title="[bold]Narada Dashboard[/bold]",
            border_style="yellow",
        )
    )


def main():
    """Main entry point for the CLI application."""
    # Display an eye-catching header on startup
    console.print("\n")
    console.print(
        Text("🎵 NARADA", style="bold rgb(255,140,0)", justify="center"),
        Text("Music Integration Platform", style="rgb(255,165,0)", justify="center"),
        "\n",
    )

    try:
        app()
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled by user[/yellow]")
        return 1
    except Exception as e:
        console.print(f"\n[bold red]Error:[/bold red] {str(e)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
