"""Narada CLI - Main application entry point and app structure."""

from importlib.metadata import version
from pathlib import Path
from typing import Annotated

from rich.console import Console
import typer

from src.config import get_logger, setup_loguru_logger
from src.infrastructure.cli import data_commands, workflows_commands
from src.infrastructure.cli.setup_commands import register_setup_commands
from src.infrastructure.cli.status_commands import register_status_commands
from src.infrastructure.cli.workflows_commands import list_workflows

VERSION = version("narada")

# Initialize console and logger with reasonable width
console = Console(width=80)
logger = get_logger(__name__)

# Initialize main app with modern configuration
app = typer.Typer(
    help=f"🎵 Narada v{VERSION} - Your personal music integration platform",
    no_args_is_help=True,  # Show help when no command provided
    rich_markup_mode="rich",
    add_completion=False,  # Disable completion - too finicky for development tool
    pretty_exceptions_enable=True,
    pretty_exceptions_short=True,
    pretty_exceptions_show_locals=False,
)

# Add unified playlist command
app.add_typer(
    workflows_commands.app,
    name="playlist",
    help="Create and manage playlists",
    rich_help_panel="🔧 Playlist Workflow Management",
)

# Register individual utility commands
register_status_commands(app)
register_setup_commands(app)

# Add unified data command
app.add_typer(
    data_commands.app,
    name="data",
    help="Manage your music data",
    rich_help_panel="📊 Data Sync",
)


# Register individual workflow commands for direct access
def register_workflow_commands() -> None:
    """Register individual workflow commands at the top level for direct access."""
    try:
        workflows = list_workflows()
        for workflow in workflows:
            workflow_id = workflow["id"]
            workflow_name = workflow["name"]

            # Create a command function for this workflow
            def create_workflow_command(wf_id: str, wf_name: str) -> None:
                """Create a command function for a specific workflow."""

                @app.command(
                    name=wf_id,
                    help=f"Run {wf_name} workflow",
                    rich_help_panel="🎵 Playlist Workflows",
                )
                def workflow_command(  # pyright: ignore[reportUnusedFunction]
                    show_results: Annotated[
                        bool,
                        typer.Option(
                            "--show-results/--no-results", help="Show result metrics"
                        ),
                    ] = True,
                    output_format: Annotated[
                        str,
                        typer.Option(
                            "--format", "-f", help="Output format (table, json)"
                        ),
                    ] = "table",
                ) -> None:
                    """Run workflow."""
                    # Import here to avoid circular imports
                    from src.infrastructure.cli.workflows_commands import (
                        _run_workflow_interactive,
                    )

                    _run_workflow_interactive(wf_id, show_results, output_format)

            create_workflow_command(workflow_id, workflow_name)

    except Exception as e:
        # If workflow registration fails, log but don't crash the CLI
        logger.debug(f"Failed to register workflow commands: {e}")


# Register workflow commands at import time
register_workflow_commands()


@app.command(name="version", rich_help_panel="⚙️ System")
def version_command() -> None:
    """Show version information."""
    console.print(
        f"[bold bright_blue]🎵 Narada[/bold bright_blue] [dim]v{VERSION}[/dim]"
    )


# No longer registering duplicate workflow commands - use unified 'playlist' command


@app.callback()
def init_cli(
    ctx: typer.Context,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable verbose output"),
    ] = False,
) -> None:
    """Initialize Narada CLI."""
    # Store verbosity in context for subcommands
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose

    # Setup logging first
    setup_loguru_logger(verbose)

    # Create data directory
    Path("data").mkdir(exist_ok=True)


def main() -> int:
    """Application entry point."""
    try:
        # Let Typer handle command execution
        return app() or 0
    except Exception:
        logger.exception("Unhandled exception")
        return 1
