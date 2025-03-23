"""Command registry for Narada CLI."""

from collections.abc import Callable, Sequence
from typing import Any

import typer

# Define service names as constants
SERVICES = ["Spotify", "Last.fm", "MusicBrainz"]

# Track registered commands with rich metadata
# Update the type annotation to properly reflect the structure
REGISTERED_COMMANDS: dict[str, dict[str, str | list[str] | Sequence[str]]] = {}


def register_command(
    app: typer.Typer,
    name: str,
    help_text: str,
    category: str,
    aliases: Sequence[str] | None = None,
    examples: Sequence[str] | None = None,
) -> Callable:
    """Decorator to register a command with rich metadata.

    Args:
        app: Typer app to register with
        name: Command name
        help_text: Help text for command
        category: Command category for grouping in displays
        aliases: Optional alternative names for the command
        examples: Optional usage examples
    """

    def decorator(func: Callable) -> Callable:
        # Register with Typer
        typer_command = app.command(
            name=name,
            help=help_text,
        )(func)

        # Track command metadata
        REGISTERED_COMMANDS[name] = {
            "name": name,
            "help": help_text,
            "category": category,
            "aliases": aliases or [],
            "examples": examples or [],
            "callback": func.__name__,
        }

        return typer_command

    return decorator


def get_registered_commands() -> list[dict[str, Any]]:
    """Get list of all registered commands with metadata."""
    return list(REGISTERED_COMMANDS.values())


def register_all_commands(app: typer.Typer) -> None:
    """Register all commands with the Typer app."""
    from narada.cli.setup_commands import register_setup_commands
    from narada.cli.status_commands import register_status_commands
    from narada.cli.sync_commands import register_sync_commands
    from narada.cli.workflow_commands import register_workflow_commands

    # Register each group of commands
    register_status_commands(app)
    register_setup_commands(app)
    register_workflow_commands(app)
    register_sync_commands(app)
