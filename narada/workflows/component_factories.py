"""Factories and utility functions for workflow components.

This module provides a clean abstraction layer between pure functional
transforms and component implementations, handling context extraction
and factory patterns for component creation.
"""

from datetime import datetime
from typing import Any, Awaitable, Callable, Optional, TypeVar, cast

from toolz import curry

from narada.core.models import Playlist, Track, TrackList
from narada.core.transforms import (
    Transform,
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

T = TypeVar("T")
ComponentFunc = Callable[[dict, dict], Awaitable[dict]]


class ComponentError(Exception):
    """Base exception for component errors."""

    pass


@curry
def make_result(tracklist: TrackList, operation: str, **extras) -> dict[str, Any]:
    """Create standard result dictionary."""
    result = {
        "tracklist": tracklist,
        "operation": operation,
        "tracks_count": len(tracklist.tracks),
        **extras,
    }
    return result


class ComponentContext:
    """Helper class to simplify context extraction and validation."""

    def __init__(self, data: dict[str, Any]):
        self.data = data

    def extract_tracklist(self) -> TrackList:
        """Extract tracklist from context."""
        # Direct tracklist in root context
        if "tracklist" in self.data and isinstance(self.data["tracklist"], TrackList):
            return self.data["tracklist"]

        # Tracklist in nested context
        for value in self.data.values():
            if isinstance(value, dict) and "tracklist" in value:
                if isinstance(value["tracklist"], TrackList):
                    return value["tracklist"]

        raise ComponentError("Missing required input: tracklist")

    def extract_playlist(self) -> Playlist:
        """Extract playlist from context."""
        # Direct playlist in root context
        if "playlist" in self.data and isinstance(self.data["playlist"], Playlist):
            return self.data["playlist"]

        # Playlist in nested context
        for value in self.data.values():
            if isinstance(value, dict) and "playlist" in value:
                if isinstance(value["playlist"], Playlist):
                    return value["playlist"]

        raise ComponentError("Missing required input: playlist")

    def get_match_results(self) -> dict:
        """Extract match results from context."""
        # Direct match results in root context
        if "match_results" in self.data and isinstance(
            self.data["match_results"], dict
        ):
            return self.data["match_results"]

        # Match results in nested context
        for value in self.data.values():
            if isinstance(value, dict) and "match_results" in value:
                return value["match_results"]

        raise ComponentError("Missing required input: match_results")

    def get_required_config(self, config: dict[str, Any], key: str) -> Any:
        """Get required configuration value."""
        if key not in config:
            raise ComponentError(f"Missing required config: {key}")
        return config[key]

    def get_task_result(self, task_id: str) -> dict[str, Any]:
        """Get a specific task result from context."""
        if task_id not in self.data:
            raise ComponentError(f"Task result not found: {task_id}")
        return self.data[task_id]

    def get_reference_playlist(self, config: dict[str, Any]) -> Playlist:
        """Extract reference playlist using task_id from config."""
        task_id = self.get_required_config(config, "reference_task_id")
        reference_result = self.get_task_result(task_id)

        if "playlist" not in reference_result:
            raise ComponentError(f"No playlist found in reference task: {task_id}")

        return reference_result["playlist"]

    def collect_tracklists(self, task_ids: list[str]) -> list[TrackList]:
        """Collect tracklists from multiple task results."""
        tracklists = []
        for task_id in task_ids:
            try:
                task_result = self.get_task_result(task_id)
                if "tracklist" in task_result:
                    tracklists.append(task_result["tracklist"])
            except ComponentError:
                continue  # Skip missing tasks

        if not tracklists:
            raise ComponentError("No tracklists found from the specified tasks")

        return tracklists


# === UTILITY FUNCTIONS ===


def ensure_tracklist(playlist_or_tracklist: Any) -> TrackList:
    """Convert input to TrackList if it's a Playlist."""
    if isinstance(playlist_or_tracklist, TrackList):
        return playlist_or_tracklist
    elif isinstance(playlist_or_tracklist, Playlist):
        return TrackList.from_playlist(playlist_or_tracklist)
    else:
        raise TypeError(
            f"Expected Playlist or TrackList, got {type(playlist_or_tracklist)}"
        )


def ensure_playlist(
    tracklist_or_playlist: Any,
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> Playlist:
    """Convert input to Playlist if it's a TrackList."""
    if isinstance(tracklist_or_playlist, Playlist):
        return tracklist_or_playlist
    elif isinstance(tracklist_or_playlist, TrackList):
        return Playlist(
            name=name
            or tracklist_or_playlist.metadata.get(
                "source_playlist_name", "Unnamed Playlist"
            ),
            description=description,
            tracks=tracklist_or_playlist.tracks,
        )
    else:
        raise TypeError(
            f"Expected TrackList or Playlist, got {type(tracklist_or_playlist)}"
        )


# === COMPONENT FACTORY PATTERNS ===


def create_transform_component(
    transform_fn: Transform, operation_name: str
) -> ComponentFunc:
    """Create a component that applies a transform to a tracklist."""

    async def component_impl(context: dict, config: dict) -> dict:
        ctx = ComponentContext(context)
        tracklist = ctx.extract_tracklist()
        transformed = transform_fn(tracklist)
        return cast(dict, make_result(transformed, operation_name))

    return component_impl


def create_filter_component(
    predicate_factory: Callable[[dict], Callable[[Track], bool]], operation_name: str
) -> ComponentFunc:
    """Create a filtering component using a predicate factory."""

    async def component_impl(context: dict, config: dict) -> dict:
        ctx = ComponentContext(context)
        tracklist = ctx.extract_tracklist()
        original_count = len(tracklist.tracks)

        # Create predicate from config
        predicate = predicate_factory(config)

        # Apply filter transform - need to explicitly handle the curry function
        transform_fn = cast(Transform, filter_by_predicate(predicate))
        filtered = transform_fn(tracklist)  # Now this should work correctly

        return cast(
            dict,
            make_result(
                filtered,
                operation_name,
                original_count=original_count,
                removed_count=original_count - len(filtered.tracks),
            ),
        )

    return component_impl


def create_dedup_component(operation_name: str) -> ComponentFunc:
    """Create a component that removes duplicate tracks."""

    async def component_impl(context: dict, config: dict) -> dict:
        ctx = ComponentContext(context)
        tracklist = ctx.extract_tracklist()
        original_count = len(tracklist.tracks)

        # Apply filter transform with explicit typing
        transform_fn = cast(Transform, filter_duplicates())
        deduped = transform_fn(tracklist)

        return cast(
            dict,
            make_result(
                deduped,
                operation_name,
                original_count=original_count,
                removed_count=original_count - len(deduped.tracks),
            ),
        )

    return component_impl


def create_date_filter_component(operation_name: str) -> ComponentFunc:
    """Create a component that filters tracks by date range."""

    async def component_impl(context: dict, config: dict) -> dict:
        ctx = ComponentContext(context)
        tracklist = ctx.extract_tracklist()
        original_count = len(tracklist.tracks)

        min_age_days = config.get("min_age_days")
        max_age_days = config.get("max_age_days")

        # Apply filter transform with explicit typing
        filter_fn = cast(Transform, filter_by_date_range(min_age_days, max_age_days))
        filtered = filter_fn(tracklist)

        return cast(
            dict,
            make_result(
                filtered,
                operation_name,
                original_count=original_count,
                removed_count=original_count - len(filtered.tracks),
            ),
        )

    return component_impl


def create_reference_filter_component(
    filter_type: str, operation_name: str
) -> ComponentFunc:
    """Create a component that filters against a reference playlist."""

    async def component_impl(context: dict, config: dict) -> dict:
        ctx = ComponentContext(context)
        tracklist = ctx.extract_tracklist()
        reference_playlist = ctx.get_reference_playlist(config)
        original_count = len(tracklist.tracks)

        # Choose appropriate filter based on type
        if filter_type == "tracks":
            filter_fn = cast(Transform, exclude_tracks(reference_playlist.tracks))
        elif filter_type == "artists":
            filter_fn = cast(Transform, exclude_artists(reference_playlist.tracks))
        else:
            raise ValueError(f"Unknown filter type: {filter_type}")

        filtered = filter_fn(tracklist)

        return cast(
            dict,
            make_result(
                filtered,
                operation_name,
                original_count=original_count,
                removed_count=original_count - len(filtered.tracks),
            ),
        )

    return component_impl


def create_sort_component(
    key_factory: Callable[[dict, dict], Callable[[Track], Any]], operation_name: str
) -> ComponentFunc:
    """Create a sorting component using a key function factory."""

    async def component_impl(context: dict, config: dict) -> dict:
        ctx = ComponentContext(context)
        tracklist = ctx.extract_tracklist()
        reverse = config.get("reverse", True)

        # Create key function from context and config
        key_fn = key_factory(context, config)

        # Apply sort transform with explicit typing
        sort_fn = cast(Transform, sort_by_attribute(key_fn, reverse))
        sorted_tracklist = sort_fn(tracklist)

        return cast(dict, make_result(sorted_tracklist, operation_name))

    return component_impl


def create_selection_component(operation_name: str) -> ComponentFunc:
    """Create a component that selects a subset of tracks."""

    async def component_impl(context: dict, config: dict) -> dict:
        ctx = ComponentContext(context)
        tracklist = ctx.extract_tracklist()

        # Get configuration
        count = ctx.get_required_config(config, "count")
        method = config.get("method", "first").lower()

        if method not in ["first", "last", "random"]:
            raise ComponentError(f"Invalid selection method: {method}")

        # Apply selection transform with explicit typing
        select_fn = cast(Transform, select_by_method(count, method))
        selected = select_fn(tracklist)

        return cast(
            dict,
            make_result(
                selected, f"{operation_name}_{method}", selection_method=method
            ),
        )

    return component_impl


def create_combine_component(
    operation_name: str, interleaved: bool = False
) -> ComponentFunc:
    """Create a component that combines multiple tracklists."""

    async def component_impl(context: dict, config: dict) -> dict:
        ctx = ComponentContext(context)
        order = ctx.get_required_config(config, "order")

        # Find tracklists in order
        tracklists = ctx.collect_tracklists(order)

        # Apply combine transform based on type with explicit typing
        if interleaved:
            stop_on_empty = config.get("stop_on_empty", False)
            combine_fn = cast(
                Transform, interleave(tracklists, stop_on_empty=stop_on_empty)
            )
        else:
            combine_fn = cast(Transform, concatenate(tracklists))

        # Use an empty TrackList as a placeholder since concatenate/interleave ignore it
        combined = combine_fn(TrackList())

        return cast(
            dict, make_result(combined, operation_name, source_count=len(tracklists))
        )

    return component_impl


# === KEY FUNCTION FACTORIES ===


def create_user_play_count_key(context: dict, config: dict) -> Callable[[Track], int]:
    """Create a key function for sorting by user play count."""
    try:
        match_results = ComponentContext(context).get_match_results()
        min_confidence = config.get("min_confidence", 60)
    except ComponentError:
        # Fallback if match results aren't available
        return lambda _: 0

    def get_play_count(track: Track) -> int:
        if not track.id or track.id not in match_results:
            return 0
        result = match_results[track.id]
        if not result.success or result.confidence < min_confidence:
            return 0
        return result.user_play_count

    return get_play_count


def create_spotify_popularity_key(
    context: dict, config: dict
) -> Callable[[Track], int]:
    """Create a key function for sorting by Spotify popularity."""

    def get_spotify_popularity(track: Track) -> int:
        return track.get_connector_attribute("spotify", "popularity", 0)

    return get_spotify_popularity


# === PREDICATE FACTORIES ===


def create_date_range_predicate(config: dict) -> Callable[[Track], bool]:
    """Create a predicate for filtering tracks by date range."""
    max_age_days = config.get("max_age_days")
    min_age_days = config.get("min_age_days")
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
