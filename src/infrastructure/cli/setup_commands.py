"""Setup and configuration commands for Narada CLI."""

import asyncio
from pathlib import Path
from typing import Annotated

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
import typer

from src.infrastructure.cli.ui import command_error_handler
from src.infrastructure.config import get_config, get_logger
from src.infrastructure.persistence.database.db_models import init_db

# Initialize console and logger
console = Console()
logger = get_logger(__name__)


def register_setup_commands(app: typer.Typer) -> None:
    """Register setup commands with the Typer app."""
    app.command(
        name="setup",
        help="Configure your music service connections",
        rich_help_panel="⚙️ System",
    )(setup)
    app.command(
        name="init-db",
        help="Initialize the database schema",
        rich_help_panel="⚙️ System",
    )(initialize_database)


@command_error_handler
def setup(
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Force reconfiguration"),
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
            "\n[yellow]Configuration already exists. Use --force to reconfigure.[/yellow]\n",
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
        ),
    )

    # Configuration metadata for checking
    config_keys = [
        ("Spotify", "Client ID", "SPOTIFY_CLIENT_ID"),
        ("Spotify", "Client Secret", "SPOTIFY_CLIENT_SECRET"),
        ("Last.fm", "API Key", "LASTFM_API_KEY"),
        ("Last.fm", "API Secret", "LASTFM_API_SECRET"),
        ("Last.fm", "Username", "LASTFM_USERNAME"),
    ]

    # Show current configuration
    console.print("\n[bold cyan]Current Configuration:[/bold cyan]")
    config_table = Table(show_header=True)
    config_table.add_column("Service", style="cyan")
    config_table.add_column("Setting", style="green")
    config_table.add_column("Status", style="yellow")

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


@command_error_handler
def initialize_database() -> None:
    """Initialize the database schema based on current models.

    This command creates database tables that don't yet exist.
    Existing tables are left untouched.
    """
    with console.status("[bold blue]Initializing database schema...") as status:
        # Run the initialization
        asyncio.run(init_db())

        # Display success message
        status.update("[bold green]Database initialization complete!")
        console.print(
            "\n[bold green]✓ Database schema initialized successfully[/bold green]",
        )

        # Show next steps
        console.print("\nNext steps:")
        console.print(
            "  • Run [cyan]narada status[/cyan] to check service connections",
        )
        console.print("  • Run [cyan]narada setup[/cyan] to configure API keys")
        console.print("  • Run [cyan]narada workflow[/cyan] to execute a workflow")

        logger.info("Database initialization completed successfully")
