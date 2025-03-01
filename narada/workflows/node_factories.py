"""
Factory system for workflow nodes with unified patterns.

This module provides a streamlined approach to node creation, consolidating
the various factory patterns into a cohesive system with minimal boilerplate.
"""

from asyncio import iscoroutinefunction
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, TypedDict, TypeVar, cast

from narada.config import get_logger
from narada.core.models import Playlist, Track, TrackList
from narada.core.transforms import (
    concatenate,
    exclude_artists,
    exclude_tracks,
    filter_by_date_range,
    filter_by_predicate,
    filter_duplicates,
    interleave,
    select_by_method,
    sort_by_attribute,
)

logger = get_logger(__name__)

# === TYPE DEFINITIONS ===

T = TypeVar("T")
NodeFn = Callable[[dict, dict], Awaitable[dict]]
TransformFn = Callable[[TrackList], TrackList]
KeyFn = Callable[[Track], Any]
PredicateFn = Callable[[Track], bool]


class Result(TypedDict, total=False):
    """Standard node result structure."""

    tracklist: TrackList
    playlist: Playlist
    operation: str
    tracks_count: int
    original_count: int
    removed_count: int
    match_results: dict
    source_count: int


class Context:
    """Context extractor with simplified path-based access."""

    def __init__(self, data: dict) -> None:
        self.data = data

    def get(self, path: str, default: Any = None) -> Any:
        """Get a value from nested context using dot notation."""
        parts = path.split(".")
        current = self.data

        for part in parts:
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]

        return current

    def require(self, path: str) -> Any:
        """Get a required value, raising error if missing."""
        result = self.get(path)
        if result is None:
            raise ValueError(f"Required value missing: {path}")
        return result

    def extract_tracklist(self) -> TrackList:
        """Extract tracklist from context with fallback paths."""
        # Try direct paths first
        for path in ["tracklist", "result.tracklist"]:
            tracklist = self.get(path)
            if isinstance(tracklist, TrackList):
                return tracklist

        # Try to find in any task result
        for value in self.data.values():
            if isinstance(value, dict) and isinstance(
                value.get("tracklist"),
                TrackList,
            ):
                return value["tracklist"]

        raise ValueError("Missing required tracklist in context")

    def collect_tracklists(self, task_ids: list[str]) -> list[TrackList]:
        """Collect tracklists from multiple task results."""
        return [
            self.data[task_id]["tracklist"]
            for task_id in task_ids
            if task_id in self.data
            and isinstance(self.data[task_id].get("tracklist"), TrackList)
        ]


def make_result(tracklist: TrackList, operation: str, **extras) -> Result:
    """Create standard result dictionary."""
    return cast(
        "Result",
        {
            "tracklist": tracklist,
            "operation": operation,
            "tracks_count": len(tracklist.tracks),
            **extras,
        },
    )


def make_node(transform_factory: Callable, operation: str) -> NodeFn:
    """
    Unified node factory that handles all node types.

    This factory consolidates the patterns from multiple specialized factories.
    """

    async def node_impl(context: dict, config: dict) -> dict:
        ctx = Context(context)

        # Handle potentially async transform_factory
        transform: Any
        if iscoroutinefunction(transform_factory):
            transform = await transform_factory(ctx, config)
        else:
            transform = transform_factory(ctx, config)

        # Handle different transform types
        match transform:
            case fn if callable(fn):
                # Function-based transform (filter, sort, etc.)
                tracklist = ctx.extract_tracklist()
                original_count = len(tracklist.tracks)

                # Handle potentially async transform function with proper typing
                transformed: TrackList
                if iscoroutinefunction(fn):
                    # Since we know it's a coroutine function, we can safely await it
                    result = await fn(tracklist)  # type: ignore
                    transformed = cast("TrackList", result)
                else:
                    # For synchronous functions
                    result = fn(tracklist)
                    transformed = cast("TrackList", result)

                return {
                    "tracklist": transformed,
                    "operation": operation,
                    "original_count": original_count,
                    "removed_count": original_count - len(transformed.tracks),
                }
            case _:
                raise TypeError(f"Unsupported transform type: {type(transform)}")

    return node_impl


async def persist_tracks_and_playlist(
    tracks: list[Track],
    playlist_name: str | None = None,
    playlist_description: str | None = None,
    playlist_connector_ids: dict[str, str] | None = None,
) -> tuple[list[Track], str | None, dict[str, int]]:
    """Persist tracks and optionally a playlist to the database.

    Args:
        tracks: List of track domain models
        playlist_name: Optional playlist name (if playlist should be saved)
        playlist_description: Optional playlist description
        playlist_connector_ids: Optional connector IDs for the playlist

    Returns:
        Tuple of (persisted tracks with IDs, playlist DB ID if created, persistence stats)
    """
    from narada.core.models import Playlist
    from narada.core.repositories import PlaylistRepository, TrackRepository
    from narada.data.database import get_session

    # Statistics for tracking persistence operation
    new_tracks = 0
    updated_tracks = 0
    playlist_id = None

    async with get_session(rollback=False) as session:
        track_repo = TrackRepository(session)

        # Save all tracks to get database IDs
        db_tracks = []
        for track in tracks:
            try:
                original_id = track.id
                saved_track = await track_repo.save_track(track)

                # Track whether this was new or updated
                if original_id != saved_track.id:
                    if original_id is None:
                        new_tracks += 1
                    else:
                        updated_tracks += 1

                db_tracks.append(saved_track)
            except Exception as e:
                logger.error(f"Error persisting track {track.title}: {e!s}")
                db_tracks.append(track)  # Use original track if save fails

        # If playlist info provided, save playlist too
        if playlist_name:
            try:
                playlist_repo = PlaylistRepository(session)
                playlist = Playlist(
                    name=playlist_name,
                    description=playlist_description,
                    tracks=db_tracks,
                    connector_track_ids=playlist_connector_ids or {},
                )
                playlist_id = await playlist_repo.save_playlist(playlist, track_repo)
                logger.debug(f"Saved playlist {playlist_name} with ID: {playlist_id}")
            except Exception as e:
                logger.error(f"Error saving playlist {playlist_name}: {e!s}")

    return (
        db_tracks,
        playlist_id,
        {"new_tracks": new_tracks, "updated_tracks": updated_tracks},
    )


# === TRANSFORM FACTORIES ===


def make_filter(predicate_fn: PredicateFn) -> TransformFn:
    """Create a tracklist filter using the provided predicate."""
    return cast("TransformFn", filter_by_predicate(predicate_fn))


def make_date_filter(
    min_age: int | None = None,
    max_age: int | None = None,
) -> TransformFn:
    """Create a date range filter."""
    return cast("TransformFn", filter_by_date_range(min_age, max_age))


def make_dedup_filter() -> TransformFn:
    """Create a deduplication filter."""
    return cast("TransformFn", filter_duplicates())


def make_exclusion_filter(
    reference_tracks: list[Track],
    by_artist: bool = False,
) -> TransformFn:
    """Create an exclusion filter (by track or artist)."""
    return cast(
        "TransformFn",
        exclude_artists(reference_tracks)
        if by_artist
        else exclude_tracks(reference_tracks),
    )


def make_sorter(key_fn: KeyFn, reverse: bool = False) -> TransformFn:
    """Create a sorter using the provided key function."""
    return cast("TransformFn", sort_by_attribute(key_fn, reverse))


def make_selector(count: int, method: str = "first") -> TransformFn:
    """Create a track selector (first, last, random)."""
    return cast("TransformFn", select_by_method(count, method))


def make_combiner(
    tracklists: list[TrackList],
    interleaved: bool = False,
) -> TransformFn:
    """Create a tracklist combiner."""
    if interleaved:
        return cast("TransformFn", interleave(tracklists))
    return cast("TransformFn", concatenate(tracklists))


# === KEY FACTORIES ===


def user_play_count_key(ctx: Context, config: dict) -> Callable[[Track], int]:
    """Create key function for user play count sorting."""
    min_confidence = config.get("min_confidence", 60)

    # Try to find match results in context
    match_results = (
        ctx.get("match_results")
        or ctx.get("result.match_results")
        or next(
            (
                v.get("match_results")
                for k, v in ctx.data.items()
                if isinstance(v, dict) and v.get("match_results")
            ),
            {},
        )
    )

    def get_play_count(track: Track) -> int:
        if not track.id or not match_results or track.id not in match_results:
            return 0
        result = match_results[track.id]
        return (
            result.user_play_count
            if result.success and result.confidence >= min_confidence
            else 0
        )

    return get_play_count


def spotify_popularity_key(_ctx: Context, config: dict) -> Callable[[Track], int]:
    """Create key function for Spotify popularity sorting."""
    # Example of how you could use config if needed
    default_popularity = config.get("default_popularity", 0)

    return lambda track: track.get_connector_attribute(
        "spotify",
        "popularity",
        default_popularity,
    )


# === PREDICATE FACTORIES ===


def date_range_predicate(_ctx: Context, config: dict) -> PredicateFn:
    """Create a predicate for date range filtering."""
    min_age_days = config.get("min_age_days")
    max_age_days = config.get("max_age_days")
    now = datetime.now(tz=UTC)

    def in_date_range(track: Track) -> bool:
        if not track.release_date:
            return False

        age_days = (now - track.release_date).days

        if max_age_days is not None and age_days > max_age_days:
            return False

        return not (min_age_days is not None and age_days < min_age_days)

    return in_date_range


def exclusion_predicate(ctx: Context, config: dict) -> PredicateFn:
    """Create a predicate for exclusion filtering."""
    # Get reference playlist from another task
    ref_task_id = config.get("reference_task_id")
    exclude_artists_flag = config.get("exclude_artists", False)

    if not ref_task_id or ref_task_id not in ctx.data:
        raise ValueError(f"Missing reference task: {ref_task_id}")

    reference = ctx.data[ref_task_id].get("tracklist") or ctx.data[ref_task_id].get(
        "playlist",
    )

    if not reference or not hasattr(reference, "tracks"):
        raise ValueError(f"No tracks found in reference task: {ref_task_id}")

    if exclude_artists_flag:
        # Create artist exclusion set
        artist_names = {
            track.artists[0].name.lower() for track in reference.tracks if track.artists
        }

        return lambda track: not (
            track.artists and track.artists[0].name.lower() in artist_names
        )
    else:
        # Create track ID exclusion set
        track_ids = {track.id for track in reference.tracks if track.id}

        return lambda track: track.id not in track_ids


# === NODE FACTORY FUNCTIONS ===
# These integrate with your node registry


def filter_factory(ctx: Context, config: dict) -> TransformFn:
    """Factory for filter nodes."""
    filter_type = config.get("filter_type", "predicate")

    match filter_type:
        case "date_range":
            return make_date_filter(
                config.get("min_age_days"),
                config.get("max_age_days"),
            )
        case "deduplicate":
            return make_dedup_filter()
        case "exclusion":
            return make_filter(exclusion_predicate(ctx, config))
        case _:
            raise ValueError(f"Unknown filter type: {filter_type}")


def sorter_factory(ctx: Context, config: dict) -> TransformFn:
    """Factory for sorter nodes."""
    sort_by = config.get("sort_by", "popularity")
    reverse = config.get("reverse", True)

    match sort_by:
        case "play_count":
            return make_sorter(user_play_count_key(ctx, config), reverse)
        case "popularity":
            return make_sorter(spotify_popularity_key(ctx, config), reverse)
        case "date":
            return make_sorter(
                lambda t: t.release_date or datetime.min.replace(tzinfo=UTC),
                reverse,
            )
        case _:
            raise ValueError(f"Unknown sort type: {sort_by}")


def selector_factory(_ctx: Context, config: dict) -> TransformFn:
    """Factory for selector nodes."""
    count = config.get("count", 10)
    method = config.get("method", "first")

    return make_selector(count, method)


def combiner_factory(ctx: Context, config: dict) -> TransformFn:
    """Factory for combiner nodes."""
    source_tasks = config.get("sources", [])
    interleaved = config.get("interleaved", False)

    tracklists = ctx.collect_tracklists(source_tasks)
    if not tracklists:
        raise ValueError("No tracklists found for combiner")

    return make_combiner(tracklists, interleaved)


# Replace the duplicated playlist_destination_factory with this single cleaner version


async def playlist_destination_factory(
    ctx: Context,
    config: dict,
    operation: str,
) -> dict:
    """Factory for playlist destination operations."""
    tracklist = ctx.extract_tracklist()
    name = config.get("name", "Narada Playlist")
    description = config.get("description", "Created by Narada")

    match operation:
        case "create_internal":
            # Only persist to internal database
            db_tracks, playlist_id, stats = await persist_tracks_and_playlist(
                tracklist.tracks,
                playlist_name=name,
                playlist_description=description,
            )

            return {
                "playlist_id": playlist_id,
                "playlist_name": name,
                "track_count": len(tracklist.tracks),
                "operation": "create_internal_playlist",
                **stats,
            }

        case "create_spotify":
            from narada.integrations.spotify import SpotifyConnector

            # Create on Spotify first
            spotify = SpotifyConnector()
            spotify_id = await spotify.create_playlist(
                name,
                tracklist.tracks,
                description,
            )

            # Then persist to our database with Spotify ID
            db_tracks, playlist_id, stats = await persist_tracks_and_playlist(
                tracklist.tracks,
                playlist_name=name,
                playlist_description=description,
                playlist_connector_ids={"spotify": spotify_id},
            )

            return {
                "playlist_id": playlist_id,
                "spotify_playlist_id": spotify_id,
                "playlist_name": name,
                "track_count": len(tracklist.tracks),
                "operation": "create_spotify_playlist",
                **stats,
            }

        case "update_spotify":
            spotify_id = config.get("playlist_id")
            append = config.get("append", False)

            if not spotify_id:
                raise ValueError("Missing required playlist_id for update operation")

            from narada.core.repositories import PlaylistRepository, TrackRepository
            from narada.data.database import get_session

            # First persist all tracks to ensure they have IDs
            db_tracks, _, stats = await persist_tracks_and_playlist(tracklist.tracks)

            # Get existing playlist from database
            async with get_session(rollback=False) as session:
                track_repo = TrackRepository(session)
                playlist_repo = PlaylistRepository(session)
                existing = await playlist_repo.get_playlist("spotify", spotify_id)

                if not existing:
                    raise ValueError(f"Playlist with Spotify ID {spotify_id} not found")

                # Create updated playlist
                updated = existing.with_tracks(
                    existing.tracks + db_tracks if append else db_tracks,
                )

                # Update on Spotify
                from narada.integrations.spotify import SpotifyConnector

                spotify = SpotifyConnector()
                await spotify.update_playlist(spotify_id, updated, replace=not append)

                # Update in database
                await playlist_repo.update_playlist(
                    str(existing.id),
                    updated,
                    track_repo,
                )

            return {
                "playlist_id": str(existing.id),
                "spotify_playlist_id": spotify_id,
                "track_count": len(updated.tracks),
                "original_count": len(existing.tracks),
                "operation": "update_spotify_playlist",
                "append_mode": append,
                **stats,
            }

        case _:
            raise ValueError(f"Unsupported operation type: {operation}")
