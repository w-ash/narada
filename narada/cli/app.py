"""Narada CLI - Main application entry point and app structure."""

import asyncio
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

from rich.console import Console
import typer

from narada.cli.command_registry import get_all_commands, register_all_commands
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
    add_completion=True,
    # Configure Typer's exception handling
    pretty_exceptions_enable=True,
    pretty_exceptions_short=True,
    pretty_exceptions_show_locals=False,  # Don't show local variables for security
)

# Register all commands to main app
register_all_commands(app)


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

        # Only show banner for root command (no subcommand)
        if ctx.invoked_subcommand is None:
            display_welcome_banner(VERSION, get_all_commands(app))
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

            # Run interactive shell with commands from Typer app
            return run_interactive_shell(app, VERSION, get_all_commands(app))
        else:
            # Let Typer handle command execution
            return app() or 0
    except Exception:
        logger.exception("Unhandled exception")
        return 1
