"""Narada CLI command implementations.

This module contains the implementation of all CLI commands,
keeping them separate from the CLI initialization logic.
"""

import asyncio
from pathlib import Path
from typing import Any, List, Optional, Tuple

import typer
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from typing_extensions import Annotated

from narada.config import get_config, get_logger, resilient_operation

# Initialize console and logger
console = Console()
logger = get_logger(__name__)

# Define service names as constants
SERVICES = ["Spotify", "Last.fm", "MusicBrainz"]


def register_commands(app: typer.Typer) -> None:
    """Register all commands with the Typer app."""
    app.command()(status)
    app.command()(setup)
    app.command(name="workflow")(run_workflow)
    app.command()(dashboard)


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
    from narada.integrations.lastfm import LastFmConnector

    connector = LastFmConnector()
    match connector:
        case _ if not connector.api_key:
            return False, "Not configured - missing API key"
        case _ if not connector.username:
            return True, "API connected (no username configured)"
        case _:
            try:
                play_count = await connector.get_track_play_count(
                    "The Beatles", "Let It Be", connector.username
                )
                return bool(play_count.track_url), f"Connected as {connector.username}"
            except Exception as e:
                return False, f"API error: {e}"


@resilient_operation("musicbrainz_check")
async def _check_musicbrainz() -> tuple[bool, str]:
    """Check MusicBrainz connectivity."""
    from narada.integrations.musicbrainz import MusicBrainzConnector

    connector = MusicBrainzConnector()
    try:
        recording = await connector.get_recording_by_isrc("USSM18900468")
        match recording:
            case {"id": _}:
                return True, "API connected (rate limited to 1 req/sec)"
            case _:
                return False, "API error - failed to fetch test recording"
    except Exception as e:
        return False, f"Connection failed: {e}"


@resilient_operation("service_check")
async def _check_connections() -> List[Tuple[str, bool, str]]:
    """Check all service connections concurrently.

    Returns:
        List[Tuple[str, bool, str]]: List of (service_name, is_connected, details)
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
        def process_result(service: str, result: Any) -> Tuple[str, bool, str]:
            match result:
                case Exception() as e:
                    return service, False, f"Error: {str(e)}"
                case (is_connected, details):
                    return service, is_connected, details
                case _:
                    return service, False, "Invalid response format"

        return [
            process_result(service, result)
            for service, result in zip(SERVICES, results)
        ]


def status(
    ctx: typer.Context,
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
                    "Run [bold]narada setup[/bold] to configure.[/yellow]"
                )
                console.print("\n")

            logger.success(
                "Service status check completed",
                connected=sum(1 for _, connected, _ in results if connected),
                total=len(SERVICES),
            )

        except Exception as e:
            logger.exception("Status check failed")
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1)


def setup(
    force: Annotated[
        bool, typer.Option("--force", "-f", help="Force reconfiguration")
    ] = False,
) -> None:
    """Configure your music service connections."""
    logger.info("Starting setup wizard", force=force)

    if not force and any(
        get_config(k)
        for _, _, k in [
            ("Spotify", "Client ID", "SPOTIFY_CLIENT_ID"),
            ("Last.fm", "API Key", "LASTFM_API_KEY"),
        ]
    ):
        console.print(
            "\n[yellow]Configuration already exists. Use --force to reconfigure.[/yellow]\n"
        )
        return

    # Display setup instructions
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

    # Configuration metadata for checking
    config_keys = [
        ("Spotify", "Client ID", "SPOTIFY_CLIENT_ID"),
        ("Spotify", "Client Secret", "SPOTIFY_CLIENT_SECRET"),
        ("Last.fm", "API Key", "LASTFM_API_KEY"),
        ("Last.fm", "API Secret", "LASTFM_API_SECRET"),
        ("Last.fm", "Username", "LASTFM_USERNAME"),
    ]

    # Display configuration status
    for service, key, config_key in config_keys:
        value = get_config(config_key)
        status = "[green]✓ Configured[/green]" if value else "[red]✗ Not Set[/red]"
        config_table.add_row(service, key, status)

    console.print(config_table)
    console.print("\n")

    # Log configuration status
    logger.info(
        "Configuration status displayed",
        configured=sum(1 for _, _, k in config_keys if get_config(k)),
        total=len(config_keys),
    )

    # Show path to .env file
    env_path = Path(".env").absolute()
    console.print(f"[bold]Edit your configuration file at:[/bold] {env_path}")
    console.print("\n")


def run_workflow(
    workflow_id: Annotated[
        Optional[str], typer.Argument(help="Workflow ID to execute", default=None)
    ] = None,
) -> None:
    """Run a workflow from available definitions."""
    import json
    from pathlib import Path

    from narada.config import get_config
    from narada.workflows.prefect import run_workflow as execute_workflow

    # Get workflow definitions directory with fallback
    workflows_dir = Path(get_config("WORKFLOWS_DIR", "narada/workflows/definitions"))

    # Ensure directory exists
    if not workflows_dir.exists():
        workflows_dir.mkdir(parents=True, exist_ok=True)
        console.print(f"[yellow]Created workflows directory: {workflows_dir}[/yellow]")

    # Discover available workflows
    available_workflows = {}
    for file_path in workflows_dir.glob("*.json"):
        try:
            with open(file_path, "r") as f:
                workflow_def = json.load(f)
                wf_id = workflow_def.get("id")
                if wf_id:
                    available_workflows[wf_id] = {
                        "name": workflow_def.get("name", wf_id),
                        "description": workflow_def.get("description", ""),
                        "path": file_path,
                    }
        except Exception as e:
            logger.warning(f"Error loading workflow from {file_path}: {e}")

    # Show workflow list if none specified
    if not workflow_id:
        if not available_workflows:
            console.print("[red]No workflows found in definitions directory.[/red]")
            console.print(
                f"[yellow]Add workflow JSON files to: {workflows_dir}[/yellow]"
            )
            return

        # Display workflow table
        table = Table(title="Available Workflows")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Description", style="dim")

        for wf_id, wf_info in sorted(available_workflows.items()):
            table.add_row(wf_id, wf_info["name"], wf_info["description"])

        console.print(table)

        # Interactive selection
        choices = list(available_workflows.keys())
        if typer.confirm("Run a workflow now?"):
            for i, wf_id in enumerate(choices, 1):
                console.print(f"[cyan]{i}.[/cyan] {wf_id}")

            choice = typer.prompt("Enter number", type=int, default=1)
            if 1 <= choice <= len(choices):
                workflow_id = choices[choice - 1]
            else:
                console.print("[red]Invalid selection.[/red]")
                return
        else:
            return

    # Validate workflow exists
    if workflow_id not in available_workflows:
        console.print(f"[red]Workflow '{workflow_id}' not found.[/red]")
        return

    # Load workflow definition
    workflow_path = available_workflows[workflow_id]["path"]
    try:
        with open(workflow_path, "r") as f:
            workflow_def = json.load(f)
    except Exception as e:
        console.print(f"[red]Error loading workflow: {e}[/red]")
        logger.exception(f"Failed to load workflow: {workflow_path}")
        return

    # Execute the workflow with progress indication
    with Live(
        Panel(f"[bold blue]Initializing workflow: {workflow_id}[/bold blue]"),
        refresh_per_second=4,
    ) as live:
        try:
            result = asyncio.run(execute_workflow(workflow_def))

            # Success panel with results
            success_content = (
                f"[green bold]✓ Workflow completed: {workflow_id}[/green bold]\n\n"
            )

            # Extract key results
            if isinstance(result, dict):
                if "playlist_id" in result:
                    success_content += (
                        f"[bold]Playlist ID:[/bold] {result['playlist_id']}\n"
                    )
                elif "destination" in result and isinstance(
                    result["destination"], dict
                ):
                    playlist_id = result["destination"].get("playlist_id")
                    if playlist_id:
                        success_content += f"[bold]Playlist ID:[/bold] {playlist_id}\n"

            live.update(Panel(success_content, border_style="green"))

        except Exception as e:
            live.update(
                Panel(
                    f"[bold red]✗ Workflow failed[/bold red]\n\n{str(e)}",
                    border_style="red",
                )
            )
            logger.exception("Workflow execution failed")
            raise typer.Exit(1)


def dashboard(
    refresh: Annotated[
        int,
        typer.Option(
            "--refresh", "-r", help="Refresh interval in seconds", min=1, max=3600
        ),
    ] = 60,
) -> None:
    """Launch interactive music dashboard."""
    logger.info("Dashboard requested", refresh_interval=refresh)

    console.print(
        Panel(
            f"[bold yellow]The Narada Dashboard is coming soon![/bold yellow]\n\n"
            f"[dim]Auto-refresh interval: {refresh} seconds[/dim]\n\n"
            "This interactive interface will show your:\n"
            "• [cyan]Top artists across platforms[/cyan]\n"
            "• [cyan]Listening history visualizations[/cyan]\n"
            "• [cyan]Smart playlist recommendations[/cyan]",
            title="[bold]Narada Dashboard[/bold]",
            border_style="yellow",
        )
    )

    logger.debug("Dashboard initialized", refresh_interval=refresh)
