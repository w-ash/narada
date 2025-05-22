"""Command registry for Narada CLI.

This module manages the registration and tracking of CLI commands with their
metadata. It provides a centralized way to register commands with additional
information like descriptions, categories, and examples.
"""

from collections.abc import Callable, Sequence
from typing import Any

import typer

# Define service names as constants
SERVICES = ["Spotify", "Last.fm", "MusicBrainz"]

# Command metadata dict to track richer information than Typer provides
COMMAND_METADATA: dict[str, dict[str, Any]] = {}


def register_command(
    app: typer.Typer,
    name: str,
    help_text: str,
    category: str,
    examples: Sequence[str] | None = None,
) -> Callable:
    """Decorator to register a command with rich metadata.

    Args:
        app: Typer app to register with
        name: Command name
        help_text: Help text for command
        category: Command category for grouping in displays
        examples: Optional usage examples
    """

    def decorator(func: Callable) -> Callable:
        # Register with Typer
        typer_command = app.command(
            name=name,
            help=help_text,
        )(func)

        # Track command metadata
        COMMAND_METADATA[name] = {
            "name": name,
            "help": help_text,
            "category": category,
            "examples": examples or [],
            "callback": func.__name__,
        }

        return typer_command

    return decorator


def get_all_commands(app: typer.Typer) -> list[dict[str, Any]]:
    """Get list of all commands with metadata.

    This function combines Typer's command info with our richer metadata.
    """
    commands = []

    # Get all commands registered with Typer
    for command in app.registered_commands:
        command_name = command.name

        # Start with Typer's basic info
        command_info = {
            "name": command_name,
            "help": command.help or "",
            "category": "Utilities",  # Default category
        }

        # Enhance with our richer metadata if available
        if command_name in COMMAND_METADATA:
            command_info.update(COMMAND_METADATA[command_name])

        commands.append(command_info)

    return commands


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
