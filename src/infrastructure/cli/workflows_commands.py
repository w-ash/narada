"""Workflow commands for Narada CLI."""

import json
from pathlib import Path
from typing import Annotated

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
import typer

from src.application.workflows.prefect import run_workflow as execute_workflow
from src.infrastructure.cli.async_helpers import interactive_async_operation
from src.infrastructure.cli.completions import complete_workflow_names
from src.infrastructure.cli.ui import display_operation_result

# Create workflows subcommand app
app = typer.Typer(help="Run workflows for playlist generation")
console = Console()


@app.command()
def run(
    workflow_id: Annotated[
        str | None,
        typer.Argument(
            help="Workflow ID to execute", autocompletion=complete_workflow_names
        ),
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
    _run_workflow_interactive(workflow_id, show_results, output_format)


@app.command()
def list() -> None:
    """List available workflows."""
    _list_workflows()


@interactive_async_operation()
async def _run_workflow_interactive(
    workflow_id: str | None,
    show_results: bool,
    output_format: str,
) -> None:
    """Run workflow with interactive selection if needed."""

    # Get available workflows
    workflows = list_workflows()

    # Show workflow list if none specified
    if not workflow_id:
        if not workflows:
            console.print("[red]No workflows found in definitions directory.[/red]")
            raise typer.Exit(1)

        # Display workflow table
        table = Table(title="Available Workflows")
        table.add_column("#", style="bold cyan", justify="right")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Description", style="dim")

        for i, wf in enumerate(workflows, 1):
            table.add_row(str(i), wf["id"], wf["name"], wf["description"])

        console.print(table)

        # Interactive selection
        choice_input = Prompt.ask("Select workflow number or ID", default="").strip()

        if choice_input in ("", "back", "exit", "quit", "cancel"):
            return

        # Parse selection
        try:
            choice = int(choice_input)
            if 1 <= choice <= len(workflows):
                workflow_id = workflows[choice - 1]["id"]
            else:
                console.print("[red]Invalid selection number.[/red]")
                raise typer.Exit(1)
        except ValueError:
            # Try matching by ID
            matching_workflow = next(
                (wf for wf in workflows if wf["id"].lower() == choice_input.lower()),
                None,
            )
            if matching_workflow:
                workflow_id = matching_workflow["id"]
            else:
                console.print("[red]Invalid selection.[/red]")
                raise typer.Exit(1) from None

    # Validate workflow exists
    workflow_info = next((wf for wf in workflows if wf["id"] == workflow_id), None)
    if not workflow_info:
        console.print(f"[red]Workflow '{workflow_id}' not found.[/red]")
        raise typer.Exit(1)

    # Initialize workflow system
    with console.status("[bold blue]Initializing workflow system..."):
        success, message = initialize_workflow_system()

    if not success:
        console.print(f"[bold red]✗ {message}[/bold red]")
        raise typer.Exit(1)

    console.print(f"[bold green]✓ {message}[/bold green]")

    # Display workflow info
    console.print(
        Panel.fit(
            f"[bold]{workflow_info['name']}[/bold]\n"
            f"[dim]{workflow_info['description']}[/dim]\n"
            f"[cyan]Tasks: [bold]{workflow_info.get('task_count', 0)}[/bold][/cyan]",
            title="[bold bright_blue]⚡ Starting Workflow[/bold bright_blue]",
            border_style="blue",
        )
    )

    # Register simple progress callback for CLI feedback
    from src.application.workflows.prefect import register_simple_progress_callback

    register_simple_progress_callback(_simple_workflow_feedback)

    try:
        # Load and execute workflow
        workflow_path = Path(workflow_info["path"])
        workflow_def = json.loads(workflow_path.read_text())

        _, result = await execute_workflow(workflow_def)

        # Display results
        console.print(
            Panel.fit(
                f"[bold green]{workflow_info['name']}[/bold green]\n"
                f"[cyan]Processed [bold]{len(result.tracks) if result and hasattr(result, 'tracks') else 0}[/bold] tracks[/cyan]",
                title="[bold green]✓ Workflow Completed[/bold green]",
                border_style="green",
            )
        )

        if show_results and result:
            display_operation_result(result, output_format=output_format)

    except Exception as e:
        console.print("[bold red]✗ Workflow failed[/bold red]")
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e


def _list_workflows() -> None:
    """Display available workflows."""
    workflows = list_workflows()

    if not workflows:
        console.print("[red]No workflows found.[/red]")
        return

    table = Table(title="Available Workflows")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Description", style="dim")
    table.add_column("Tasks", style="yellow", justify="right")

    for wf in workflows:
        table.add_row(wf["id"], wf["name"], wf["description"], str(wf["task_count"]))

    console.print(table)


def _simple_workflow_feedback(event_type: str, event_data: dict) -> None:
    """Simple CLI feedback for workflow progress without visual clutter."""
    match event_type:
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

        case "task_started":
            task_name = event_data.get("task_name", "Unknown task")
            task_type = event_data.get("task_type", "")
            emoji = _get_task_emoji(task_type)
            console.print(f"[cyan]{emoji} {task_name}[/cyan]")

        case "task_completed":
            task_name = event_data.get("task_name", "Unknown")
            result = event_data.get("result", {})
            summary = _get_completion_summary(result)
            console.print(f"[green]✓ {task_name}[/green] {summary}")


def _get_task_emoji(task_type: str) -> str:
    """Get emoji for task type."""
    emoji_map = {
        "source.spotify_playlist": "📥",
        "enricher.lastfm": "🎵",
        "sorter.by_metric": "🔄",
        "destination.create_spotify_playlist": "📤",
        "filter": "🔍",
        "combiner": "🔗",
        "selector": "✂️",
    }
    return emoji_map.get(task_type.split(".")[0], "⚙")


def _get_completion_summary(result: dict) -> str:
    """Generate completion summary from task result."""
    if not isinstance(result, dict):
        return ""

    if "tracklist" in result:
        track_count = (
            len(result["tracklist"].tracks)
            if hasattr(result["tracklist"], "tracks")
            else 0
        )
        return f"([dim]{track_count} tracks[/dim])"

    return ""


def list_workflows():
    """Discover and parse workflow definitions from JSON files."""
    # Get path to workflow definitions directory
    current_file = Path(__file__)
    definitions_path = (
        current_file.parent.parent.parent / "application" / "workflows" / "definitions"
    )
    workflows = []

    if not definitions_path.exists():
        return workflows

    for json_file in definitions_path.glob("*.json"):
        try:
            definition = json.loads(json_file.read_text())

            workflows.append({
                "id": definition.get("id", json_file.stem),
                "name": definition.get("name", "Unknown"),
                "description": definition.get("description", ""),
                "task_count": len(definition.get("tasks", [])),
                "path": str(json_file),
            })
        except (OSError, json.JSONDecodeError) as e:
            console.print(
                f"[yellow]Warning: Could not parse {json_file.name}: {e}[/yellow]"
            )
            continue

    return workflows


def initialize_workflow_system() -> tuple[bool, str]:
    """Initialize and validate workflow nodes."""
    try:
        from src.application.workflows import validate_registry

        return validate_registry()
    except Exception as e:
        return False, f"Workflow initialization failed: {e!s}"
