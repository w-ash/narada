"""Core domain models for Narada music integration platform.

These models represent the central entities in our system, independent of
any external service implementation details.
"""

from datetime import datetime
from enum import Enum
from typing import List

from attrs import Factory, define


class InteractionType(str, Enum):
    """Types of user interactions with tracks."""

    PLAY = "play"
    LOVE = "love"
    SKIP = "skip"
    BLOCK = "block"


@define(frozen=True)
class ServiceIdentifiers:
    """Cross-service identifiers for a single entity."""

    spotify: str | None = None
    isrc: str | None = None
    mbid: str | None = None
    lastfm_url: str | None = None

    def has_path_to_lastfm(self) -> bool:
        """Check if we have sufficient data to identify on Last.fm."""
        return bool(self.mbid or self.lastfm_url)

    def has_path_to_spotify(self) -> bool:
        """Check if we have sufficient data to identify on Spotify."""
        return bool(self.spotify or self.isrc)


@define
class Track:
    """Core track entity with minimal required fields."""

    title: str
    artist_name: str
    album_name: str | None = None
    duration_ms: int | None = None
    release_date: datetime | None = None
    identifiers: ServiceIdentifiers = Factory(ServiceIdentifiers)

    def __str__(self) -> str:
        return f"{self.artist_name} - {self.title}"


@define
class Playlist:
    """Representation of a playlist with position management."""

    name: str
    description: str | None = None
    owner: str | None = None
    service: str | None = None
    service_id: str | None = None
    tracks: List[Track] = Factory(list)

    def add_track(self, track: Track, position: int | None = None) -> None:
        """Add a track at the specified position or at the end."""
        if position is not None:
            self.tracks.insert(position, track)
        else:
            self.tracks.append(track)

    def remove_track(self, track: Track) -> bool:
        """Remove a track from the playlist, return True if found and removed."""
        if track in self.tracks:
            self.tracks.remove(track)
            return True
        return False


@define
class UserInteraction:
    """Record of user interaction with a track."""

    track: Track
    interaction_type: InteractionType
    timestamp: datetime
    service: str

    @classmethod
    def play(
        cls, track: Track, service: str, timestamp: datetime | None = None
    ) -> "UserInteraction":
        """Factory method for creating a play interaction."""
        return cls(
            track=track,
            interaction_type=InteractionType.PLAY,
            timestamp=timestamp or datetime.now(),
            service=service,
        )

    @classmethod
    def love(
        cls, track: Track, service: str, timestamp: datetime | None = None
    ) -> "UserInteraction":
        """Factory method for creating a love interaction."""
        return cls(
            track=track,
            interaction_type=InteractionType.LOVE,
            timestamp=timestamp or datetime.now(),
            service=service,
        )
