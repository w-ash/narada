"""Track-related domain entities.

Pure track representations and related value objects with zero external dependencies.
"""

from datetime import UTC, datetime
from typing import Any

import attrs
from attrs import define, field, validators


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

    # Core metadata
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
    connector_track_ids: dict[str, str] = field(factory=dict)
    connector_metadata: dict[str, dict[str, Any]] = field(factory=dict)

    def with_connector_track_id(self, connector: str, sid: str) -> "Track":
        """Create a new track with additional connector identifier."""
        new_ids = self.connector_track_ids.copy()
        new_ids[connector] = sid
        return attrs.evolve(self, connector_track_ids=new_ids)

    def with_id(self, db_id: int) -> "Track":
        """Set the internal database ID for this track."""
        if not isinstance(db_id, int) or db_id <= 0:
            raise ValueError(
                f"Invalid database ID: {db_id}. Must be a positive integer.",
            )
        return attrs.evolve(self, id=db_id)

    def with_connector_metadata(
        self,
        connector: str,
        metadata: dict[str, Any],
    ) -> "Track":
        """Create a new track with additional connector metadata."""
        new_metadata = self.connector_metadata.copy()
        new_metadata[connector] = {**new_metadata.get(connector, {}), **metadata}
        return attrs.evolve(self, connector_metadata=new_metadata)

    def with_like_status(
        self,
        service: str,
        is_liked: bool,
        timestamp: datetime | None = None,
    ) -> "Track":
        """Create a new track with updated like status for the specified service."""
        new_metadata = self.connector_metadata.copy()
        service_meta = new_metadata.get(service, {}).copy()

        service_meta["is_liked"] = is_liked
        if timestamp:
            service_meta["liked_at"] = timestamp.isoformat()

        new_metadata[service] = service_meta
        return attrs.evolve(self, connector_metadata=new_metadata)

    def is_liked_on(self, service: str) -> bool:
        """Check if track is liked/loved on the specified service."""
        return bool(self.connector_metadata.get(service, {}).get("is_liked", False))

    def get_liked_timestamp(self, service: str) -> datetime | None:
        """Get the timestamp when track was liked on the service."""
        iso_timestamp = self.connector_metadata.get(service, {}).get("liked_at")
        if not iso_timestamp:
            return None

        try:
            return datetime.fromisoformat(iso_timestamp)
        except ValueError:
            return None

    def get_connector_attribute(
        self,
        connector: str,
        attribute: str,
        default=None,
    ) -> Any:
        """Get a specific attribute from connector metadata."""
        return self.connector_metadata.get(connector, {}).get(attribute, default)


@define(frozen=True, slots=True)
class TrackLike:
    """Immutable representation of a track like/love interaction."""

    track_id: int
    service: str  # 'spotify', 'lastfm', 'internal'
    is_liked: bool = True  # Default to liked since most cases create likes
    liked_at: datetime | None = None
    last_synced: datetime | None = None
    id: int | None = None  # Database ID if available


@define(frozen=True, slots=True)
class TrackMetric:
    """Time-series metrics for tracks from external services."""

    track_id: int
    connector_name: str
    metric_type: str
    value: float
    collected_at: datetime = field(factory=lambda: datetime.now(UTC))
    id: int | None = None


@define(frozen=True, slots=True)
class ConnectorTrack:
    """External track representation from a specific music service."""

    connector_name: str
    connector_track_id: str
    title: str
    artists: list[Artist]
    album: str | None = None
    duration_ms: int | None = None
    isrc: str | None = None
    release_date: datetime | None = None
    raw_metadata: dict[str, Any] = field(factory=dict)
    last_updated: datetime = field(factory=lambda: datetime.now(UTC))
    id: int | None = None


@define(frozen=True)
class ConnectorTrackMapping:
    """Cross-connected-service entity mapping with confidence scoring.

    Tracks how entities are resolved across connectors with metadata
    about match quality and resolution method.
    """

    connector_name: str = field(validator=validators.instance_of(str))
    connector_track_id: str = field(validator=validators.instance_of(str))
    match_method: str = field(
        validator=validators.in_([
            "direct",  # Direct match where internal object was created from the connector
            "isrc",  # Matched by ISRC
            "mbid",  # Matched by MusicBrainz ID
            "artist_title",  # Matched by artist and title
        ]),
    )
    confidence: int = field(
        validator=[validators.instance_of(int), validators.ge(0), validators.le(100)],
    )
    metadata: dict[str, Any] = field(factory=dict)


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
    def from_playlist(cls, playlist: Any) -> "TrackList":  # Avoiding circular import
        """Create TrackList from a Playlist."""
        return cls(
            tracks=playlist.tracks,
            metadata={"source_playlist_name": playlist.name},
        )