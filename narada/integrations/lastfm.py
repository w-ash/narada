"""Last.fm service connector with domain model conversion."""

import asyncio
import os
from typing import Optional

import backoff
import pylast
from attrs import define

from narada.config import get_logger, resilient_operation
from narada.core.models import Artist, Track

# Get contextual logger with service binding
logger = get_logger(__name__).bind(service="lastfm")


@define(frozen=True)
class LastFmPlayCount:
    """Value object for Last.fm play count data."""

    user_play_count: int = 0
    global_play_count: int = 0
    track_url: Optional[str] = None


class LastFmConnector:
    """Thin wrapper around pylast with domain model conversion.

    Handles authentication and provides methods to:
    - Fetch user and global play counts
    - Resolve tracks via MBID or artist/title search
    - Batch retrieve play counts for playlist optimization

    All methods handle rate limiting via backoff decorator.
    """

    def __init__(
        self, api_key: Optional[str] = None, username: Optional[str] = None
    ) -> None:
        """Initialize Last.fm client with API credentials."""
        logger.debug("Initializing Last.fm connector")

        # Use environment variables by default, with fallback to passed parameters
        self.api_key = api_key or os.getenv("LASTFM_KEY")
        self.api_secret = os.getenv("LASTFM_SECRET")
        self.username = username or os.getenv("LASTFM_USERNAME")

        if not self.api_key or not self.api_secret:
            logger.warning("Last.fm API credentials not configured")
            self.client = None
            return

        self.client = pylast.LastFMNetwork(
            api_key=str(self.api_key),
            api_secret=str(self.api_secret),
        )

        # Set user agent for API courtesy
        self.client.session_key = None
        pylast.HEADERS["User-Agent"] = "Narada/0.1.0 (Music Metadata Integration)"

    @resilient_operation("get_track_play_count")
    @backoff.on_exception(backoff.expo, pylast.NetworkError, max_tries=3)
    async def get_track_play_count(
        self, artist_name: str, track_title: str, username: Optional[str] = None
    ) -> LastFmPlayCount:
        """Get play count for a track by artist and title.

        Args:
            artist_name: Artist name
            track_title: Track title
            username: Optional username (defaults to configured user)

        Returns:
            LastFmPlayCount with user and global counts
        """
        user = username or self.username

        if not user:
            logger.warning("No username provided for Last.fm play count")
            return LastFmPlayCount()

        if not self.client:
            logger.warning("Last.fm client not initialized - missing API credentials")
            return LastFmPlayCount()

        try:
            # Run in thread pool to avoid blocking
            track = await asyncio.to_thread(
                self.client.get_track, artist_name, track_title
            )

            # Get user play count
            track.username = user
            user_playcount = await asyncio.to_thread(
                lambda: int(track.get_userplaycount() or 0)
            )

            # Get global play count (may be unavailable)
            try:
                global_playcount = await asyncio.to_thread(
                    lambda: int(track.get_playcount() or 0)
                )
            except (pylast.WSError, TypeError):
                global_playcount = 0

            # Get track URL
            track_url = await asyncio.to_thread(lambda: track.get_url())

            return LastFmPlayCount(
                user_play_count=user_playcount,
                global_play_count=global_playcount,
                track_url=track_url,
            )

        except pylast.WSError as e:
            if "not found" in str(e).lower():
                logger.debug(
                    "Track not found on Last.fm", artist=artist_name, track=track_title
                )
                return LastFmPlayCount()
            raise
        except Exception as e:
            logger.exception(
                "Error getting Last.fm play count",
                artist=artist_name,
                track=track_title,
                error=str(e),
            )
            return LastFmPlayCount()

    @resilient_operation("get_mbid_play_count")
    @backoff.on_exception(backoff.expo, pylast.NetworkError, max_tries=3)
    async def get_mbid_play_count(
        self, mbid: str, username: Optional[str] = None
    ) -> LastFmPlayCount:
        """Get play count for a track by MusicBrainz ID.

        Args:
            mbid: MusicBrainz track ID
            username: Optional username (defaults to configured user)

        Returns:
            LastFmPlayCount with user and global counts
        """
        user = username or self.username

        if not user:
            logger.warning("No username provided for Last.fm play count")
            return LastFmPlayCount()

        if not self.client:
            logger.warning("Last.fm client not initialized - missing API credentials")
            return LastFmPlayCount()

        try:
            # Run in thread pool to avoid blocking
            track = await asyncio.to_thread(self.client.get_track_by_mbid, mbid)

            # Get user play count
            track.username = user
            user_playcount = await asyncio.to_thread(
                lambda: int(track.get_userplaycount() or 0)
            )

            # Get global play count (may be unavailable)
            try:
                global_playcount = await asyncio.to_thread(
                    lambda: int(track.get_playcount() or 0)
                )
            except (pylast.WSError, TypeError):
                global_playcount = 0

            # Get track URL
            track_url = await asyncio.to_thread(lambda: track.get_url())

            return LastFmPlayCount(
                user_play_count=user_playcount,
                global_play_count=global_playcount,
                track_url=track_url,
            )

        except pylast.WSError as e:
            if "not found" in str(e).lower():
                logger.debug("Track not found on Last.fm with MBID", mbid=mbid)
                return LastFmPlayCount()
            raise
        except Exception as e:
            logger.exception(
                "Error getting Last.fm play count by MBID", mbid=mbid, error=str(e)
            )
            return LastFmPlayCount()

    @resilient_operation("batch_get_track_play_counts")
    async def batch_get_track_play_counts(
        self, tracks: list[Track], username: Optional[str] = None
    ) -> dict[int, LastFmPlayCount]:
        """Batch retrieve play counts for multiple tracks.

        Optimizes API calls through parallel requests.

        Args:
            tracks: List of domain Track models
            username: Optional username (defaults to configured user)

        Returns:
            dictionary mapping track ID to play count info
        """
        user = username or self.username
        results = {}

        # Define coroutines based on available identifiers
        coroutines = []
        for track in tracks:
            track_id = track.id
            if track_id is None:
                continue

            # Try MBID resolution first if available
            mbid = track.connector_track_ids.get("musicbrainz")
            if mbid:
                coro = self.get_mbid_play_count(mbid, user)
                coroutines.append((track_id, coro))
                continue

            # Fall back to artist/title search
            if track.artists and track.title:
                artist_name = track.artists[0].name
                coro = self.get_track_play_count(artist_name, track.title, user)
                coroutines.append((track_id, coro))

        # Execute all requests in parallel with rate limiting
        # Use semaphore to limit concurrency to 3 requests at a time
        semaphore = asyncio.Semaphore(3)

        async def bounded_fetch(track_id, coro):
            async with semaphore:
                # Add 0.25s delay between requests to be nice to Last.fm API
                await asyncio.sleep(0.25)
                result = await coro
                return track_id, result

        fetch_tasks = [bounded_fetch(t_id, coro) for t_id, coro in coroutines]
        completed = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        # Process results
        for item in completed:
            if isinstance(item, Exception):
                logger.error(f"Error in batch play count fetch: {item}")
                continue
            if not isinstance(item, tuple):
                logger.error(f"Unexpected result type: {type(item)}")
                continue

            track_id, play_count = item
            results[track_id] = play_count

        return results


def convert_lastfm_track_to_domain(lastfm_track: pylast.Track) -> Track:
    """Convert Last.fm track data to domain model.

    Args:
        lastfm_track: Raw track data from Last.fm API

    Returns:
        Domain Track model with available metadata
    """
    try:
        # Get basic metadata
        title = lastfm_track.get_title()
        artist = lastfm_track.get_artist()
        artist_name = artist.get_name() if artist else None

        # Try to get album
        try:
            album_obj = lastfm_track.get_album()
            album = album_obj.get_name() if album_obj else None
        except (pylast.WSError, AttributeError):
            album = None

        # Create domain model
        track = Track(
            title=title or "",
            artists=[Artist(name=artist_name or "")] if artist_name else [],
            album=album,
        )

        # Try to get MBID
        try:
            mbid = lastfm_track.get_mbid()
            if mbid:
                track = track.with_connector_track_id("musicbrainz", mbid)
        except (pylast.WSError, AttributeError):
            pass

        # Add Last.fm URL
        track = track.with_connector_track_id("lastfm", lastfm_track.get_url())

        return track
    except Exception as e:
        logger.exception(f"Error converting Last.fm track: {e}")
        raise ValueError(f"Cannot convert Last.fm track: {e}")
