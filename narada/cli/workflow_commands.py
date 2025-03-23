"""Workflow commands for Narada CLI."""

import asyncio
import json
from pathlib import Path
from typing import Annotated, Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
import typer

from narada.cli.command_registry import register_command
from narada.cli.ui import display_error, display_workflow_result
from narada.config import get_config, get_logger
from narada.workflows.prefect import (
    register_progress_callback,
    run_workflow as execute_workflow,
)

# Initialize console and logger
console = Console()
logger = get_logger(__name__)


def register_workflow_commands(app: typer.Typer) -> None:
    """Register workflow commands with the Typer app."""
    register_command(
        app=app,
        name="workflow",
        help_text="Run a workflow from available definitions",
        category="Operations",
        examples=[
            "workflow",
            "workflow spotify-to-lastfm",
            "workflow --no-results my-workflow",
        ],
    )(run_workflow)


def initialize_workflow_system() -> tuple[bool, str]:
    """Initialize and validate workflow nodes during app startup."""
    try:
        # Import workflow package which triggers node registration
        from narada.workflows import validate_registry

        # Run validation and return result
        return validate_registry()
    except Exception as e:
        logger.exception("Workflow system initialization failed")
        return False, f"Workflow initialization failed: {e!s}"


def workflow_progress_callback(event_type: str, event_data: dict[str, Any]) -> None:
    """Progress callback for workflow execution."""
    match event_type:
        case "task_started":
            task_name = event_data.get("task_name", "Unknown task")
            task_type = event_data.get("task_type", "")
            console.print(
                f"[bright_blue]⚙ Starting:[/bright_blue] [bold]{task_name}[/bold] [dim]({task_type})[/dim]"
            )

        case "task_completed":
            task_name = event_data.get("task_name", "Unknown")
            task_type = event_data.get("task_type", "")

            # Add track count display when result contains a tracklist
            result = event_data.get("result", {})
            if isinstance(result, dict) and "tracklist" in result:
                tracklist = result["tracklist"]
                track_count = len(tracklist.tracks)

                # Display track count with task info and a hint of animation using unicode chars
                console.print(
                    Panel.fit(
                        f"[bold green]{task_name}[/bold green]\n"
                        f"[dim]Type: {task_type}[/dim]\n"
                        f"[cyan]Produced: [bold]{track_count} tracks[/bold][/cyan]",
                        border_style="green",
                        title="[green]✓ Task Completed[/green]",
                        title_align="left",
                        padding=(0, 2),
                    )
                )
            else:
                console.print(
                    f"[green]✓ Completed:[/green] [bold]{task_name}[/bold] [dim]({task_type})[/dim]",
                )

        case "workflow_started":
            workflow_name = event_data.get("workflow_name", "Unknown workflow")
            console.print(
                f"[bold blue]▶ Starting workflow:[/bold blue] [bold]{workflow_name}[/bold]"
            )

        case "workflow_completed":
            workflow_name = event_data.get("workflow_name", "Unknown workflow")
            console.print(
                f"[bold green]✓ Workflow completed:[/bold green] [bold]{workflow_name}[/bold]"
            )

        case _:
            # Handle any other event types
            logger.debug(f"Unhandled event type: {event_type}", event_data=event_data)


async def list_workflows() -> list[dict[str, Any]]:  # noqa: RUF029
    """Get available workflows."""
    # Get workflow definitions directory with fallback
    workflows_dir = Path(get_config("WORKFLOWS_DIR", "narada/workflows/definitions"))

    # Ensure directory exists
    if not workflows_dir.exists():
        workflows_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created workflows directory: {workflows_dir}")

    # Discover available workflows
    available_workflows = []
    for file_path in workflows_dir.glob("*.json"):
        try:
            with open(file_path) as f:  # noqa: ASYNC230
                workflow_def = json.load(f)
                wf_id = workflow_def.get("id")
                if wf_id:
                    available_workflows.append({
                        "id": wf_id,
                        "name": workflow_def.get("name", wf_id),
                        "description": workflow_def.get("description", ""),
                        "path": str(file_path),
                        "task_count": len(workflow_def.get("tasks", [])),
                    })
        except Exception as e:
            logger.warning(f"Error loading workflow from {file_path}: {e}")

    return sorted(available_workflows, key=lambda wf: wf["id"])


async def run_workflow_async(
    workflow_id: str | None,
    show_results: bool = True,
    output_format: str = "table",
) -> int:
    """Async implementation of workflow execution."""
    # Get available workflows
    workflows = await list_workflows()

    # Show workflow list if none specified
    if not workflow_id:
        if not workflows:
            console.print("[red]No workflows found in definitions directory.[/red]")
            console.print(
                "[yellow]Add workflow JSON files to the workflows directory[/yellow]",
            )
            return 1

        # Display workflow table with numbers for selection
        table = Table(title="Available Workflows")
        table.add_column("#", style="bold cyan", justify="right")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Description", style="dim")

        for i, wf in enumerate(workflows, 1):
            table.add_row(str(i), wf["id"], wf["name"], wf["description"])

        console.print(table)
        console.print(
            "\n[dim]Enter a number to run a workflow, or 'back' to return to main menu[/dim]"
        )

        # Interactive selection without confirmation
        try:
            choice_input = typer.prompt("Select workflow", default="").strip().lower()

            # Handle special commands
            if choice_input in ("", "back", "exit", "quit", "cancel"):
                return 0

            # Parse as number
            try:
                choice = int(choice_input)
                if 1 <= choice <= len(workflows):
                    workflow_id = workflows[choice - 1]["id"]
                else:
                    console.print("[red]Invalid selection number.[/red]")
                    return 1
            except ValueError:
                # Try matching by ID
                matching_workflow = next(
                    (wf for wf in workflows if wf["id"].lower() == choice_input), None
                )
                if matching_workflow:
                    workflow_id = matching_workflow["id"]
                else:
                    console.print(
                        "[red]Invalid selection. Enter a number or workflow ID.[/red]"
                    )
                    return 1
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Workflow selection cancelled.[/yellow]")
            return 0

    # Validate workflow exists
    workflow_info = next((wf for wf in workflows if wf["id"] == workflow_id), None)
    if not workflow_info:
        console.print(f"[red]Workflow '{workflow_id}' not found.[/red]")
        return 1

    # Initialize node system
    with console.status("[bold blue]Initializing node system..."):
        success, message = initialize_workflow_system()

    if not success:
        console.print(f"[bold red]✗ {message}[/bold red]")
        logger.error(f"Node initialization failed: {message}")
        return 1

    console.print(f"[bold green]✓ {message}[/bold green]")
    logger.info(f"Node initialization successful: {message}")

    # Display workflow starting panel
    console.print(
        Panel.fit(
            f"[bold]{workflow_info['name']}[/bold]\n"
            f"[dim]{workflow_info['description']}[/dim]\n"
            f"[cyan]Tasks: [bold]{workflow_info.get('task_count', 0)}[/bold][/cyan]",
            title="[bold bright_blue]⚡ Starting Workflow[/bold bright_blue]",
            border_style="blue",
            padding=(0, 2),
        )
    )
    console.print()

    # Create a custom progress display
    with Progress(
        SpinnerColumn("dots2"),  # More modern spinner
        TextColumn("[bold bright_blue]{task.description}[/bold bright_blue]"),
        BarColumn(bar_width=None, complete_style="bright_blue"),
        TimeElapsedColumn(),
        console=console,
        expand=True,
        transient=False,  # Keep progress history visible
    ) as progress:
        # Set up progress tracking tasks
        progress_task = progress.add_task(
            f"[bold]Running workflow: {workflow_info['name']}",
            total=workflow_info.get("task_count", 1),
        )

        # Register progress callback
        register_progress_callback(workflow_progress_callback)

        try:
            # Load workflow definition
            with open(workflow_info["path"]) as f:  # noqa: ASYNC230
                workflow_def = json.load(f)

            # Execute workflow
            _, result = await execute_workflow(workflow_def)

            # Complete progress bar
            progress.update(
                progress_task, completed=progress.tasks[progress_task].total
            )

            # Display success and results
            console.print()
            console.print(
                Panel.fit(
                    f"[bold green]{workflow_info['name']}[/bold green]\n"
                    f"[dim]{workflow_info['description']}[/dim]\n"
                    f"[cyan]Processed [bold]{len(result.tracks) if result and hasattr(result, 'tracks') else 0}[/bold] tracks[/cyan]",
                    title="[bold green]✓ Workflow Completed[/bold green]",
                    border_style="green",
                    padding=(0, 2),
                )
            )

            # Display metrics visualization if requested
            if show_results and result:
                display_workflow_result(result, output_format)

            return 0
        except Exception as e:
            console.print()
            console.print("[bold red]✗ Workflow failed[/bold red]")
            console.print(f"[red]Error: {e}[/red]")
            logger.exception("Workflow execution failed")
            return 1


def run_workflow(
    workflow_id: Annotated[
        str | None,
        typer.Argument(help="Workflow ID to execute"),
    ] = None,
    show_results: Annotated[
        bool,
        typer.Option("--show-results/--no-results", help="Show result metrics"),
    ] = True,
    output_format: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format (table, json)"),
    ] = "table",
) -> None:
    """Run a workflow from available definitions."""
    try:
        exit_code = asyncio.run(
            run_workflow_async(workflow_id, show_results, output_format)
        )
        if exit_code != 0:
            raise typer.Exit(exit_code)
    except Exception as e:
        display_error(e, "workflow execution")
        raise typer.Exit(1) from e
