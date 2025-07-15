"""Clean play data commands using Typer best practices and proper separation of concerns."""

from pathlib import Path
from typing import Annotated

import typer

from src.application.use_cases.import_tracks import run_import
from src.domain.entities import OperationResult
from src.infrastructure.cli.async_helpers import async_db_operation
from src.infrastructure.persistence.repositories.track import TrackRepositories

# Create plays subcommand app with clean structure
app = typer.Typer(help="Import play history data")


# Spotify Commands
@app.command()
def spotify_file(
    file_path: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            help="Spotify JSON export file path",
        ),
    ],
) -> None:
    """Import plays from Spotify JSON export file."""
    _run_spotify_file_import(file_path=file_path)


# LastFM Commands
@app.command()
def lastfm_recent(
    limit: Annotated[
        int, typer.Option("--limit", "-l", help="Number of recent plays to import")
    ] = 1000,
    resolve_tracks: Annotated[
        bool,
        typer.Option("--resolve-tracks", help="Resolve tracks for playlist workflows"),
    ] = False,
) -> None:
    """Import recent plays from Last.fm API."""
    _run_lastfm_recent_import(limit=limit, resolve_tracks=resolve_tracks)


@app.command()
def lastfm_incremental(
    resolve_tracks: Annotated[
        bool,
        typer.Option(
            "--resolve-tracks/--no-resolve-tracks", help="Resolve tracks for playlists"
        ),
    ] = True,
    user_id: Annotated[
        str | None,
        typer.Option(
            "--user", "-u", help="Last.fm username (defaults to LASTFM_USERNAME env)"
        ),
    ] = None,
) -> None:
    """Import new Last.fm plays since last sync."""
    _run_lastfm_incremental_import(user_id=user_id, resolve_tracks=resolve_tracks)


@app.command()
def lastfm_full(
    resolve_tracks: Annotated[
        bool,
        typer.Option(
            "--resolve-tracks/--no-resolve-tracks", help="Resolve tracks for playlists"
        ),
    ] = True,
    user_id: Annotated[
        str | None,
        typer.Option(
            "--user", "-u", help="Last.fm username (defaults to LASTFM_USERNAME env)"
        ),
    ] = None,
    confirm: Annotated[
        bool, typer.Option("--confirm", help="Skip confirmation prompt")
    ] = False,
) -> None:
    """Import full Last.fm play history (resets checkpoint)."""
    _run_lastfm_full_import(
        user_id=user_id, resolve_tracks=resolve_tracks, confirm=confirm
    )


# Internal async wrappers - these handle the DB connection and orchestration
# All business logic is now in the ImportOrchestrator service


@async_db_operation()
async def _run_spotify_file_import(
    file_path: Path,
    *,
    repositories: TrackRepositories,
) -> OperationResult:
    """Run Spotify file import via orchestrator."""
    return await run_import("spotify", "file", repositories, file_path=file_path)


@async_db_operation()
async def _run_lastfm_recent_import(
    limit: int,
    resolve_tracks: bool,
    *,
    repositories: TrackRepositories,
) -> OperationResult:
    """Run LastFM recent import via orchestrator."""
    return await run_import(
        "lastfm", "recent", repositories, limit=limit, resolve_tracks=resolve_tracks
    )


@async_db_operation()
async def _run_lastfm_incremental_import(
    user_id: str | None,
    resolve_tracks: bool,
    *,
    repositories: TrackRepositories,
) -> OperationResult:
    """Run LastFM incremental import via orchestrator."""
    return await run_import(
        "lastfm",
        "incremental",
        repositories,
        user_id=user_id,
        resolve_tracks=resolve_tracks,
    )


@async_db_operation()
async def _run_lastfm_full_import(
    user_id: str | None,
    resolve_tracks: bool,
    confirm: bool,
    *,
    repositories: TrackRepositories,
) -> OperationResult:
    """Run LastFM full history import via orchestrator."""
    return await run_import(
        "lastfm",
        "full",
        repositories,
        user_id=user_id,
        resolve_tracks=resolve_tracks,
        confirm=confirm,
    )
