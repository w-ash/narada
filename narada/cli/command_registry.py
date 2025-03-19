"""Command registry for Narada CLI.

This module provides a central place to register commands
with the CLI app, making it easy to organize commands into
separate modules without losing track of them.
"""

import typer

# Define service names as constants
SERVICES = ["Spotify", "Last.fm", "MusicBrainz"]


def register_all_commands(app: typer.Typer) -> None:
    """Register all commands with the Typer app.

    This is the main entry point for commands registration,
    importing each command group and registering its commands.

    Args:
        app: The Typer app to register commands with
    """
    from narada.cli.setup_commands import register_setup_commands
    from narada.cli.status_commands import register_status_commands
    from narada.cli.sync_commands import register_sync_commands
    from narada.cli.workflow_commands import register_workflow_commands

    # Register each group of commands
    register_status_commands(app)
    register_setup_commands(app)
    register_workflow_commands(app)
    register_sync_commands(app)
