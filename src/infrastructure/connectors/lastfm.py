"""Last.fm API integration for Narada music metadata.

This module provides a clean interface to the Last.fm API through the pylast library
(https://github.com/pylast/pylast), converting between Last.fm track representations
and domain models. It implements rate limiting, error handling, and batch processing
for efficient data retrieval.

Key components:
- LastFMConnector: Main client with track info retrieval and love operations
- LastFMTrackInfo: Immutable container for Last.fm track metadata
- LastFmMetricResolver: Resolves Last.fm-specific track metrics
- Batch processing utilities: Efficient retrieval of track info for multiple tracks

The module supports:
- Track information retrieval by MBID or artist/title
- User-specific playcount and loved status
- Global playcount and listener metrics
- Loving tracks on Last.fm
"""

import asyncio
from collections.abc import Callable
import contextlib
from datetime import datetime
import os
from typing import Any, ClassVar

from attrs import define, field
import backoff
import pylast

from src.domain.entities import (
    Artist,
    PlayRecord,
    Track,
    create_lastfm_play_record,
)
from src.infrastructure.config import get_config, get_logger, resilient_operation
from src.infrastructure.connectors.base_connector import (
    BaseMetricResolver,
    BatchProcessor,
    register_metrics,
)
from src.infrastructure.connectors.protocols import ConnectorConfig

# Get contextual logger with service binding
logger = get_logger(__name__).bind(service="lastfm")


@define(frozen=True, slots=True)
class LastFMTrackInfo:
    """Complete track information from Last.fm API.

    Immutable container for all track-related data from Last.fm,
    including metadata, artist information, and user-specific metrics.

    Attributes:
        lastfm_title: Track title as known by Last.fm
        lastfm_mbid: MusicBrainz ID for the track if available
        lastfm_url: Last.fm URL for the track
        lastfm_duration: Track duration in milliseconds
        lastfm_artist_name: Artist name as known by Last.fm
        lastfm_artist_mbid: MusicBrainz ID for the artist if available
        lastfm_artist_url: Last.fm URL for the artist
        lastfm_album_name: Album name as known by Last.fm
        lastfm_album_mbid: MusicBrainz ID for the album if available
        lastfm_album_url: Last.fm URL for the album
        lastfm_user_playcount: Number of times the user has played this track
        lastfm_global_playcount: Total play count across all Last.fm users
        lastfm_listeners: Number of unique listeners on Last.fm
        lastfm_user_loved: Whether the user has "loved" this track on Last.fm
    """

    # Basic track info
    lastfm_title: str | None = field(default=None)
    lastfm_mbid: str | None = field(default=None)
    lastfm_url: str | None = field(default=None)
    lastfm_duration: int | None = field(default=None)

    # Artist info
    lastfm_artist_name: str | None = field(default=None)
    lastfm_artist_mbid: str | None = field(default=None)
    lastfm_artist_url: str | None = field(default=None)

    # Album info
    lastfm_album_name: str | None = field(default=None)
    lastfm_album_mbid: str | None = field(default=None)
    lastfm_album_url: str | None = field(default=None)

    # Metrics - None means "unknown/not fetched", 0 means "zero plays"
    lastfm_user_playcount: int | None = field(default=None)
    lastfm_global_playcount: int | None = field(default=None)
    lastfm_listeners: int | None = field(default=None)
    lastfm_user_loved: bool = field(default=False)

    # Field extraction mapping for pylast Track objects
    EXTRACTORS: ClassVar[dict[str, Callable]] = {
        "lastfm_title": lambda t: t.get_title(),
        "lastfm_mbid": lambda t: t.get_mbid(),
        "lastfm_url": lambda t: t.get_url(),
        "lastfm_duration": lambda t: t.get_duration(),
        "lastfm_artist_name": lambda t: t.get_artist() and t.get_artist().get_name(),
        "lastfm_artist_mbid": lambda t: t.get_artist() and t.get_artist().get_mbid(),
        "lastfm_artist_url": lambda t: t.get_artist() and t.get_artist().get_url(),
        "lastfm_album_name": lambda t: t.get_album() and t.get_album().get_name(),
        "lastfm_album_mbid": lambda t: t.get_album() and t.get_album().get_mbid(),
        "lastfm_album_url": lambda t: t.get_album() and t.get_album().get_url(),
        "lastfm_user_playcount": lambda t: int(t.get_userplaycount() or 0)
        if t.username
        else None,
        "lastfm_user_loved": lambda t: bool(t.get_userloved()) if t.username else False,
        "lastfm_global_playcount": lambda t: int(t.get_playcount() or 0),
        "lastfm_listeners": lambda t: int(t.get_listener_count() or 0),
    }

    @classmethod
    def empty(cls) -> "LastFMTrackInfo":
        """Create an empty track info object for tracks not found."""
        return cls()

    @classmethod
    def from_pylast_track(cls, track: pylast.Track) -> "LastFMTrackInfo":
        """Create LastFMTrackInfo from a pylast Track object."""
        # Extract all fields with error handling
        with contextlib.suppress(pylast.WSError, AttributeError, TypeError, ValueError):
            info = {
                field: extractor(track)
                for field, extractor in cls.EXTRACTORS.items()
                if extractor(track) is not None
            }
            return cls(**info)

        # Return empty object on error
        return cls.empty()

    def to_domain_track(self) -> Track:
        """Convert Last.fm track info to domain track model."""
        # Create base track with essential fields
        track = Track(
            title=self.lastfm_title or "",
            artists=[Artist(name=self.lastfm_artist_name)]
            if self.lastfm_artist_name
            else [],
            album=self.lastfm_album_name,
            duration_ms=self.lastfm_duration,
        )

        # Add connector IDs
        if self.lastfm_mbid:
            track = track.with_connector_track_id("musicbrainz", self.lastfm_mbid)

        if self.lastfm_url:
            track = track.with_connector_track_id("lastfm", self.lastfm_url)

        # Add all non-None LastFM metadata
        from attrs import asdict

        lastfm_metadata = {
            k: v
            for k, v in asdict(self).items()
            if k.startswith("lastfm_") and v is not None
        }

        if lastfm_metadata:
            track = track.with_connector_metadata("lastfm", lastfm_metadata)

        return track


@define(slots=True)
class LastFMConnector:
    """Last.fm API connector with domain model conversion.

    Implements the TrackMatcher protocol for identity resolution.
    """

    api_key: str | None = field(default=None)
    api_secret: str | None = field(default=None)
    lastfm_username: str | None = field(default=None)
    client: pylast.LastFMNetwork | None = field(default=None, init=False, repr=False)
    batch_processor: BatchProcessor = field(init=False, repr=False)
    connector_name: str = "lastfm"

    # Constants for API communication
    USER_AGENT: ClassVar[str] = "Narada/0.1.0 (Music Metadata Integration)"

    def __attrs_post_init__(self) -> None:
        """Initialize Last.fm client with API credentials."""
        # Use environment variables by default, with fallback to passed parameters
        self.api_key = self.api_key or os.getenv("LASTFM_KEY")
        self.api_secret = self.api_secret or os.getenv("LASTFM_SECRET")
        self.lastfm_username = self.lastfm_username or os.getenv("LASTFM_USERNAME")

        # Initialize the batch processor with config values
        self.batch_processor = BatchProcessor[
            Track,
            tuple[int, LastFMTrackInfo | None],
        ](
            batch_size=get_config("LASTFM_API_BATCH_SIZE"),
            concurrency_limit=get_config("LASTFM_API_CONCURRENCY"),
            retry_count=get_config("LASTFM_API_RETRY_COUNT"),
            retry_base_delay=get_config("LASTFM_API_RETRY_BASE_DELAY"),
            retry_max_delay=get_config("LASTFM_API_RETRY_MAX_DELAY"),
            request_delay=get_config("LASTFM_API_REQUEST_DELAY"),
            logger_instance=logger,
        )

        if not self.api_key or not self.api_secret:
            return

        # For write operations, we need username and password
        lastfm_password = os.getenv("LASTFM_PASSWORD")

        if self.lastfm_username and lastfm_password:
            # Full authentication for write operations
            self.client = pylast.LastFMNetwork(
                api_key=str(self.api_key),
                api_secret=str(self.api_secret),
                username=self.lastfm_username,
                password_hash=pylast.md5(lastfm_password),
            )
        else:
            # Read-only client for track info retrieval
            self.client = pylast.LastFMNetwork(
                api_key=str(self.api_key),
                api_secret=str(self.api_secret),
            )

        # Set user agent for API courtesy
        pylast.HEADERS["User-Agent"] = self.USER_AGENT

    async def _fetch_track(
        self,
        mbid: str | None = None,
        artist_name: str | None = None,
        track_title: str | None = None,
    ) -> tuple[str, str, pylast.Track]:
        """Fetch a track from Last.fm using the most appropriate method."""
        if not self.client:
            raise ValueError("Last.fm client not initialized")

        # Try MBID lookup first (preferred)
        if mbid:
            return (
                "mbid",
                mbid,
                await asyncio.to_thread(self.client.get_track_by_mbid, mbid),
            )

        # Fall back to artist/title lookup
        if artist_name and track_title:
            return (
                "artist/title",
                f"{artist_name} - {track_title}",
                await asyncio.to_thread(
                    self.client.get_track,
                    artist_name,
                    track_title,
                ),
            )

        # No valid lookup parameters
        raise ValueError("Either mbid or (artist_name + track_title) must be provided")

    @resilient_operation("get_lastfm_track_info")
    @backoff.on_exception(
        backoff.expo,
        (pylast.NetworkError, pylast.MalformedResponseError, pylast.WSError),
        max_tries=get_config("LASTFM_API_RETRY_COUNT"),
        base=get_config("LASTFM_API_RETRY_BASE_DELAY"),
        max_value=get_config("LASTFM_API_RETRY_MAX_DELAY"),
        jitter=backoff.full_jitter,
    )
    async def get_lastfm_track_info(
        self,
        artist_name: str | None = None,
        track_title: str | None = None,
        mbid: str | None = None,
        lastfm_username: str | None = None,
    ) -> LastFMTrackInfo:
        """Get comprehensive track information from Last.fm."""
        if not self.client:
            return LastFMTrackInfo.empty()

        user = lastfm_username or self.lastfm_username

        try:
            # Fetch track using appropriate method
            _, _, track = await self._fetch_track(mbid, artist_name, track_title)

            # Set username for user-specific data
            track.username = user

            # Convert to domain object
            return await asyncio.to_thread(LastFMTrackInfo.from_pylast_track, track)

        except ValueError:
            raise
        except pylast.WSError as e:
            if "not found" in str(e).lower():
                return LastFMTrackInfo.empty()
            raise
        except Exception:
            return LastFMTrackInfo.empty()

    @resilient_operation("batch_get_track_info")
    async def batch_get_track_info(
        self,
        tracks: list[Track],
        lastfm_username: str | None = None,
        progress_callback: Callable[[str, dict], None] | None = None,
    ) -> dict[int, LastFMTrackInfo]:
        """Batch retrieve Last.fm track information for multiple tracks."""
        if not tracks or not self.client:
            return {}

        user = lastfm_username or self.lastfm_username
        if not user:
            return {}

        async def process_track(track: Track) -> tuple[int, LastFMTrackInfo | None]:
            """Process a single track."""
            if track.id is None:
                return -1, None

            # Try MusicBrainz ID first, fall back to artist/title
            mbid = track.connector_track_ids.get("musicbrainz")
            artist_name = track.artists[0].name if track.artists else None

            if mbid:
                return track.id, await self.get_lastfm_track_info(
                    mbid=mbid,
                    lastfm_username=user,
                )
            elif artist_name:
                return track.id, await self.get_lastfm_track_info(
                    artist_name=artist_name,
                    track_title=track.title,
                    lastfm_username=user,
                )
            else:
                return track.id, LastFMTrackInfo.empty()

        # Create a wrapper for progress callback to ensure proper task context
        def wrapped_progress_callback(event_type: str, event_data: dict) -> None:
            if progress_callback:
                # Ensure task_name is properly set for workflow integration
                event_data = event_data.copy()
                if "task_name" not in event_data:
                    event_data["task_name"] = "enrich"
                progress_callback(event_type, event_data)

        # Use the pre-configured batch processor
        batch_results = await self.batch_processor.process(
            tracks,
            process_track,
            progress_callback=wrapped_progress_callback,
            progress_task_name="enrich",
            progress_description="Enriching tracks with Last.fm data",
        )

        # Filter valid results
        return {
            track_id: info
            for track_id, info in batch_results
            if track_id != -1 and info and info.lastfm_url
        }

    @resilient_operation("love_track_on_lastfm")
    @backoff.on_exception(
        backoff.expo,
        (pylast.NetworkError, pylast.MalformedResponseError, pylast.WSError),
        max_tries=3,
        jitter=backoff.full_jitter,
    )
    async def love_track(
        self,
        artist_name: str,
        track_title: str,
        username: str | None = None,
    ) -> bool:
        """Love a track on Last.fm.

        Args:
            artist_name: Name of the artist
            track_title: Title of the track
            username: Last.fm username (defaults to configured username)

        Returns:
            True if successful, False otherwise
        """
        if not self.client:
            logger.error("Last.fm client not initialized")
            return False

        # Check if client is authenticated for write operations
        if not hasattr(self.client, "username") or not self.client.username:
            logger.error(
                "Last.fm client not authenticated - set LASTFM_PASSWORD environment variable"
            )
            return False

        # Use provided username or fall back to configured one
        user = username or self.lastfm_username

        if not user:
            logger.error("No Last.fm username provided or configured")
            return False

        try:
            # Get Last.fm user
            lastfm_user = await asyncio.to_thread(self.client.get_user, user)
            if not lastfm_user:
                logger.error(f"Could not get Last.fm user: {user}")
                return False

            # Get track
            lastfm_track = await asyncio.to_thread(
                self.client.get_track,
                artist_name,
                track_title,
            )

            # Love the track
            await asyncio.to_thread(lastfm_track.love)
            logger.info(f"Loved track on Last.fm: {artist_name} - {track_title}")
            return True

        except pylast.WSError as e:
            if "not found" in str(e).lower():
                logger.warning(
                    f"Track not found on Last.fm: {artist_name} - {track_title}"
                )
            else:
                logger.error(f"Last.fm API error: {e}")
            return False
        except Exception as e:
            logger.exception(f"Error loving track on Last.fm: {e}")
            return False

    @resilient_operation("get_recent_tracks")
    @backoff.on_exception(
        backoff.expo,
        (pylast.NetworkError, pylast.MalformedResponseError, pylast.WSError),
        max_tries=get_config("LASTFM_API_RETRY_COUNT"),
        base=get_config("LASTFM_API_RETRY_BASE_DELAY"),
        max_value=get_config("LASTFM_API_RETRY_MAX_DELAY"),
        jitter=backoff.full_jitter,
    )
    async def get_recent_tracks(
        self,
        username: str | None = None,
        limit: int = 200,
        page: int = 1,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
    ) -> list[PlayRecord]:
        """Get recent tracks from Last.fm user.getRecentTracks API.

        Args:
            username: Last.fm username (defaults to configured username)
            limit: Number of tracks per page (default 200, max 200)
            page: Page number to fetch (1-based)
            from_time: Beginning timestamp (UTC)
            to_time: End timestamp (UTC)

        Returns:
            List of PlayRecord objects with Last.fm metadata
        """
        if not self.client:
            logger.error("Last.fm client not initialized")
            return []

        user = username or self.lastfm_username
        if not user:
            logger.error("No Last.fm username provided or configured")
            return []

        # Validate limit
        limit = min(max(1, limit), 200)

        try:
            # Get Last.fm user
            lastfm_user = await asyncio.to_thread(self.client.get_user, user)
            if not lastfm_user:
                logger.error(f"Could not get Last.fm user: {user}")
                return []

            # Build parameters for API call
            params = {
                "limit": limit,
            }

            # Add time range if specified (convert to UNIX timestamps)
            if from_time:
                params["time_from"] = int(from_time.timestamp())
            if to_time:
                params["time_to"] = int(to_time.timestamp())

            # Get recent tracks using pylast
            recent_tracks = await asyncio.to_thread(
                lastfm_user.get_recent_tracks,
                limit=params["limit"],
                time_from=params.get("time_from"),
                time_to=params.get("time_to"),
            )

            # Convert pylast Track objects to LastfmPlayRecord
            play_records = []
            for track_info in recent_tracks:
                # track_info is a tuple: (Track, PlayedTime)
                if len(track_info) >= 2:
                    track, played_time = track_info[0], track_info[1]

                    # Skip currently playing tracks (they have no timestamp)
                    if not played_time:
                        continue

                    # Parse the timestamp - pylast returns datetime objects
                    from datetime import UTC

                    scrobbled_at = (
                        played_time
                        if isinstance(played_time, datetime)
                        else datetime.fromtimestamp(int(played_time), tz=UTC)
                    )

                    # Extract track metadata
                    track_name = (
                        track.get_title() if hasattr(track, "get_title") else str(track)
                    )
                    artist_name = (
                        track.get_artist().get_name()
                        if hasattr(track, "get_artist") and track.get_artist()
                        else ""
                    )
                    album_name = (
                        track.get_album().get_name()
                        if hasattr(track, "get_album") and track.get_album()
                        else None
                    )

                    # Extract URLs and MBIDs
                    track_url = track.get_url() if hasattr(track, "get_url") else None
                    track_mbid = (
                        track.get_mbid() if hasattr(track, "get_mbid") else None
                    )

                    artist_url = (
                        track.get_artist().get_url()
                        if hasattr(track, "get_artist") and track.get_artist()
                        else None
                    )
                    artist_mbid = (
                        track.get_artist().get_mbid()
                        if hasattr(track, "get_artist") and track.get_artist()
                        else None
                    )

                    album_url = (
                        track.get_album().get_url()
                        if hasattr(track, "get_album") and track.get_album()
                        else None
                    )
                    album_mbid = (
                        track.get_album().get_mbid()
                        if hasattr(track, "get_album") and track.get_album()
                        else None
                    )

                    # Create unified PlayRecord using factory method
                    play_record = create_lastfm_play_record(
                        artist_name=artist_name,
                        track_name=track_name,
                        album_name=album_name,
                        scrobbled_at=scrobbled_at,
                        lastfm_track_url=track_url,
                        lastfm_artist_url=artist_url,
                        lastfm_album_url=album_url,
                        mbid=track_mbid,
                        artist_mbid=artist_mbid,
                        album_mbid=album_mbid,
                        streamable=False,  # Not available in recent tracks API
                        loved=False,  # Not available in recent tracks API
                        api_page=page,
                        raw_data={
                            "track_url": track_url,
                            "artist_url": artist_url,
                            "album_url": album_url,
                        },
                    )

                    play_records.append(play_record)

            logger.info(
                f"Retrieved {len(play_records)} recent tracks for user {user}",
                page=page,
                limit=limit,
                from_time=from_time,
                to_time=to_time,
            )

            return play_records

        except pylast.WSError as e:
            if "not found" in str(e).lower():
                logger.warning(f"User not found: {user}")
                return []
            logger.error(f"Last.fm API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Error fetching recent tracks: {e}")
            raise


@define(frozen=True, slots=True)
class LastFmMetricResolver(BaseMetricResolver):
    """Resolves LastFM metrics from persistence layer."""

    # Map metric names to connector metadata fields
    FIELD_MAP: ClassVar[dict[str, str]] = {
        "lastfm_user_playcount": "lastfm_user_playcount",
        "lastfm_global_playcount": "lastfm_global_playcount",
        "lastfm_listeners": "lastfm_listeners",
    }

    # Connector name for database operations
    CONNECTOR: ClassVar[str] = "lastfm"


def get_connector_config() -> ConnectorConfig:
    """Last.fm connector configuration."""
    return {
        "extractors": {
            "lastfm_user_playcount": lambda obj: _extract_metric(
                obj,
                ["lastfm_user_playcount", "userplaycount"],
            ),
            "lastfm_global_playcount": lambda obj: _extract_metric(
                obj,
                ["lastfm_global_playcount", "playcount"],
            ),
            "lastfm_listeners": lambda obj: _extract_metric(
                obj,
                ["lastfm_listeners", "listeners"],
            ),
        },
        "dependencies": ["musicbrainz"],
        "factory": lambda _params: LastFMConnector(),
        "metrics": LastFmMetricResolver.FIELD_MAP,
    }


def _extract_metric(obj: Any, field_names: list[str]) -> int | None:
    """Extract a metric value from various object types."""
    # First check for direct attribute access
    for field_name in field_names:
        if hasattr(obj, field_name) and getattr(obj, field_name) is not None:
            return getattr(obj, field_name)

    # Then check metadata dictionary access
    if hasattr(obj, "metadata"):
        for field_name in field_names:
            if field_name in obj.metadata and obj.metadata[field_name] is not None:
                return obj.metadata[field_name]

    # Finally check dictionary access
    if hasattr(obj, "get"):
        for field_name in field_names:
            value = obj.get(field_name)
            if value is not None:
                return value

    return None


# Register all metric resolvers at once
register_metrics(LastFmMetricResolver(), LastFmMetricResolver.FIELD_MAP)
