"""UI helpers for CLI interaction.

This module provides reusable UI components and helpers for the CLI,
keeping the presentation logic separate from business logic.
"""

from collections.abc import Callable
import functools
import shlex
from typing import Any, ParamSpec, TypeVar

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
import typer

from src.domain.entities import OperationResult
from src.infrastructure.config import get_logger

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


def display_operation_result(
    result: OperationResult,
    title: str | None = None,
    output_format: str = "table",
    next_step_message: str | None = None,
) -> None:
    """Unified display function for all operation results using Rich.

    Leverages Rich (Typer's recommended display library) to provide consistent
    formatting across all operation types. Supports both summary and detailed views.

    Args:
        result: Any OperationResult (WorkflowResult, SyncStats, etc.)
        title: Optional title override
        output_format: "table" or "json" output format
        next_step_message: Optional follow-up message
    """
    if output_format == "json":
        import json

        console.print_json(json.dumps(result.to_dict()))
        return

    # Display title
    display_title = title or result.operation_name or "Operation Results"
    console.print(f"\n[bold blue]{display_title}[/bold blue]")

    # Summary statistics
    summary_data = []

    # Play-based operations show both plays and tracks
    if result.plays_processed > 0:
        summary_data.append(("Plays Processed", str(result.plays_processed)))
        summary_data.append(("Tracks Affected", str(len(result.tracks))))

        # Add play-level metrics
        for metric_name, metric_value in result.play_metrics.items():
            display_name = metric_name.replace("_", " ").title()
            summary_data.append((display_name, str(metric_value)))
    else:
        summary_data.append(("Tracks Processed", str(len(result.tracks))))

    # Add operation-specific summaries using duck typing
    if hasattr(result, "imported") and hasattr(result, "exported"):  # SyncStats
        imported = getattr(result, "imported", 0)
        exported = getattr(result, "exported", 0)
        skipped = getattr(result, "skipped", 0)
        errors = getattr(result, "errors", 0)
        total = getattr(result, "total", 0)

        # Enhanced intelligence reporting
        already_liked = getattr(result, "already_liked", 0)
        candidates = getattr(result, "candidates", 0)

        success_count = imported + exported
        success_rate = (success_count / total * 100) if total > 0 else 0

        # Show intelligence first (most important insight)
        if already_liked > 0:
            efficiency_rate = (already_liked / total * 100) if total > 0 else 0
            summary_data.extend([
                ("Total Tracks", str(total)),
                ("Already Liked ✅", f"{already_liked} ({efficiency_rate:.1f}%)"),
                ("Candidates", str(candidates)),
            ])

        summary_data.extend([
            ("Imported", str(imported)),
            ("Exported", str(exported)),
            ("Skipped", str(skipped)),
            ("Errors", str(errors)),
            ("Success Rate", f"{success_rate:.1f}%"),
        ])

    if result.execution_time > 0:
        summary_data.append(("Duration", f"{result.execution_time:.1f}s"))

    # Create summary table
    summary_table = Table(show_header=False, box=None, padding=(0, 2))
    summary_table.add_column(style="cyan")
    summary_table.add_column(style="green bold")

    for metric, value in summary_data:
        summary_table.add_row(metric, value)

    console.print(summary_table)

    # Track details table if we have tracks
    if result.tracks:
        console.print()
        details_table = Table(title="Track Details")
        details_table.add_column("#", style="dim", justify="right")
        details_table.add_column("Artist", style="cyan")
        details_table.add_column("Track", style="green")

        # Add metric columns
        metric_columns = sorted(result.metrics.keys())
        for metric_name in metric_columns:
            display_name = metric_name.replace("_", " ").title()
            details_table.add_column(display_name, style="yellow")

        # Add track rows
        for i, track in enumerate(result.tracks, 1):
            artist_name = track.artists[0].name if track.artists else "Unknown"
            row = [str(i), artist_name, track.title]

            for metric_name in metric_columns:
                value = result.get_metric(track.id, metric_name, "—")
                if metric_name == "sync_status" and isinstance(value, str):
                    # Add emoji for sync status
                    emoji = {
                        "imported": "✅",
                        "exported": "📤",
                        "skipped": "⚠️",
                        "error": "❌",
                    }.get(value, "❓")
                    row.append(f"{emoji} {value}")
                elif isinstance(value, float):
                    row.append(f"{value:.1f}")
                else:
                    row.append(str(value))

            details_table.add_row(*row)

        console.print(details_table)

    # Next step message
    if next_step_message:
        console.print(f"\n[yellow]{next_step_message}[/yellow]")

    console.print()


# Legacy aliases for existing code - remove after updating all callers
display_sync_stats = display_operation_result
display_workflow_result = display_operation_result


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
