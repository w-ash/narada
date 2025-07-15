"""Narada CLI - Main application entry point and app structure."""

from importlib.metadata import version
from pathlib import Path
from typing import Annotated

from rich.console import Console
import typer

from src.infrastructure.cli import likes_commands, plays_commands, workflows_commands
from src.infrastructure.cli.setup_commands import register_setup_commands
from src.infrastructure.cli.status_commands import register_status_commands
from src.infrastructure.cli.workflows_commands import list_workflows
from src.infrastructure.config import get_logger, setup_loguru_logger

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

# Add workflow management commands
app.add_typer(
    workflows_commands.app,
    name="workflows",
    help="Run workflows for playlist generation (list, run)",
    rich_help_panel="🔧 Playlist Workflow Management",
)

# Add workflow alias (simple duplicate registration since Typer lacks native aliases)
app.add_typer(
    workflows_commands.app, name="wf", help="Short alias for workflows", hidden=True
)

# Register individual utility commands
register_status_commands(app)
register_setup_commands(app)

# Add clean import command structure using subcommands
app.add_typer(
    plays_commands.app,
    name="import",
    help="Import play history from various sources",
    rich_help_panel="📊 Data Import",
)

# Add likes commands (keeping for now)
app.add_typer(
    likes_commands.app,
    name="likes",
    help="Manage liked tracks",
    rich_help_panel="📊 Data Sync",
)


def register_workflow_commands(app: typer.Typer) -> None:
    """Dynamically register workflow commands as top-level commands."""
    try:
        workflows = list_workflows()
        logger.info(f"Registering {len(workflows)} workflow commands")

        for workflow in workflows:
            workflow_id = workflow["id"]
            workflow_name = workflow["name"]

            # Create workflow runner function with closure
            def create_workflow_runner(wf_id: str):
                def workflow_command() -> None:
                    from src.infrastructure.cli.workflows_commands import (
                        _run_workflow_interactive,
                    )

                    _run_workflow_interactive(wf_id, True, "table")

                return workflow_command

            # Register with rich help text
            app.command(
                name=workflow_id,
                help=f"🎵 {workflow_name}",
                rich_help_panel="🎵 Playlist Workflows",
            )(create_workflow_runner(workflow_id))

        logger.debug(f"Successfully registered {len(workflows)} workflow commands")

    except Exception as e:
        # Fail gracefully if workflows can't be loaded
        logger.warning(
            "Failed to load workflows for dynamic registration",
            error=str(e),
            exc_info=True,
        )


@app.command(name="version", rich_help_panel="⚙️ System")
def version_command() -> None:
    """Show version information."""
    console.print(
        f"[bold bright_blue]🎵 Narada[/bold bright_blue] [dim]v{VERSION}[/dim]"
    )


# Register workflow commands at import time for help system
register_workflow_commands(app)


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
