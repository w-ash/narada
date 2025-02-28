"""
Factory system for workflow components with unified patterns.

This module provides a streamlined approach to component creation, consolidating
the various factory patterns into a cohesive system with minimal boilerplate.
"""

from datetime import datetime
from typing import Any, Awaitable, Callable, TypedDict, TypeVar, cast

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

# Type definitions
T = TypeVar("T")
ComponentFn = Callable[[dict, dict], Awaitable[dict]]
TransformFn = Callable[[TrackList], TrackList]
KeyFn = Callable[[Track], Any]
PredicateFn = Callable[[Track], bool]


class Result(TypedDict, total=False):
    """Standard component result structure."""

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
        for key, value in self.data.items():
            if isinstance(value, dict) and isinstance(
                value.get("tracklist"), TrackList
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
        Result,
        {
            "tracklist": tracklist,
            "operation": operation,
            "tracks_count": len(tracklist.tracks),
            **extras,
        },
    )


def make_component(transform_factory: Callable, operation: str) -> ComponentFn:
    """
    Unified component factory that handles all component types.

    This factory consolidates the patterns from multiple specialized factories.
    """

    async def component_impl(context: dict, config: dict) -> dict:
        ctx = Context(context)
        transform = transform_factory(ctx, config)

        # Handle different transform types
        match transform:
            case fn if callable(fn):
                # Function-based transform (filter, sort, etc.)
                tracklist = ctx.extract_tracklist()
                original_count = len(tracklist.tracks)
                result = fn(tracklist)
                transformed = cast(TrackList, result)

                # Use explicit cast to dict to fix type compatibility
                return dict(
                    tracklist=transformed,
                    operation=operation,
                    original_count=original_count,
                    removed_count=original_count - len(transformed.tracks),
                )

            # Add other specialized handling here if needed
            case _:
                raise TypeError(f"Unsupported transform type: {type(transform)}")

    return component_impl


# === TRANSFORM FACTORIES ===


def make_filter(predicate_fn: PredicateFn) -> TransformFn:
    """Create a tracklist filter using the provided predicate."""
    return cast(TransformFn, filter_by_predicate(predicate_fn))


def make_date_filter(
    min_age: int | None = None, max_age: int | None = None
) -> TransformFn:
    """Create a date range filter."""
    return cast(TransformFn, filter_by_date_range(min_age, max_age))


def make_dedup_filter() -> TransformFn:
    """Create a deduplication filter."""
    return cast(TransformFn, filter_duplicates())


def make_exclusion_filter(
    reference_tracks: list[Track], by_artist: bool = False
) -> TransformFn:
    """Create an exclusion filter (by track or artist)."""
    return cast(
        TransformFn,
        exclude_artists(reference_tracks)
        if by_artist
        else exclude_tracks(reference_tracks),
    )


def make_sorter(key_fn: KeyFn, reverse: bool = False) -> TransformFn:
    """Create a sorter using the provided key function."""
    return cast(TransformFn, sort_by_attribute(key_fn, reverse))


def make_selector(count: int, method: str = "first") -> TransformFn:
    """Create a track selector (first, last, random)."""
    return cast(TransformFn, select_by_method(count, method))


def make_combiner(
    tracklists: list[TrackList], interleaved: bool = False
) -> TransformFn:
    """Create a tracklist combiner."""
    if interleaved:
        return cast(TransformFn, interleave(tracklists))
    return cast(TransformFn, concatenate(tracklists))


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


def spotify_popularity_key(ctx: Context, config: dict) -> Callable[[Track], int]:
    """Create key function for Spotify popularity sorting."""
    return lambda track: track.get_connector_attribute("spotify", "popularity", 0)


# === PREDICATE FACTORIES ===


def date_range_predicate(ctx: Context, config: dict) -> PredicateFn:
    """Create a predicate for date range filtering."""
    min_age_days = config.get("min_age_days")
    max_age_days = config.get("max_age_days")
    now = datetime.now()

    def in_date_range(track: Track) -> bool:
        if not track.release_date:
            return False

        age_days = (now - track.release_date).days

        if max_age_days is not None and age_days > max_age_days:
            return False

        if min_age_days is not None and age_days < min_age_days:
            return False

        return True

    return in_date_range


def exclusion_predicate(ctx: Context, config: dict) -> PredicateFn:
    """Create a predicate for exclusion filtering."""
    # Get reference playlist from another task
    ref_task_id = config.get("reference_task_id")
    exclude_artists_flag = config.get("exclude_artists", False)

    if not ref_task_id or ref_task_id not in ctx.data:
        raise ValueError(f"Missing reference task: {ref_task_id}")

    reference = ctx.data[ref_task_id].get("tracklist") or ctx.data[ref_task_id].get(
        "playlist"
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


# === COMPONENT FACTORY FUNCTIONS ===
# These integrate with your component registry


def filter_factory(ctx: Context, config: dict) -> TransformFn:
    """Factory for filter components."""
    filter_type = config.get("filter_type", "predicate")

    match filter_type:
        case "date_range":
            return make_date_filter(
                config.get("min_age_days"), config.get("max_age_days")
            )
        case "deduplicate":
            return make_dedup_filter()
        case "exclusion":
            return make_filter(exclusion_predicate(ctx, config))
        case _:
            raise ValueError(f"Unknown filter type: {filter_type}")


def sorter_factory(ctx: Context, config: dict) -> TransformFn:
    """Factory for sorter components."""
    sort_by = config.get("sort_by", "popularity")
    reverse = config.get("reverse", True)

    match sort_by:
        case "play_count":
            return make_sorter(user_play_count_key(ctx, config), reverse)
        case "popularity":
            return make_sorter(spotify_popularity_key(ctx, config), reverse)
        case "date":
            return make_sorter(lambda t: t.release_date or datetime.min, reverse)
        case _:
            raise ValueError(f"Unknown sort type: {sort_by}")


def selector_factory(ctx: Context, config: dict) -> TransformFn:
    """Factory for selector components."""
    count = config.get("count", 10)
    method = config.get("method", "first")

    return make_selector(count, method)


def combiner_factory(ctx: Context, config: dict) -> TransformFn:
    """Factory for combiner components."""
    source_tasks = config.get("sources", [])
    interleaved = config.get("interleaved", False)

    tracklists = ctx.collect_tracklists(source_tasks)
    if not tracklists:
        raise ValueError("No tracklists found for combiner")

    return make_combiner(tracklists, interleaved)
