"""Unified data commands for managing music data in Narada CLI."""

from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, cast

if TYPE_CHECKING:
    from collections.abc import Coroutine

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
import typer

from src.application.use_cases.import_tracks import run_import
from src.application.use_cases.sync_likes import (
    run_lastfm_likes_export,
    run_spotify_likes_import,
)
from src.domain.entities import OperationResult
from src.infrastructure.cli.async_helpers import async_db_operation
from src.infrastructure.persistence.database.db_connection import get_session
from src.infrastructure.persistence.repositories.factories import get_unit_of_work

# Initialize console
console = Console()


class DataOperation(StrEnum):
    """Data operations available in Narada."""

    # Play history operations
    IMPORT_PLAYS_FILE = "import-plays-file"
    IMPORT_PLAYS_LASTFM = "import-plays-lastfm"

    # Liked tracks operations
    IMPORT_LIKES_SPOTIFY = "import-likes-spotify"
    EXPORT_LIKES_LASTFM = "export-likes-lastfm"


# Operation metadata for menu display
OPERATION_METADATA = {
    DataOperation.IMPORT_PLAYS_FILE: {
        "description": "Import play history from Spotify export file",
        "category": "import",
        "icon": "📁",
    },
    DataOperation.IMPORT_PLAYS_LASTFM: {
        "description": "Import play history from Last.fm API",
        "category": "import",
        "icon": "🎵",
    },
    DataOperation.IMPORT_LIKES_SPOTIFY: {
        "description": "Import liked tracks from Spotify API",
        "category": "import",
        "icon": "💚",
    },
    DataOperation.EXPORT_LIKES_LASTFM: {
        "description": "Export your likes to Last.fm as loves",
        "category": "export",
        "icon": "❤️",
    },
}


# Create data subcommand app
app = typer.Typer(help="Manage your music data")


@app.callback(invoke_without_command=True)
def data_main(ctx: typer.Context) -> None:
    """Manage your music data - import/export plays and likes.

    Shows interactive menu when called without a subcommand.
    """
    if ctx.invoked_subcommand is None:
        # Show interactive menu when no subcommand provided
        operation = _show_data_menu()
        if operation is not None:
            # Route to appropriate handler with default parameters
            _route_data_operation(
                operation=operation,
                file_path=None,
                recent=None,
                limit=None,
                batch_size=None,
                full=False,
                confirm=False,
                resolve_tracks=True,
                user_id=None,
            )


@app.command()
def menu(
    operation: Annotated[
        DataOperation | None,
        typer.Argument(help="Data operation to perform"),
    ] = None,
    # File operations
    file_path: Annotated[
        Path | None,
        typer.Option("--file", "-f", help="File path for file-based imports"),
    ] = None,
    # Quantity controls
    recent: Annotated[
        int | None,
        typer.Option("--recent", "-r", help="Number of recent plays to import"),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option("--limit", "-l", help="Maximum number of items to process"),
    ] = None,
    # Batch processing
    batch_size: Annotated[
        int | None,
        typer.Option("--batch-size", "-b", help="Batch size for processing"),
    ] = None,
    # Sync modes
    full: Annotated[
        bool,
        typer.Option("--full", help="Full sync instead of incremental"),
    ] = False,
    # Control options
    confirm: Annotated[
        bool,
        typer.Option("--confirm", help="Skip confirmation prompts"),
    ] = False,
    resolve_tracks: Annotated[
        bool,
        typer.Option(
            "--resolve-tracks/--no-resolve-tracks", help="Resolve tracks for playlists"
        ),
    ] = True,
    # User identification
    user_id: Annotated[
        str | None,
        typer.Option("--user", "-u", help="User ID for operations"),
    ] = None,
) -> None:
    """Manage your music data - import/export plays and likes."""

    # If no operation specified, show interactive menu
    if operation is None:
        operation = _show_data_menu()
        if operation is None:
            return  # User cancelled

    # Route to appropriate handler
    _route_data_operation(
        operation=operation,
        file_path=file_path,
        recent=recent,
        limit=limit,
        batch_size=batch_size,
        full=full,
        confirm=confirm,
        resolve_tracks=resolve_tracks,
        user_id=user_id,
    )


def _show_data_menu() -> DataOperation | None:
    """Display interactive data menu and get user selection."""

    # Group operations by category
    import_ops = [
        (op, meta)
        for op, meta in OPERATION_METADATA.items()
        if meta["category"] == "import"
    ]
    export_ops = [
        (op, meta)
        for op, meta in OPERATION_METADATA.items()
        if meta["category"] == "export"
    ]
    all_ops = import_ops + export_ops

    # Create menu display
    console.print(
        Panel.fit(
            "🎵 Manage your music data",
            title="[bold blue]Narada Data[/bold blue]",
            border_style="blue",
        )
    )

    console.print("\n📥 [bold]Import Data[/bold]:")
    for i, (op, meta) in enumerate(import_ops, 1):
        console.print(
            f"  [cyan]{i}[/cyan]. [bold]{op.value}[/bold] - {meta['icon']} {meta['description']}"
        )

    console.print("\n📤 [bold]Export Data[/bold]:")
    for i, (op, meta) in enumerate(export_ops, len(import_ops) + 1):
        console.print(
            f"  [cyan]{i}[/cyan]. [bold]{op.value}[/bold] - {meta['icon']} {meta['description']}"
        )

    # Build choices list for Rich validation (numbers + operation names)
    # Add numeric choices
    choices = [str(i) for i in range(1, len(all_ops) + 1)]
    # Add operation name choices
    for op, _ in all_ops:
        choices.append(op.value)
    # Add exit options
    choices.extend(["q", "quit", "exit", "cancel"])

    # Get user selection with Rich validation
    console.print()
    choice = Prompt.ask(
        f"Select operation [1-{len(all_ops)}] or type name",
        choices=choices,
        default="",
        show_choices=False,  # Don't show the long list
    ).strip()

    # Handle exit options
    if choice in ("", "q", "quit", "exit", "cancel"):
        return None

    # Handle numeric selection
    if choice.isdigit():
        choice_num = int(choice)
        if 1 <= choice_num <= len(all_ops):
            return all_ops[choice_num - 1][0]

    # Handle name-based selection (Rich already validated it's in choices)
    for op in DataOperation:
        if op.value == choice:
            return op

    # This shouldn't happen since Rich validates choices
    return None


def _route_data_operation(
    operation: DataOperation,
    file_path: Path | None,
    recent: int | None,
    limit: int | None,
    batch_size: int | None,
    full: bool,
    confirm: bool,
    resolve_tracks: bool,
    user_id: str | None,
) -> None:
    """Route data operation to appropriate handler."""

    match operation:
        case DataOperation.IMPORT_PLAYS_FILE:
            _handle_spotify_plays_file(file_path, batch_size)

        case DataOperation.IMPORT_PLAYS_LASTFM:
            _handle_lastfm_plays(recent, limit, full, confirm, resolve_tracks, user_id)

        case DataOperation.IMPORT_LIKES_SPOTIFY:
            _handle_spotify_likes(limit, batch_size, user_id)

        case DataOperation.EXPORT_LIKES_LASTFM:
            _handle_lastfm_loves(limit, batch_size, user_id)

        case _:
            console.print(f"[red]Unknown operation: {operation}[/red]")


def _handle_spotify_plays_file(file_path: Path | None, batch_size: int | None) -> None:
    """Handle Spotify plays file import."""

    # Prompt for file path if not provided
    if file_path is None:
        file_path_str = Prompt.ask("Enter path to Spotify JSON export file")
        file_path = Path(file_path_str)

    # Validate file exists
    if not file_path.exists():
        console.print(f"[red]File not found: {file_path}[/red]")
        raise typer.Exit(1)

    import asyncio
    asyncio.run(cast("Coroutine[Any, Any, OperationResult]", _run_spotify_file_import(file_path=file_path, batch_size=batch_size)))


def _handle_lastfm_plays(
    recent: int | None,
    limit: int | None,  # noqa: ARG001
    full: bool,
    confirm: bool,
    resolve_tracks: bool,
    user_id: str | None,
) -> None:
    """Handle Last.fm plays import."""

    import asyncio
    
    if full:
        # Full import
        asyncio.run(cast("Coroutine[Any, Any, OperationResult]", _run_lastfm_full_import(
            user_id=user_id,
            resolve_tracks=resolve_tracks,
            confirm=confirm,
        )))
    elif recent is not None:
        # Recent import with specific limit
        asyncio.run(cast("Coroutine[Any, Any, OperationResult]", _run_lastfm_recent_import(
            limit=recent,
            resolve_tracks=resolve_tracks,
        )))
    else:
        # Default to incremental
        asyncio.run(cast("Coroutine[Any, Any, OperationResult]", _run_lastfm_incremental_import(
            user_id=user_id,
            resolve_tracks=resolve_tracks,
        )))


def _handle_spotify_likes(
    limit: int | None, batch_size: int | None, user_id: str | None
) -> None:
    """Handle Spotify likes import."""
    import asyncio
    asyncio.run(cast("Coroutine[Any, Any, OperationResult]", _run_spotify_likes_import(
        user_id=user_id or "default",
        batch_size=batch_size,
        limit=limit,
    )))


def _handle_lastfm_loves(
    limit: int | None, batch_size: int | None, user_id: str | None
) -> None:
    """Handle Last.fm loves export."""
    import asyncio
    asyncio.run(cast("Coroutine[Any, Any, OperationResult]", _run_lastfm_loves_export(
        user_id=user_id or "default",
        batch_size=batch_size,
        limit=limit,
    )))


# Data operation handlers (preserving all existing functionality)


@async_db_operation(
    progress_text="Importing plays from Spotify file...",
    success_text="Spotify plays imported successfully!",
    display_title="Spotify File Import Results",
)
async def _run_spotify_file_import(
    file_path: Path,
    batch_size: int | None,
) -> OperationResult:
    """Run Spotify file import via orchestrator."""
    kwargs: dict[str, Any] = {"file_path": file_path}
    if batch_size is not None:
        kwargs["batch_size"] = batch_size

    return await run_import("spotify", "file", **kwargs)


@async_db_operation(
    progress_text="Importing recent plays from Last.fm...",
    success_text="Last.fm plays imported successfully!",
    display_title="Last.fm Recent Import Results",
)
async def _run_lastfm_recent_import(
    limit: int,
    resolve_tracks: bool,
) -> OperationResult:
    """Run LastFM recent import via orchestrator."""
    return await run_import(
        "lastfm", "recent", limit=limit, resolve_tracks=resolve_tracks
    )


@async_db_operation(
    progress_text="Importing new plays from Last.fm...",
    success_text="Last.fm incremental sync completed!",
    display_title="Last.fm Incremental Import Results",
)
async def _run_lastfm_incremental_import(
    user_id: str | None,
    resolve_tracks: bool,
) -> OperationResult:
    """Run LastFM incremental import via orchestrator."""
    return await run_import(
        "lastfm",
        "incremental",
        user_id=user_id,
        resolve_tracks=resolve_tracks,
    )


@async_db_operation(
    progress_text="Importing full Last.fm play history...",
    success_text="Last.fm full import completed!",
    display_title="Last.fm Full Import Results",
)
async def _run_lastfm_full_import(
    user_id: str | None,
    resolve_tracks: bool,
    confirm: bool,
) -> OperationResult:
    """Run LastFM full history import via orchestrator."""
    return await run_import(
        "lastfm",
        "full",
        user_id=user_id,
        resolve_tracks=resolve_tracks,
        confirm=confirm,
    )


@async_db_operation(
    progress_text="Importing liked tracks from Spotify...",
    success_text="Spotify likes imported successfully!",
    display_title="Spotify Likes Import Results",
    next_step_message="[yellow]Tip:[/yellow] Run [cyan]narada data export-likes-lastfm[/cyan] to sync your likes to Last.fm",
)
async def _run_spotify_likes_import(
    user_id: str,
    batch_size: int | None,
    limit: int | None,
) -> OperationResult:
    """Run Spotify likes import operation."""
    async with get_session() as session:
        uow = get_unit_of_work(session)
        return await run_spotify_likes_import(
            uow=uow,
            user_id=user_id,
            limit=batch_size,  # API batch size
            max_imports=limit,  # Max total imports
        )


@async_db_operation(
    progress_text="Exporting likes to Last.fm...",
    success_text="Likes exported to Last.fm successfully!",
    display_title="Last.fm Loves Export Results",
)
async def _run_lastfm_loves_export(
    user_id: str,
    batch_size: int | None,
    limit: int | None,
) -> OperationResult:
    """Run Last.fm loves export operation."""
    async with get_session() as session:
        uow = get_unit_of_work(session)
        return await run_lastfm_likes_export(
            uow=uow,
            user_id=user_id,
            batch_size=batch_size,
            max_exports=limit,
        )


# Individual commands for direct access


@app.command(name="import-plays-file")
def import_plays_file_command(
    file_path: Annotated[
        Path,
        typer.Argument(help="Path to Spotify JSON export file"),
    ],
    batch_size: Annotated[
        int | None,
        typer.Option("--batch-size", "-b", help="Batch size for processing"),
    ] = None,
) -> None:
    """Import play history from Spotify JSON export file."""
    _handle_spotify_plays_file(file_path, batch_size)


@app.command(name="import-plays-lastfm")
def import_plays_lastfm_command(
    recent: Annotated[
        int | None,
        typer.Option("--recent", "-r", help="Number of recent plays to import"),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option("--limit", "-l", help="Maximum number of items to process"),
    ] = None,
    full: Annotated[
        bool,
        typer.Option("--full", help="Full sync instead of incremental"),
    ] = False,
    confirm: Annotated[
        bool,
        typer.Option("--confirm", help="Skip confirmation prompts"),
    ] = False,
    resolve_tracks: Annotated[
        bool,
        typer.Option(
            "--resolve-tracks/--no-resolve-tracks", help="Resolve tracks for playlists"
        ),
    ] = True,
    user_id: Annotated[
        str | None,
        typer.Option("--user", "-u", help="User ID for operations"),
    ] = None,
) -> None:
    """Import play history from Last.fm API."""
    _handle_lastfm_plays(recent, limit, full, confirm, resolve_tracks, user_id)


@app.command(name="import-likes-spotify")
def import_likes_spotify_command(
    limit: Annotated[
        int | None,
        typer.Option("--limit", "-l", help="Maximum number of items to process"),
    ] = None,
    batch_size: Annotated[
        int | None,
        typer.Option("--batch-size", "-b", help="Batch size for processing"),
    ] = None,
    user_id: Annotated[
        str | None,
        typer.Option("--user", "-u", help="User ID for operations"),
    ] = None,
) -> None:
    """Import liked tracks from Spotify API."""
    _handle_spotify_likes(limit, batch_size, user_id)


@app.command(name="export-likes-lastfm")
def export_likes_lastfm_command(
    limit: Annotated[
        int | None,
        typer.Option("--limit", "-l", help="Maximum number of items to process"),
    ] = None,
    batch_size: Annotated[
        int | None,
        typer.Option("--batch-size", "-b", help="Batch size for processing"),
    ] = None,
    user_id: Annotated[
        str | None,
        typer.Option("--user", "-u", help="User ID for operations"),
    ] = None,
) -> None:
    """Export your liked tracks to Last.fm as loves."""
    _handle_lastfm_loves(limit, batch_size, user_id)
