"""UI helpers for CLI interaction.

This module provides reusable UI components and helpers for the CLI,
keeping the presentation logic separate from business logic.
"""

from collections.abc import Callable
import functools
import shlex
from typing import Any, ParamSpec, TypeVar

from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
import typer

from narada.config import get_logger
from narada.core.models import WorkflowResult
from narada.services.like_sync import SyncStats

# Initialize console and logger
console = Console()
logger = get_logger(__name__)

# Type variables for command handler decorator
P = ParamSpec("P")
R = TypeVar("R")


def command_error_handler[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    """Decorator to standardize error handling for CLI commands.

    This decorator wraps a command function to:
    1. Provide consistent error handling using Typer's Exit mechanism
    2. Log errors using Loguru with proper context
    3. Display user-friendly error messages with Rich

    Args:
        func: The command function to wrap

    Returns:
        Wrapped function with integrated error handling
    """

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        # Get operation name from function name for logging context
        operation = func.__name__.replace("_", " ")

        # Execute with logging context
        with logger.contextualize(operation=operation):
            try:
                # Log command execution
                logger.debug(f"Executing {operation}")
                return func(*args, **kwargs)

            except typer.Exit:
                # Let typer.Exit propagate to Typer - it's already being handled
                raise

            except typer.Abort:
                # User initiated abort (e.g., Ctrl+C), log and re-raise
                logger.info(f"Operation {operation} aborted by user")
                raise

            except Exception as e:
                # Log the exception with full traceback
                logger.exception(f"Error during {operation}")

                # Display a clean error message to the user
                console.print(f"\n[bold red]✗ Error during {operation}:[/bold red] {e}")

                # Convert to Typer exit for proper exit code
                raise typer.Exit(code=1) from e

    return wrapper


def display_welcome_banner(
    version: str, commands: list[dict[str, Any]], is_repl: bool = False
) -> None:
    """Display an elegant welcome banner using Rich."""
    console.print("\n")
    console.print(
        Text("🎵 NARADA", style="bold rgb(255,140,0)"),
        Text(f" v{version}", style="dim"),
        Text(" - Music Integration Platform", style="rgb(255,165,0)"),
        "\n",
        justify="center",
    )

    # Group commands by category
    command_groups = {}
    for cmd in commands:
        category = cmd.get("category", "Utilities")
        if category not in command_groups:
            command_groups[category] = []
        command_groups[category].append(cmd)

    # Build panel content with grouped commands
    panel_title = (
        "[bold bright_blue]Interactive Shell[/bold bright_blue]"
        if is_repl
        else "[bold]Getting Started[/bold]"
    )
    panel_content = ["[bold green]Welcome to Narada![/bold green]\n"]

    if is_repl:
        panel_content.append("[dim]Shell commands:[/dim]")
        panel_content.append(
            "[yellow]help[/yellow] or [yellow]?[/yellow] - Show available commands"
        )
        panel_content.append(
            "[yellow]exit[/yellow] or [yellow]quit[/yellow] - Exit the shell"
        )
        panel_content.append("[yellow]<tab>[/yellow] - Press to complete commands")

    # Organize commands by category for better presentation
    for group, cmds in sorted(command_groups.items()):
        if cmds:
            panel_content.append(f"\n[yellow]{group}:[/yellow]")
            for cmd in sorted(cmds, key=lambda c: c["name"]):
                # Add examples if available
                examples = cmd.get("examples", [])
                example_text = f" [dim](e.g. {examples[0]})[/dim]" if examples else ""

                panel_content.append(
                    f"• [cyan]{cmd['name']}[/cyan] - {cmd['help']}{example_text}"
                )

    if not is_repl:
        panel_content.append(
            "\n[dim]Run any command with --help for more information[/dim]",
        )
        panel_content.append(
            "\n[dim]Or use --interactive (-i) flag for interactive shell[/dim]",
        )

    console.print(
        Panel(
            "\n".join(panel_content),
            title=panel_title,
            border_style="green",
            expand=False,
        ),
    )


def display_sync_stats(
    stats: SyncStats,
    title: str,
    next_step_message: str | None = None,
) -> None:
    """Display sync statistics in a formatted table.

    Args:
        stats: The sync statistics to display
        title: The title for the results table
        next_step_message: Optional message to display after results
    """
    console.print()
    table = Table(title=title)
    table.add_column("Metric", style="cyan")
    table.add_column("Count", style="green", justify="right")

    # Add all non-zero stats rows
    if stats.imported > 0:
        table.add_row("Imported", str(stats.imported))
    if stats.exported > 0:
        table.add_row("Exported", str(stats.exported))
    if stats.skipped > 0:
        table.add_row("Skipped", str(stats.skipped))
    if stats.errors > 0:
        table.add_row("Errors", str(stats.errors))
    table.add_row("Total Processed", str(stats.total))

    console.print(table)
    console.print()

    # Show next steps if provided
    if next_step_message and (stats.imported > 0 or stats.exported > 0):
        console.print(next_step_message)
        console.print()


def display_workflow_result(
    result: WorkflowResult,
    output_format: str = "table",
) -> None:
    """Display workflow execution results with associated metrics."""
    logger = get_logger(__name__)

    # Log debugging info instead of printing it
    logger.debug(f"Tracks in result: {len(result.tracks)}")
    logger.debug(f"Metrics in result: {list(result.metrics.keys())}")
    logger.debug(f"Tracks with IDs: {sum(1 for t in result.tracks if t.id)}")

    # Debug metric structure and types
    if "spotify_popularity" in result.metrics:
        sample_keys = list(result.metrics["spotify_popularity"].keys())[:5]
        sample_values = [result.metrics["spotify_popularity"][k] for k in sample_keys]
        logger.debug(
            "Spotify popularity metrics structure",
            key_type=str(type(sample_keys[0])) if sample_keys else "N/A",
            sample_keys=sample_keys,
            sample_values=sample_values,
            int_count=sum(
                1 for k in result.metrics["spotify_popularity"] if isinstance(k, int)
            ),
            str_count=sum(
                1 for k in result.metrics["spotify_popularity"] if isinstance(k, str)
            ),
        )

    if not result.tracks:
        console.print(
            Panel(
                "[yellow]No tracks found in workflow result[/yellow]",
                title="[yellow]Empty Result[/yellow]",
                border_style="yellow",
            )
        )
        return

    # Create table with dynamic columns
    metrics_summary = ", ".join([
        m.replace("_", " ").title() for m in sorted(result.metrics.keys())
    ])

    table = Table(
        title=f"[bold]Workflow: {result.workflow_name}[/bold]",
        caption=f"[dim]Metrics: {metrics_summary}[/dim]",
        highlight=True,
        border_style="bright_blue",
        header_style="bold bright_blue",
        box=None,
    )

    # Standard columns
    table.add_column("#", style="dim", justify="right")
    table.add_column("Artist", style="cyan bold")
    table.add_column("Track", style="green")

    # Add metric columns dynamically
    metric_columns = sorted(result.metrics.keys())
    for metric_name in metric_columns:
        display_name = metric_name.replace("_", " ").title()
        table.add_column(display_name, style="yellow", justify="right")

    # Add rows for each track - show all tracks
    for i, track in enumerate(result.tracks, 1):
        # Get primary artist and track name
        artist_name = track.artists[0].name if track.artists else ""

        # Build row with metrics
        row = [str(i), artist_name, track.title]
        for metric_name in metric_columns:
            # Get the metric value for this track
            value = result.get_metric(track.id, metric_name, default="—")
            # Format the value nicely
            if isinstance(value, (int, float)):
                row.append(f"{value}")
            else:
                row.append(str(value))

        table.add_row(*row)

    # Display in requested format
    if output_format == "json":
        import json

        console.print_json(json.dumps(result.to_dict()))
    else:  # Default to table format
        console.print("\n")

        # Show summary stats first
        panels = [
            Panel(
                f"[bold]{len(result.tracks)}[/bold]",
                title="Total Tracks",
                border_style="green",
            ),
        ]

        # Add metric summary if available
        for metric_name in metric_columns[:2]:  # Limit to first 2 metrics
            if result.metrics.get(metric_name):
                display_name = metric_name.replace("_", " ").title()
                # Try to get average or max value
                values = [
                    v
                    for v in result.metrics[metric_name].values()
                    if isinstance(v, (int, float))
                ]
                if values:
                    avg_value = sum(values) / len(values)
                    max_value = max(values)
                    panels.append(
                        Panel(
                            f"[bold cyan]Avg: {avg_value:.1f}[/bold cyan]\n[dim]Max: {max_value}[/dim]",
                            title=f"{display_name}",
                            border_style="blue",
                        )
                    )

        console.print(Columns(panels, equal=True, expand=True))
        console.print()

        # Show track table
        console.print(table)
        console.print("\n")


def display_error(error: Exception, operation: str) -> None:
    """Display error message with consistent formatting.

    Args:
        error: The exception that occurred
        operation: Description of the operation that failed
    """
    console.print(f"\n[bold red]✗ Error during {operation}:[/bold red] {error}")
    logger.exception(f"Error during {operation}")


def run_interactive_shell(
    app: typer.Typer, version: str, commands: list[dict[str, Any]]
) -> int:
    """Run an interactive REPL for the application."""
    # Import click exceptions here to handle command errors gracefully
    from click.exceptions import (
        BadParameter,
        MissingParameter,
        NoSuchOption,
        UsageError,
    )

    # Display welcome banner
    display_welcome_banner(version, commands, is_repl=True)

    # REPL loop
    running = True
    while running:
        try:
            # Prompt for command with modern style
            console.print(
                "\n[bold bright_blue]>[/bold bright_blue] [bold green]narada[/bold green][dim]:[/dim] ",
                end="",
            )
            command_str = input()

            # Skip empty commands
            if not command_str.strip():
                continue

            # Handle special commands
            if command_str.lower() in ("exit", "quit"):
                console.print("[yellow]Exiting Narada shell...[/yellow]")
                running = False
                continue

            if command_str.lower() in ("help", "?"):
                display_welcome_banner(version, commands, is_repl=True)
                continue

            # Parse the command into args, handling quotes correctly
            try:
                args = shlex.split(command_str)
            except ValueError as e:
                console.print(f"[red]Error parsing command:[/red] {e}")
                continue

            # Strip "narada" prefix if the user included it
            if args and args[0].lower() == "narada":
                args = args[1:]

            if not args:
                continue

            # Execute the command (synchronously)
            try:
                app(args, standalone_mode=False)
            except (BadParameter, MissingParameter, NoSuchOption) as e:
                # Handle parameter errors gracefully
                console.print(f"[yellow]Command parameter error: {e}[/yellow]")
                console.print(f"[dim]Try '{args[0]} --help' for more information[/dim]")
            except UsageError as e:
                # Handle unknown commands and usage errors gracefully
                if "No such command" in str(e):
                    cmd_name = str(e).split("'")[1] if "'" in str(e) else "unknown"
                    console.print(
                        f"[yellow]Unknown command: [bold]{cmd_name}[/bold][/yellow]"
                    )

                    # Get command suggestions
                    suggestions = get_command_suggestions(cmd_name, commands)
                    if suggestions:
                        console.print("[dim]Did you mean:[/dim]")
                        for suggestion in suggestions[:3]:  # Limit to top 3 suggestions
                            console.print(f"  [cyan]{suggestion}[/cyan]")

                    console.print("[dim]Type 'help' to see available commands[/dim]")
                else:
                    console.print(f"[yellow]Usage error: {e}[/yellow]")
            except typer.Exit as e:
                if e.exit_code != 0:
                    console.print(
                        f"[yellow]Command exited with code {e.exit_code}[/yellow]"
                    )
            except typer.Abort:
                console.print("[yellow]Command aborted[/yellow]")
            except Exception as e:
                # Only log the exception, show a clean error to the user
                logger.exception(f"Error during command execution: {command_str}")
                console.print(f"[red]Error: {e!s}[/red]")

        except KeyboardInterrupt:
            console.print(
                "\n[yellow]Command interrupted. Press Ctrl+D to exit.[/yellow]"
            )
        except EOFError:
            console.print("\n[yellow]Exiting Narada shell...[/yellow]")
            running = False

    return 0


def get_command_suggestions(
    input_cmd: str, commands: list[dict[str, str]]
) -> list[str]:
    """Get command suggestions based on partial input.

    Uses fuzzy matching to suggest commands that are similar to what was typed.

    Args:
        input_cmd: Partial command that was typed
        commands: List of available commands

    Returns:
        List of suggested command names
    """
    if not input_cmd:
        return []

    # Simple fuzzy matching - could be enhanced with a proper fuzzy search library
    input_lower = input_cmd.lower()

    # Check for exact matches first
    exact_matches = [
        cmd["name"] for cmd in commands if cmd["name"].lower() == input_lower
    ]
    if exact_matches:
        return exact_matches

    # Then check for commands that start with the input
    prefix_matches = [
        cmd["name"] for cmd in commands if cmd["name"].lower().startswith(input_lower)
    ]
    if prefix_matches:
        return prefix_matches

    # Then check for commands that contain the input
    return [cmd["name"] for cmd in commands if input_lower in cmd["name"].lower()]
