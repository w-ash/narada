"""Functional playlist transformation primitives using toolz composition."""

from typing import Any, Callable, TypeVar, Union

from toolz import compose_left, curry

from narada.config import get_logger
from narada.core.models import Playlist, Track

logger = get_logger(__name__)

# Type aliases for transformation pipeline
P = TypeVar("P", bound=Playlist)
PlaylistTransform = Callable[[P], P]


def create_pipeline(*operations: PlaylistTransform) -> PlaylistTransform:
    """Compose multiple operations into a single transformation pipeline.

    This is the heart of our transformation architecture, allowing
    arbitrary composition of operations.
    """
    return compose_left(*operations)


@curry
def sort_by_attribute(
    attribute_getter: Callable[[Track], Any],
    reverse: bool = False,
    playlist: Playlist = None,
) -> Union[PlaylistTransform, Playlist]:
    """Sort playlist by any attribute or derived value.

    When partially applied, returns a transformation function.
    When fully applied, returns a transformed playlist.
    """

    def transform(p: Playlist) -> Playlist:
        sorted_tracks = sorted(p.tracks, key=attribute_getter, reverse=reverse)
        return p.with_tracks(sorted_tracks)

    return transform(playlist) if playlist is not None else transform


@curry
def filter_by_predicate(
    predicate: Callable[[Track], bool], playlist: Playlist = None
) -> Union[PlaylistTransform, Playlist]:
    """Filter playlist based on arbitrary track criteria."""

    def transform(p: Playlist) -> Playlist:
        filtered = [t for t in p.tracks if predicate(t)]
        return p.with_tracks(filtered)

    return transform(playlist) if playlist is not None else transform


@curry
def limit(count: int, playlist: Playlist = None) -> Union[PlaylistTransform, Playlist]:
    """Limit playlist to specified number of tracks."""

    def transform(p: Playlist) -> Playlist:
        return p.with_tracks(p.tracks[:count])

    return transform(playlist) if playlist is not None else transform


@curry
def rename(
    new_name: str, playlist: Playlist = None
) -> Union[PlaylistTransform, Playlist]:
    """Set playlist name."""

    def transform(p: Playlist) -> Playlist:
        return p.with_name(new_name)

    return transform(playlist) if playlist is not None else transform


@curry
def describe(
    new_description: str, playlist: Playlist = None
) -> Union[PlaylistTransform, Playlist]:
    """Set playlist description."""

    def transform(p: Playlist) -> Playlist:
        return p.with_description(new_description)

    return transform(playlist) if playlist is not None else transform
