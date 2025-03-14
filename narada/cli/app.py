"""Narada CLI - Main application entry point and app structure."""

import asyncio
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
import typer

from narada.cli.commands import register_commands
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

# Register commands immediately after app creation
register_commands(app)

# Subcommand groups
app.add_typer(setup_app, name="setup")
app.add_typer(ops_app, name="ops")
app.add_typer(util_app, name="util")


def _display_welcome_banner() -> None:
    """Display an elegant welcome banner using Rich."""
    console.print("\n")
    console.print(
        Text("🎵 NARADA", style="bold rgb(255,140,0)"),
        Text(f" v{VERSION}", style="dim"),
        Text(" - Music Integration Platform", style="rgb(255,165,0)"),
        "\n",
        justify="center",
    )

    # Get commands dynamically from Typer app
    command_groups = {
        "Setup": [],
        "Operations": [],
        "Utilities": [],
    }

    for command in app.registered_commands:
        if command.help and not command.hidden:
            panel = command.rich_help_panel or "Utilities"
            command_groups[panel].append(
                f"• [cyan]narada {command.name}[/cyan] - {command.help}",
            )

    # Build panel content with grouped commands
    panel_content = ["[bold green]Welcome to Narada![/bold green]\n"]
    for group, commands in command_groups.items():
        if commands:
            panel_content.extend([f"\n[yellow]{group}:[/yellow]", *commands])

    panel_content.append(
        "\n[dim]Run any command with --help for more information[/dim]",
    )

    console.print(
        Panel(
            "\n".join(panel_content),
            title="[bold]Getting Started[/bold]",
            border_style="green",
            expand=False,
        ),
    )


@app.callback(invoke_without_command=True)
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

    try:
        # Log startup info - run for all commands
        asyncio.run(log_startup_info())

        # Only show banner for root command (no subcommand) or if command is not found
        if ctx.invoked_subcommand is None or ctx.invoked_subcommand not in [
            cmd.name for cmd in app.registered_commands
        ]:
            _display_welcome_banner()

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
        return app(standalone_mode=False) or 0
    except typer.Exit as e:
        return e.exit_code
    except Exception:
        logger.exception("Unhandled exception")
        return 1
