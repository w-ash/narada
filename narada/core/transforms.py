"""
Pure functional transformations for playlists and tracks.

This module contains immutable, side-effect free functions that transform
domain models. These primitives form the foundation of our workflow system.

Example snippet:
    def sort_by_attribute(key_func, reverse=False):
        '''Pure function that returns a transformation.'''
        def transform(playlist):
            sorted_tracks = sorted(playlist.tracks, key=key_func, reverse=reverse)
            return playlist.with_tracks(sorted_tracks)
        return transform

Interactions:
    Consumes: Domain models from models.py
    Produces: Functions that transform one immutable model into another
    Key principle: No side effects, no external dependencies, no state

This is the mathematical core - these functions should be so pure they could be moved to any system and still work identically.

Note: code below is from an earlier iteration, and needs replacement or substantial refactoring.

"""

from typing import Any, Callable, Optional, TypeVar, Union

from toolz import compose_left, curry

from narada.core.models import Playlist, Track

# Type variable for generic playlist transformations
P = TypeVar("P", bound=Playlist)

# Type alias for transformation functions
Transform = Callable[[P], P]


def create_pipeline(*operations: Transform) -> Transform:
    """Compose multiple transformations into a single operation.

    Args:
        *operations: Transformation functions to compose

    Returns:
        A single function that applies all transformations in sequence
    """
    return compose_left(*operations)


@curry
def sort_by_attribute(
    getter: Callable[[Track], Any],
    reverse: bool = False,
    playlist: Union[Playlist, None] = None,
) -> Union[Transform, Playlist]:
    """Sort playlist tracks by any attribute or derived value.

    Args:
        getter: Function extracting sort key from each track
        reverse: Whether to sort in descending order
        playlist: Optional playlist to transform immediately

    Returns:
        Transformation function or transformed playlist if provided
    """

    def transform(p: Playlist) -> Playlist:
        sorted_tracks = sorted(p.tracks, key=getter, reverse=reverse)
        return p.with_tracks(sorted_tracks)

    return transform(playlist) if playlist is not None else transform


@curry
def filter_by_predicate(
    predicate: Callable[[Track], bool], playlist: Optional[Playlist] = None
) -> Union[Transform, Playlist]:
    """Filter playlist to tracks matching a predicate.

    Args:
        predicate: Function returning True for tracks to keep
        playlist: Optional playlist to transform immediately

    Returns:
        Transformation function or transformed playlist if provided
    """

    def transform(p: Playlist) -> Playlist:
        filtered = [t for t in p.tracks if predicate(t)]
        return p.with_tracks(filtered)

    return transform(playlist) if playlist is not None else transform


@curry
def limit(
    count: int, playlist: Optional[Playlist] = None
) -> Union[Transform, Playlist]:
    """Limit playlist to specified number of tracks.

    Args:
        count: Maximum number of tracks to keep
        playlist: Optional playlist to transform immediately

    Returns:
        Transformation function or transformed playlist if provided
    """

    def transform(p: Playlist) -> Playlist:
        return p.with_tracks(p.tracks[:count])

    return transform(playlist) if playlist is not None else transform


@curry
def rename(
    new_name: str, playlist: Optional[Playlist] = None
) -> Union[Transform, Playlist]:
    """Set playlist name."""

    def transform(p: Playlist) -> Playlist:
        return Playlist(
            name=new_name,
            tracks=p.tracks,
            description=p.description,
            id=p.id,
            connector_track_ids=p.connector_track_ids.copy(),
        )

    return transform(playlist) if playlist is not None else transform
