"""Narada CLI - Main application entry point."""

from importlib.metadata import version

import typer
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from typing_extensions import Annotated

from narada.cli.commands import register_commands
from narada.config import get_logger, log_startup_info, setup_loguru_logger

VERSION = version("narada")

# Initialize console and logger
console = Console()
logger = get_logger(__name__)

# Define command groups
setup_app = typer.Typer(
    help="Configure API keys and service connections", rich_help_panel="Setup"
)

ops_app = typer.Typer(
    help="Manage playlists and track operations", rich_help_panel="Operations"
)

util_app = typer.Typer(
    help="View status and perform maintenance", rich_help_panel="Utilities"
)
# Initialize main app with subcommands
app = typer.Typer(
    help="Narada - Your personal music integration platform",
    no_args_is_help=True,
    rich_markup_mode="rich",
    add_completion=False,
)

# Register commands immediately after app creation
register_commands(app)


# Subcommand groups
app.add_typer(setup_app, name="setup")
app.add_typer(ops_app, name="ops")
app.add_typer(util_app, name="util")


def update_operation_progress(value: int) -> None:
    """Global progress callback for long-running operations."""
    # Use Typer's progress bar instead of custom printing
    if hasattr(update_operation_progress, "progress"):
        progress = update_operation_progress.progress
        progress.update(update_operation_progress.task_id, completed=value)


@app.callback(invoke_without_command=True)
def init_cli(
    ctx: typer.Context,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Enable verbose output")
    ] = False,
) -> None:
    """Initialize Narada CLI."""
    # Store verbosity in context for subcommands
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose

    # Setup logging first
    setup_loguru_logger(verbose)

    # Create data directory
    from pathlib import Path

    Path("data").mkdir(exist_ok=True)

    # Only show banner for root command (no subcommand)
    if ctx.invoked_subcommand is None:
        import asyncio

        try:
            # Log startup info
            asyncio.run(log_startup_info())
            _display_welcome_banner()
        except Exception:
            logger.exception("Error during startup")
            raise typer.Exit(1)


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
                f"• [cyan]narada {command.name}[/cyan] - {command.help}"
            )

    # Build panel content with grouped commands
    panel_content = ["[bold green]Welcome to Narada![/bold green]\n"]
    for group, commands in command_groups.items():
        if commands:
            panel_content.extend([f"\n[yellow]{group}:[/yellow]", *commands])

    panel_content.append(
        "\n[dim]Run any command with --help for more information[/dim]"
    )

    console.print(
        Panel(
            "\n".join(panel_content),
            title="[bold]Getting Started[/bold]",
            border_style="green",
            expand=False,
        )
    )


def main() -> int:
    """Application entry point."""
    try:
        return app(standalone_mode=False) or 0
    except typer.Exit as e:
        return e.exit_code
    except Exception:
        logger.exception("Unhandled exception")
        return 1
