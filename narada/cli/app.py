"""Narada CLI - Main application entry point and app structure."""

import asyncio
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

from rich.console import Console
import typer

from narada.cli.command_registry import register_all_commands
from narada.cli.ui import display_welcome_banner, run_interactive_shell
from narada.config import get_logger, log_startup_info, setup_loguru_logger

VERSION = version("narada")

# Initialize console and logger
console = Console()
logger = get_logger(__name__)

# Initialize main app with subcommands
app = typer.Typer(
    help="Narada - Your personal music integration platform",
    no_args_is_help=True,
    rich_markup_mode="rich",
    add_completion=False,
)

# Define command groups
setup_app = typer.Typer(
    help="Configure API keys and service connections",
    rich_help_panel="Setup",
)
ops_app = typer.Typer(
    help="Manage playlists and track operations",
    rich_help_panel="Operations",
)
util_app = typer.Typer(
    help="View status and perform maintenance",
    rich_help_panel="Utilities",
)

# Register all commands to main app
register_all_commands(app)

# Subcommand groups - add after registering main commands
app.add_typer(setup_app, name="setup")
app.add_typer(ops_app, name="ops")
app.add_typer(util_app, name="util")


def get_commands_for_display() -> list[dict[str, str]]:
    """Extract commands from the Typer app for display purposes."""
    # The core issue is we need to register commands before the CLI is fully initialized
    # Here we register our commands directly to show in welcome banner
    commands = [
        {
            "name": "status",
            "help": "Check connection status of music services",
            "category": "Utilities",
        },
        {
            "name": "setup",
            "help": "Configure your music service connections",
            "category": "Setup",
        },
        {
            "name": "init-db",
            "help": "Initialize the database schema",
            "category": "Setup",
        },
        {
            "name": "workflow",
            "help": "Run a workflow from available definitions",
            "category": "Operations",
        },
        {
            "name": "import-spotify-likes",
            "help": "Import liked tracks from Spotify",
            "category": "Operations",
        },
        {
            "name": "export-likes-to-lastfm",
            "help": "Export liked tracks to Last.fm",
            "category": "Operations",
        },
    ]

    return commands


@app.callback(invoke_without_command=True)
def init_cli(
    ctx: typer.Context,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable verbose output"),
    ] = False,
    interactive: Annotated[
        bool,
        typer.Option("--interactive", "-i", help="Run in interactive REPL mode"),
    ] = False,
) -> None:
    """Initialize Narada CLI."""
    # Store verbosity in context for subcommands
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["interactive"] = interactive

    # Setup logging first
    setup_loguru_logger(verbose)

    # Create data directory
    Path("data").mkdir(exist_ok=True)

    try:
        # Log startup info - run for all commands
        asyncio.run(log_startup_info())

        if interactive:
            # Don't show banner yet, the REPL will handle it
            return

        # Only show banner for root command (no subcommand) or if command is not found
        if ctx.invoked_subcommand is None or ctx.invoked_subcommand not in [
            cmd.name for cmd in app.registered_commands
        ]:
            display_welcome_banner(VERSION, get_commands_for_display())

            # If a command was attempted but not found, show friendly error message
            if ctx.args and ctx.args[0] not in [
                cmd.name for cmd in app.registered_commands
            ]:
                console.print(
                    f"\n[yellow]Error: No such command '[bold]{ctx.args[0]}[/bold]'.[/yellow]",
                )
                console.print("[yellow]See the available commands above.[/yellow]\n")
    except Exception as err:
        logger.exception("Error during startup")
        raise typer.Exit(1) from err


def main() -> int:
    """Application entry point."""
    try:
        # Check for interactive mode flag
        import sys

        interactive_mode = "-i" in sys.argv or "--interactive" in sys.argv

        if interactive_mode:
            # Remove the interactive flag before passing to typer
            if "-i" in sys.argv:
                sys.argv.remove("-i")
            if "--interactive" in sys.argv:
                sys.argv.remove("--interactive")

            # Setup basics
            setup_loguru_logger(verbose=False)
            Path("data").mkdir(exist_ok=True)
            asyncio.run(log_startup_info())

            # Run interactive shell with our known commands
            command_list = get_commands_for_display()
            return run_interactive_shell(app, VERSION, command_list)
        else:
            # Run in normal command mode
            return app(standalone_mode=False) or 0
    except typer.Exit as e:
        return e.exit_code
    except Exception:
        logger.exception("Unhandled exception")
        return 1
