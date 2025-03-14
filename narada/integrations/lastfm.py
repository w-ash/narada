"""Last.fm service connector with domain model conversion."""

import asyncio
import os

from attrs import define
import backoff
import pylast

from narada.config import get_logger, resilient_operation
from narada.core.models import Artist, Track

# Get contextual logger with service binding
logger = get_logger(__name__).bind(service="lastfm")


@define(frozen=True)
class LastFmPlayCount:
    """Value object for Last.fm play count data."""

    user_play_count: int = 0
    global_play_count: int = 0
    track_url: str | None = None


class LastFmConnector:
    """Thin wrapper around pylast with domain model conversion.

    Handles authentication and provides methods to:
    - Fetch user and global play counts
    - Resolve tracks via MBID or artist/title search
    - Batch retrieve play counts for playlist optimization

    All methods handle rate limiting via backoff decorator.
    """

    def __init__(
        self,
        api_key: str | None = None,
        username: str | None = None,
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
        self,
        artist_name: str,
        track_title: str,
        username: str | None = None,
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
                self.client.get_track,
                artist_name,
                track_title,
            )

            # Get user play count
            track.username = user
            user_playcount = await asyncio.to_thread(
                lambda: int(track.get_userplaycount() or 0),
            )

            # Get global play count (may be unavailable)
            try:
                global_playcount = await asyncio.to_thread(
                    lambda: int(track.get_playcount() or 0),
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
                    "Track not found on Last.fm",
                    artist=artist_name,
                    track=track_title,
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
        self,
        mbid: str,
        username: str | None = None,
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
                lambda: int(track.get_userplaycount() or 0),
            )

            # Get global play count (may be unavailable)
            try:
                global_playcount = await asyncio.to_thread(
                    lambda: int(track.get_playcount() or 0),
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
                "Error getting Last.fm play count by MBID",
                mbid=mbid,
                error=str(e),
            )
            return LastFmPlayCount()

    @resilient_operation("batch_get_track_play_counts")
    async def batch_get_track_play_counts(
        self,
        tracks: list[Track],
        username: str | None = None,
        batch_size: int = 50,
        concurrency_limit: int = 5,
    ) -> dict[int, LastFmPlayCount]:
        """Batch retrieve play counts for multiple tracks.

        Optimizes API calls through parallel requests with batching and
        prioritizes MBID resolution for better accuracy and performance.

        Args:
            tracks: List of domain Track models
            username: Optional username (defaults to configured user)
            batch_size: Maximum batch size (default: 50)
            concurrency_limit: Maximum concurrent API calls (default: 5)

        Returns:
            dictionary mapping track ID to play count info
        """
        user = username or self.username
        results = {}
        logger = get_logger(__name__)

        if not user:
            logger.warning("No username provided for Last.fm play count")
            return {}

        if not self.client:
            logger.warning("Last.fm client not initialized - missing API credentials")
            return {}

        # Separate tracks with MBIDs from those needing artist/title lookup
        mbid_tracks = []  # Tracks with MusicBrainz IDs
        search_tracks = []  # Tracks needing artist/title search

        for track in tracks:
            if track.id is None:
                continue

            if track.connector_track_ids.get("musicbrainz"):
                mbid_tracks.append(track)
            elif track.artists and track.title:
                search_tracks.append(track)

        logger.info(
            f"Last.fm batch lookup: {len(mbid_tracks)} tracks with MBIDs, {len(search_tracks)} with artist/title",
        )

        # Process each group separately for better batching
        # First process tracks with MBIDs (faster and more accurate)
        if mbid_tracks:
            mbid_results = await self._batch_process_tracks(
                mbid_tracks,
                user,
                use_mbid=True,
                batch_size=batch_size,
                concurrency_limit=concurrency_limit,
            )
            results.update(mbid_results)

        # Then process tracks needing artist/title search
        if search_tracks:
            search_results = await self._batch_process_tracks(
                search_tracks,
                user,
                use_mbid=False,
                batch_size=batch_size,
                concurrency_limit=concurrency_limit,
            )
            results.update(search_results)

        logger.info(
            f"Last.fm batch complete: retrieved {len(results)}/{len(tracks)} play counts",
        )
        return results

    async def _batch_process_tracks(
        self,
        tracks: list[Track],
        username: str,
        use_mbid: bool = True,
        batch_size: int = 50,
        concurrency_limit: int = 5,
    ) -> dict[int, LastFmPlayCount]:
        """Process a batch of tracks with either MBID or artist/title lookup.

        Args:
            tracks: List of tracks to process
            username: Last.fm username
            use_mbid: Whether to use MusicBrainz IDs (True) or artist/title (False)
            batch_size: Maximum batch size
            concurrency_limit: Maximum concurrent API calls

        Returns:
            Dictionary mapping track IDs to play counts
        """
        results = {}
        logger = get_logger(__name__)

        # Create semaphore for concurrency control
        semaphore = asyncio.Semaphore(concurrency_limit)

        async def process_track(track: Track) -> tuple[int, LastFmPlayCount]:
            """Process a single track with rate limiting."""
            async with semaphore:
                try:
                    # Ensure track.id is not None (essential fix)
                    if track.id is None:
                        logger.warning(f"Skipping track with None id: {track.title}")
                        return -1, LastFmPlayCount()  # Use sentinel value for id

                    # Add small delay between requests to be nice to Last.fm API
                    await asyncio.sleep(0.2)

                    if use_mbid:
                        # Use MBID for lookup (guaranteed to exist due to filtering)
                        mbid = track.connector_track_ids.get("musicbrainz")
                        if mbid is not None:
                            result = await self.get_mbid_play_count(mbid, username)
                            logger.debug(f"MBID lookup for track {track.id}: {mbid}")
                        else:
                            logger.debug(f"Missing MBID for track {track.id}")
                            result = LastFmPlayCount()
                    else:
                        # Use artist/title for lookup
                        artist_name = track.artists[0].name if track.artists else ""
                        result = await self.get_track_play_count(
                            artist_name,
                            track.title,
                            username,
                        )
                        logger.debug(
                            f"Artist/title lookup for track {track.id}: {artist_name} - {track.title}",
                        )

                    return track.id, result
                except Exception as e:
                    if track.id is None:
                        logger.exception(f"Error processing track with None id: {e}")
                        return -1, LastFmPlayCount()  # Use sentinel value for id
                    else:
                        logger.exception(f"Error processing track {track.id}: {e}")
                        return track.id, LastFmPlayCount()

        # Process tracks in batches
        for i in range(0, len(tracks), batch_size):
            batch = tracks[i : i + batch_size]

            # Process batch concurrently
            batch_tasks = [process_track(track) for track in batch]
            batch_results = await asyncio.gather(*batch_tasks)

            # Collect results, filtering out empty results
            results.update({
                track_id: play_count
                for track_id, play_count in batch_results
                if track_id != -1 and play_count and play_count.track_url
            })
            logger.info(
                f"Processed batch {i // batch_size + 1}/{(len(tracks) + batch_size - 1) // batch_size}: "
                f"{len(results)}/{len(tracks)} successful",
            )

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
        raise ValueError(f"Cannot convert Last.fm track: {e}") from e


def get_connector_config():
    """LastFM connector configuration."""
    return {
        "extractors": {
            "user_play_count": lambda obj: obj.play_count.user_play_count
            if hasattr(obj, "play_count")
            else obj.get("userplaycount", 0),
            "global_play_count": lambda obj: obj.play_count.global_play_count
            if hasattr(obj, "play_count")
            else obj.get("playcount", 0),
        },
        "dependencies": ["musicbrainz"],
        "factory": lambda params: LastFmConnector(params.get("username")),
        "metrics": {"user_play_count": "play_count"},
    }
