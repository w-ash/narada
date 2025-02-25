"""Core domain models for music entities and operations.

These immutable models form the foundation of our business logic,
enforcing invariants while enabling functional transformation patterns.
"""

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, TypeVar

from attrs import define, field, validators

# Type variables for generic operations
T = TypeVar("T")
P = TypeVar("P", bound="Playlist")


@define(frozen=True, slots=True)
class Artist:
    """Artist representation with normalized metadata."""

    name: str = field(validator=validators.instance_of(str))


@define(frozen=True, slots=True)
class Track:
    """Immutable track entity representing a musical recording.

    Tracks are the core entity in our domain model, containing
    essential metadata while supporting resolution to external connectors.
    """

    title: str = field(validator=validators.instance_of(str))
    artists: List[Artist] = field(
        factory=list,
        validator=validators.deep_iterable(
            member_validator=validators.instance_of(Artist),
            iterable_validator=validators.min_len(1),
        ),
    )
    album: Optional[str] = field(default=None)
    duration_ms: Optional[int] = field(default=None)
    release_date: Optional[datetime] = field(default=None)
    isrc: Optional[str] = field(default=None)

    # Extended properties
    id: Optional[int] = field(default=None)
    play_count: Optional[int] = field(default=None)
    connector_track_ids: Dict[str, str] = field(factory=dict)

    def with_play_count(self, count: int) -> "Track":
        """Create a new track with play count information."""
        return self.__class__(
            title=self.title,
            artists=self.artists,
            album=self.album,
            duration_ms=self.duration_ms,
            release_date=self.release_date,
            isrc=self.isrc,
            id=self.id,
            play_count=count,
            connector_track_ids=self.connector_track_ids.copy(),
        )

    def with_connector_track_id(self, connector: str, sid: str) -> "Track":
        """Create a new track with additional connector identifier."""
        new_ids = self.connector_track_ids.copy()
        new_ids[connector] = sid

        return self.__class__(
            title=self.title,
            artists=self.artists,
            album=self.album,
            duration_ms=self.duration_ms,
            release_date=self.release_date,
            isrc=self.isrc,
            id=self.id,
            play_count=self.play_count,
            connector_track_ids=new_ids,
        )


@define(frozen=True)
class Playlist:
    """Immutable playlist entity containing an ordered collection of tracks.

    Playlists maintain track ordering while supporting functional
    transformations through non-mutating operations.
    """

    name: str = field(validator=validators.instance_of(str))
    tracks: List[Track] = field(factory=list)
    description: Optional[str] = field(default=None)
    id: Optional[int] = field(default=None)
    connector_track_ids: Dict[str, str] = field(factory=dict)

    def with_tracks(self, tracks: List[Track]) -> "Playlist":
        """Create a new playlist with the given tracks."""
        return self.__class__(
            name=self.name,
            tracks=tracks,
            description=self.description,
            id=self.id,
            connector_track_ids=self.connector_track_ids.copy(),
        )

    def with_connector_track_id(self, connector: str, sid: str) -> "Playlist":
        """Create a new playlist with additional connector identifier."""
        new_ids = self.connector_track_ids.copy()
        new_ids[connector] = sid

        return self.__class__(
            name=self.name,
            tracks=self.tracks,
            description=self.description,
            id=self.id,
            connector_track_ids=new_ids,
        )


@define(frozen=True)
class ConnectorTrackMapping:
    """Cross-connected-service entity mapping with confidence scoring.

    Tracks how entities are resolved across connectors with metadata
    about match quality and resolution method.
    """

    connector_name: str = field(validator=validators.instance_of(str))
    connector_track_id: str = field(validator=validators.instance_of(str))
    match_method: str = field(
        validator=validators.in_(["direct", "isrc", "mbid", "artist_title", "fuzzy"])
    )
    confidence: int = field(
        validator=[validators.instance_of(int), validators.ge(0), validators.le(100)]
    )
    metadata: Dict[str, Any] = field(factory=dict)


@define(frozen=True)
class PlaylistOperation:
    """Immutable playlist transformation definition.

    Defines operations that transform playlists while maintaining
    immutability and composition patterns.
    """

    name: str = field(validator=validators.instance_of(str))
    transform: Callable[[Playlist], Playlist] = field()

    def apply(self, playlist: Playlist) -> Playlist:
        """Apply this operation to a playlist."""
        return self.transform(playlist)

    def then(self, next_op: "PlaylistOperation") -> "PlaylistOperation":
        """Compose with another operation, returning a new operation."""

        def composed_transform(playlist: Playlist) -> Playlist:
            return next_op.apply(self.apply(playlist))

        return PlaylistOperation(
            name=f"{self.name} → {next_op.name}", transform=composed_transform
        )


# Common operations


def sort_by_attribute(attribute: str, reverse: bool = False) -> PlaylistOperation:
    """Create an operation that sorts tracks by a specific attribute."""

    def sort_transform(playlist: Playlist) -> Playlist:
        def get_attr(track: Track) -> Any:
            return getattr(track, attribute, None) or 0

        sorted_tracks = sorted(playlist.tracks, key=get_attr, reverse=reverse)
        return playlist.with_tracks(sorted_tracks)

    direction = "descending" if reverse else "ascending"
    return PlaylistOperation(
        name=f"Sort by {attribute} ({direction})", transform=sort_transform
    )


def filter_by_predicate(
    predicate: Callable[[Track], bool], name: str
) -> PlaylistOperation:
    """Create an operation that filters tracks by a predicate."""

    def filter_transform(playlist: Playlist) -> Playlist:
        filtered_tracks = [t for t in playlist.tracks if predicate(t)]
        return playlist.with_tracks(filtered_tracks)

    return PlaylistOperation(name=f"Filter: {name}", transform=filter_transform)
