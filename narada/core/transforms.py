"""
Pure functional transformations for playlists and tracks.

This module contains immutable, side-effect free functions that transform
domain models. These primitives form the foundation of our workflow system.

Transformations follow functional programming principles:
- Immutability: All operations return new objects instead of modifying existing ones
- Composition: Transformations can be combined to form complex pipelines
- Currying: Functions are designed to work with partial application
- Purity: No side effects or external dependencies
"""

from collections.abc import Callable
from datetime import UTC, datetime
import random
from typing import Any, TypeVar, cast

from toolz import compose_left, curry

from narada.core.models import Playlist, Track, TrackList

# Type variables for generic transformations
T = TypeVar("T", bound=TrackList)

# Type alias for transformation functions
Transform = Callable[[TrackList], TrackList]


# === Core Pipeline Functions ===


def create_pipeline(*operations: Transform) -> Transform:
    """
    Compose multiple transformations into a single operation.

    Args:
        *operations: Transformation functions to compose

    Returns:
        A single transformation function combining all operations
    """
    return compose_left(*operations)


# === Track Filtering ===


@curry
def filter_by_predicate(
    predicate: Callable[[Track], bool],
    tracklist: TrackList | None = None,
) -> Transform | TrackList:
    """
    Filter tracks based on a predicate function.

    Args:
        predicate: Function returning True for tracks to keep
        tracklist: Optional tracklist to transform immediately

    Returns:
        Transformation function or transformed tracklist if provided
    """

    def transform(t: TrackList) -> TrackList:
        filtered = [track for track in t.tracks if predicate(track)]
        return t.with_tracks(filtered)

    return transform(tracklist) if tracklist is not None else transform


@curry
def filter_duplicates(tracklist: TrackList | None = None) -> Transform | TrackList:
    """
    Remove duplicate tracks from a tracklist.

    Args:
        tracklist: Optional tracklist to transform immediately

    Returns:
        Transformation function or transformed tracklist if provided
    """

    def transform(t: TrackList) -> TrackList:
        seen_ids = set()
        unique_tracks = []
        duplicates_removed = 0
        original_count = len(t.tracks)
        tracks_without_ids = 0

        for track in t.tracks:
            if track.id is None:
                # If track has no ID, keep it (can't properly deduplicate)
                unique_tracks.append(track)
                tracks_without_ids += 1
            elif track.id not in seen_ids:
                seen_ids.add(track.id)
                unique_tracks.append(track)
            else:
                duplicates_removed += 1

        result = t.with_tracks(unique_tracks)
        # Add metadata for reporting
        return (
            result.with_metadata("duplicates_removed", duplicates_removed)
            .with_metadata("original_count", original_count)
            .with_metadata("tracks_without_ids", tracks_without_ids)
        )

    return transform(tracklist) if tracklist is not None else transform


@curry
def filter_by_date_range(
    min_age_days: int | None = None,
    max_age_days: int | None = None,
    tracklist: TrackList | None = None,
) -> Transform | TrackList:
    """
    Filter tracks by release date range.

    Args:
        min_age_days: Minimum age in days (None for no minimum)
        max_age_days: Maximum age in days (None for no maximum)
        tracklist: Optional tracklist to transform immediately

    Returns:
        Transformation function or transformed tracklist if provided
    """

    def in_date_range(track: Track) -> bool:
        if not track.release_date:
            return False

        age_days = (datetime.now(UTC) - track.release_date).days

        if max_age_days is not None and age_days > max_age_days:
            return False

        return not (min_age_days is not None and age_days < min_age_days)

    return cast("Transform | TrackList", filter_by_predicate(in_date_range, tracklist))


@curry
def exclude_tracks(
    reference_tracks: list[Track],
    tracklist: TrackList | None = None,
) -> Transform | TrackList:
    """
    Filter out tracks that exist in a reference collection.

    Args:
        reference_tracks: List of tracks to exclude
        tracklist: Optional tracklist to transform immediately

    Returns:
        Transformation function or transformed tracklist if provided
    """
    exclude_ids = {track.id for track in reference_tracks if track.id}

    def not_in_reference(track: Track) -> bool:
        return track.id not in exclude_ids

    return cast(
        "Transform | TrackList",
        filter_by_predicate(not_in_reference, tracklist),
    )


@curry
def exclude_artists(
    reference_tracks: list[Track],
    exclude_all_artists: bool = False,
    tracklist: TrackList | None = None,
) -> Transform | TrackList:
    """
    Filter out tracks whose artists appear in a reference collection.

    Args:
        reference_tracks: List of tracks with artists to exclude
        exclude_all_artists: If True, checks all artists on a track, not just primary
        tracklist: Optional tracklist to transform immediately

    Returns:
        Transformation function or transformed tracklist if provided
    """
    # Create set of artist names to exclude (case-insensitive)
    exclude_artists = set()

    for track in reference_tracks:
        if not track.artists:
            continue

        if exclude_all_artists:
            # Add all artists from the track
            exclude_artists.update(artist.name.lower() for artist in track.artists)
        else:
            # Add only the primary artist
            exclude_artists.add(track.artists[0].name.lower())

    def not_artist_in_reference(track: Track) -> bool:
        if not track.artists:
            return True

        if exclude_all_artists:
            # Check if any artist on the track is in the exclusion set
            return not any(
                artist.name.lower() in exclude_artists for artist in track.artists
            )
        else:
            # Check only the primary artist
            return track.artists[0].name.lower() not in exclude_artists

    return cast(
        "Transform | TrackList",
        filter_by_predicate(not_artist_in_reference, tracklist),
    )


# === Track Sorting ===


@curry
def sort_by_attribute(
    key_fn: Callable[[Track], Any],
    reverse: bool = False,
    tracklist: TrackList | None = None,
) -> Transform | TrackList:
    """
    Sort tracks by any attribute or derived value.

    Args:
        key_fn: Function extracting sort key from each track
        reverse: Whether to sort in descending order
        tracklist: Optional tracklist to transform immediately

    Returns:
        Transformation function or transformed tracklist if provided
    """

    def transform(t: TrackList) -> TrackList:
        sorted_tracks = sorted(t.tracks, key=key_fn, reverse=reverse)
        return t.with_tracks(sorted_tracks)

    return transform(tracklist) if tracklist is not None else transform


# === Track Selection ===


@curry
def limit(count: int, tracklist: TrackList | None = None) -> Transform | TrackList:
    """
    Limit to the first n tracks.

    Args:
        count: Maximum number of tracks to keep
        tracklist: Optional tracklist to transform immediately

    Returns:
        Transformation function or transformed tracklist if provided
    """

    def transform(t: TrackList) -> TrackList:
        return t.with_tracks(t.tracks[:count])

    return transform(tracklist) if tracklist is not None else transform


@curry
def take_last(
    count: int,
    tracklist: TrackList | None = None,
) -> Transform | TrackList:
    """
    Take the last n tracks.

    Args:
        count: Number of tracks to keep from the end
        tracklist: Optional tracklist to transform immediately

    Returns:
        Transformation function or transformed tracklist if provided
    """

    def transform(t: TrackList) -> TrackList:
        n = min(count, len(t.tracks))
        return t.with_tracks(t.tracks[-n:])

    return transform(tracklist) if tracklist is not None else transform


@curry
def sample_random(
    count: int,
    tracklist: TrackList | None = None,
) -> Transform | TrackList:
    """
    Randomly sample n tracks.

    Args:
        count: Number of tracks to sample
        tracklist: Optional tracklist to transform immediately

    Returns:
        Transformation function or transformed tracklist if provided
    """

    def transform(t: TrackList) -> TrackList:
        n = min(count, len(t.tracks))
        selected = random.sample(t.tracks, n)
        return t.with_tracks(selected)

    return transform(tracklist) if tracklist is not None else transform


@curry
def select_by_method(
    count: int,
    method: str = "first",
    tracklist: TrackList | None = None,
) -> Transform | TrackList:
    """
    Select tracks using specified method.

    Args:
        count: Number of tracks to select
        method: Selection method ("first", "last", or "random")
        tracklist: Optional tracklist to transform immediately

    Returns:
        Transformation function or transformed tracklist if provided
    """
    if method == "first":
        transform_fn = limit(count)
    elif method == "last":
        transform_fn = take_last(count)
    elif method == "random":
        transform_fn = sample_random(count)
    else:
        raise ValueError(f"Invalid selection method: {method}")

    def transform(t: TrackList) -> TrackList:
        result = cast("Transform", transform_fn)(t)
        return (
            cast("TrackList", result)
            .with_metadata("selection_method", method)
            .with_metadata("original_count", len(t.tracks))
        )

    return transform(tracklist) if tracklist is not None else transform


# === Track List Combination ===


@curry
def concatenate(
    tracklists: list[TrackList],
    tracklist: TrackList | None = None,
) -> Transform | TrackList:
    """
    Concatenate multiple tracklists.

    Args:
        tracklists: List of tracklists to combine
        tracklist: Optional tracklist to prepend (usually ignored)

    Returns:
        Transformation function or transformed tracklist if provided
    """

    def transform(_: TrackList) -> TrackList:
        all_tracks = []
        for t in tracklists:
            all_tracks.extend(t.tracks)

        return TrackList(
            tracks=all_tracks,
            metadata={"operation": "concatenate", "source_count": len(tracklists)},
        )

    return transform(tracklist or TrackList()) if tracklist is not None else transform


@curry
def interleave(
    tracklists: list[TrackList],
    stop_on_empty: bool = False,
    tracklist: TrackList | None = None,
) -> Transform | TrackList:
    """
    Interleave tracks from multiple tracklists.

    Args:
        tracklists: List of tracklists to interleave
        stop_on_empty: Whether to stop when any tracklist is exhausted
        tracklist: Optional tracklist to transform (usually ignored)

    Returns:
        Transformation function or transformed tracklist if provided
    """

    def transform(_: TrackList) -> TrackList:
        interleaved_tracks = []
        iterators = [iter(t.tracks) for t in tracklists]
        exhausted = [False] * len(tracklists)

        while not all(exhausted) and not (stop_on_empty and any(exhausted)):
            for i, track_iter in enumerate(iterators):
                if exhausted[i]:
                    continue

                try:
                    track = next(track_iter)
                    interleaved_tracks.append(track)
                except StopIteration:
                    exhausted[i] = True
                    if stop_on_empty:
                        break

        return TrackList(
            tracks=interleaved_tracks,
            metadata={
                "operation": "alternate",
                "source_count": len(tracklists),
                "stop_on_empty": stop_on_empty,
            },
        )

    return transform(tracklist or TrackList()) if tracklist is not None else transform


# === Playlist Operations ===


@curry
def rename(
    new_name: str,
    playlist: Playlist | None = None,
) -> Callable[[Playlist], Playlist] | Playlist:
    """
    Set playlist name.

    Args:
        new_name: New playlist name
        playlist: Optional playlist to transform immediately

    Returns:
        Transformation function or transformed playlist if provided
    """

    def transform(p: Playlist) -> Playlist:
        return Playlist(
            name=new_name,
            tracks=p.tracks,
            description=p.description,
            id=p.id,
            connector_track_ids=p.connector_track_ids.copy(),
        )

    return transform(playlist) if playlist is not None else transform


@curry
def set_description(
    description: str,
    playlist: Playlist | None = None,
) -> Callable[[Playlist], Playlist] | Playlist:
    """
    Set playlist description.

    Args:
        description: New playlist description
        playlist: Optional playlist to transform immediately

    Returns:
        Transformation function or transformed playlist if provided
    """

    def transform(p: Playlist) -> Playlist:
        return Playlist(
            name=p.name,
            tracks=p.tracks,
            description=description,
            id=p.id,
            connector_track_ids=p.connector_track_ids.copy(),
        )

    return transform(playlist) if playlist is not None else transform
