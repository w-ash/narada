"""Core domain models for music entities and operations.

These immutable models form the foundation of our business logic,
enforcing invariants while enabling functional transformation patterns.
"""

from datetime import datetime
from typing import Any, TypeVar

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
    artists: list[Artist] = field(
        factory=list,
        validator=validators.deep_iterable(
            member_validator=validators.instance_of(Artist),
            iterable_validator=validators.min_len(1),
        ),
    )
    album: str | None = field(default=None)
    duration_ms: int | None = field(default=None)
    release_date: datetime | None = field(default=None)
    isrc: str | None = field(default=None)

    # Extended properties
    id: int | None = field(default=None)
    play_count: int | None = field(default=None)
    connector_track_ids: dict[str, str] = field(factory=dict)
    connector_metadata: dict[str, dict[str, Any]] = field(factory=dict)

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
            connector_metadata=self.connector_metadata.copy(),
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
            connector_metadata=self.connector_metadata.copy(),
        )

    def with_connector_metadata(
        self,
        connector: str,
        metadata: dict[str, Any],
    ) -> "Track":
        """Create a new track with additional connector metadata."""
        new_metadata = self.connector_metadata.copy()
        new_metadata[connector] = {**new_metadata.get(connector, {}), **metadata}

        return self.__class__(
            title=self.title,
            artists=self.artists,
            album=self.album,
            duration_ms=self.duration_ms,
            release_date=self.release_date,
            isrc=self.isrc,
            id=self.id,
            play_count=self.play_count,
            connector_track_ids=self.connector_track_ids.copy(),
            connector_metadata=new_metadata,
        )

    def get_connector_attribute(
        self,
        connector: str,
        attribute: str,
        default=None,
    ) -> Any:
        """Get a specific attribute from connector metadata."""
        connector_data = self.connector_metadata.get(connector, {})
        return connector_data.get(attribute, default)


@define(frozen=True)
class Playlist:
    """Playlists are persistent entities with DB/API identity and metadata.

    Playlists are a represention of a user-facing list of tracks to be played,
    stored sources or destinations for track collections. Unlike TrackLists, Playlists
    are persisted entities that can be shared, stored, and retrieved.


    Playlists maintain track ordering while supporting additional metadata and
    cross-connector track identifiers for resolution across
    different music services.
    """

    name: str = field(validator=validators.instance_of(str))
    tracks: list[Track] = field(factory=list)
    description: str | None = field(default=None)
    id: int | None = field(default=None)
    connector_track_ids: dict[str, str] = field(factory=dict)

    def with_tracks(self, tracks: list[Track]) -> "Playlist":
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
class TrackList:
    """Ephemeral, immutable collection of tracks for processing pipelines.

    Unlike Playlists, TrackLists are not persisted entities but rather
    intermediate processing artifacts that flow through transformation pipelines.
    """

    tracks: list[Track] = field(factory=list)
    metadata: dict[str, Any] = field(factory=dict)

    def with_tracks(self, tracks: list[Track]) -> "TrackList":
        """Create new TrackList with the given tracks."""
        return self.__class__(
            tracks=tracks,
            metadata=self.metadata.copy(),
        )

    def with_metadata(self, key: str, value: Any) -> "TrackList":
        """Add metadata to the TrackList."""
        new_metadata = self.metadata.copy()
        new_metadata[key] = value
        return self.__class__(tracks=self.tracks, metadata=new_metadata)

    @classmethod
    def from_playlist(cls, playlist: Playlist) -> "TrackList":
        """Create TrackList from a Playlist."""
        return cls(
            tracks=playlist.tracks,
            metadata={"source_playlist_name": playlist.name},
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
        validator=validators.in_(["direct", "isrc", "mbid", "artist_title", "fuzzy"]),
    )
    confidence: int = field(
        validator=[validators.instance_of(int), validators.ge(0), validators.le(100)],
    )
    metadata: dict[str, Any] = field(factory=dict)
