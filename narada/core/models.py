"""Core domain models for music entities and operations.

These immutable models form the foundation of our business logic,
enforcing invariants while enabling functional transformation patterns.
"""

from datetime import UTC, datetime
from typing import Any, TypeVar

import attr
import attrs
from attrs import define, field, validators

# Type variables for generic operations
T = TypeVar("T")
P = TypeVar("P", bound="Playlist")


@define(frozen=True, slots=True)
class ConnectorPlaylistItem:
    """Represents a track within an external service playlist with its position metadata."""

    # Track identity - just the ID, not the full object
    connector_track_id: str

    # Position information
    position: int
    added_at: str | None = None
    added_by_id: str | None = None

    # Any service-specific data
    extras: dict[str, Any] = field(factory=dict)


@define(frozen=True, slots=True)
class SyncCheckpoint:
    """Represents the state of a synchronization process."""

    user_id: str
    service: str
    entity_type: str  # 'likes', 'plays'
    last_timestamp: datetime | None = None
    cursor: str | None = None  # For pagination/continuation
    id: int | None = None

    def with_update(
        self,
        timestamp: datetime,
        cursor: str | None = None,
    ) -> "SyncCheckpoint":
        """Create a new checkpoint with updated state."""
        return self.__class__(
            user_id=self.user_id,
            service=self.service,
            entity_type=self.entity_type,
            last_timestamp=timestamp,
            cursor=cursor or self.cursor,
            id=self.id,
        )


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
class TrackPlay:
    """Immutable record of a track play event."""

    track_id: int
    service: str
    played_at: datetime
    ms_played: int | None = None
    context: dict[str, Any] | None = None
    id: int | None = None


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
    match_method: str = attr.field(
        validator=attr.validators.in_([
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


@define(frozen=True, slots=True)
class Playlist:
    """Playlists are persistent entities with DB/API identity and metadata.

    Playlists are a representation of a user-facing list of tracks to be played,
    stored sources or destinations for track collections. Unlike TrackLists, Playlists
    are persisted entities that can be shared, stored, and retrieved.

    Playlists maintain track ordering while supporting additional metadata and
    cross-connector playlist identifiers for resolution across
    different music services.
    """

    name: str = field(validator=validators.instance_of(str))
    tracks: list[Track] = field(factory=list)
    description: str | None = field(default=None)
    # The internal database ID - source of truth for our system
    id: int | None = field(default=None)
    # External service IDs (spotify, apple_music, etc) - NOT for internal DB ID
    connector_playlist_ids: dict[str, str] = field(factory=dict)

    def with_tracks(self, tracks: list[Track]) -> "Playlist":
        """Create a new playlist with the given tracks."""
        return self.__class__(
            name=self.name,
            tracks=tracks,
            description=self.description,
            id=self.id,
            connector_playlist_ids=self.connector_playlist_ids.copy(),
        )

    def with_connector_playlist_id(
        self,
        connector: str,
        external_id: str,
    ) -> "Playlist":
        """Create a new playlist with additional connector identifier.

        Args:
            connector: The name of the external service ("spotify", "apple_music", etc)
                       Do not use "db" or "internal" here - use the id field for that.
            external_id: The ID of this playlist in the external service
        """
        if connector in ("db", "internal"):
            raise ValueError(
                f"Cannot use '{connector}' as connector name - use the id field instead",
            )

        new_ids = self.connector_playlist_ids.copy()
        new_ids[connector] = external_id

        return self.__class__(
            name=self.name,
            tracks=self.tracks,
            description=self.description,
            id=self.id,
            connector_playlist_ids=new_ids,
        )

    def with_id(self, db_id: int) -> "Playlist":
        """Set the internal database ID for this playlist.

        This is the source of truth for playlist identity in our system.
        """
        if not isinstance(db_id, int) or db_id <= 0:
            raise ValueError(
                f"Invalid database ID: {db_id}. Must be a positive integer.",
            )

        return self.__class__(
            name=self.name,
            tracks=self.tracks,
            description=self.description,
            id=db_id,
            connector_playlist_ids=self.connector_playlist_ids.copy(),
        )


@define(frozen=True, slots=True)
class ConnectorPlaylist:
    """External service-specific playlist representation."""

    connector_name: str
    connector_playlist_id: str
    name: str
    description: str | None = None
    items: list[ConnectorPlaylistItem] = field(
        factory=list
    )  # Single field for track items
    owner: str | None = None
    owner_id: str | None = None
    is_public: bool = False
    collaborative: bool = False
    follower_count: int | None = None
    raw_metadata: dict[str, Any] = field(factory=dict)
    last_updated: datetime = field(factory=lambda: datetime.now(UTC))
    id: int | None = None

    @property
    def track_ids(self) -> list[str]:
        """Get all track IDs in this playlist."""
        return [item.connector_track_id for item in self.items]


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


@define(frozen=True, slots=True)
class PlaylistTrack:
    """Playlist track ordering and metadata."""

    playlist_id: int
    track_id: int
    sort_key: str
    added_at: datetime | None = None
    id: int | None = None


@define(frozen=True)
class WorkflowResult:
    """Immutable result of a workflow execution with associated metrics."""

    tracks: list[Track] = field(factory=list)
    metrics: dict[str, dict[int, Any]] = field(
        factory=dict,
    )  # metric_name -> {track_id(int) -> value}
    workflow_name: str = field(default="")
    execution_time: float = field(default=0.0)

    def get_metric(
        self,
        track_id: int | None,
        metric_name: str,
        default: Any = None,
    ) -> Any:
        """Get specific metric value for a track."""
        if track_id is None:
            return None
        # Look up metric using integer track_id (consistent with rest of system)
        return self.metrics.get(metric_name, {}).get(track_id, default)

    def with_metric(self, metric_name: str, values: dict[int, Any]) -> "WorkflowResult":
        """Add or update a metric, returning a new instance."""
        metrics = self.metrics.copy()
        # Store metrics with integer keys, consistent with the rest of the system
        metrics[metric_name] = values
        return self.__class__(
            tracks=self.tracks,
            metrics=metrics,
            workflow_name=self.workflow_name,
            execution_time=self.execution_time,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to serializable dictionary for API responses."""
        return {
            "workflow_name": self.workflow_name,
            "execution_time": self.execution_time,
            "track_count": len(self.tracks),
            "tracks": [
                {
                    "id": t.id,
                    "title": t.title,
                    "artists": [a.name for a in t.artists],
                    "metrics": {
                        name: values.get(t.id)
                        for name, values in self.metrics.items()
                        if t.id and t.id in values
                    }
                    if t.id
                    else {},
                }
                for t in self.tracks
            ],
        }


def ensure_utc(dt: datetime | None) -> datetime | None:
    """Ensure datetime is timezone-aware with UTC."""
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt