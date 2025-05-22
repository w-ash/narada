"""MusicBrainz service connector for entity resolution.

This module provides integration with the MusicBrainz API for music metadata lookup
and entity resolution. It implements efficient batch processing with proper rate
limiting to comply with MusicBrainz API policies (1 request per second).

Key components:
- MusicBrainzConnector: Main connector with ISRC resolution capabilities
- BatchProcessor integration: Efficient batch processing with proper backoff
- Rate-limited request handling: Ensures API policy compliance

The module specializes in:
- ISRC to MBID (MusicBrainz ID) resolution for tracks
- Fallback artist/title search when ISRC is unavailable
- Efficient batch processing of multiple identifiers
"""

import asyncio
from importlib.metadata import metadata
import time
from typing import Any

from attrs import define, field
import backoff
import musicbrainzngs

from narada.config import get_config, get_logger, resilient_operation
from narada.integrations.base_connector import BatchProcessor

# Get contextual logger with service binding
logger = get_logger(__name__).bind(service="musicbrainz")

# Configure MusicBrainz client
pkg_meta = metadata("narada")
app_name = pkg_meta.get("Name", "Narada")
app_version = pkg_meta.get("Version", "0.1.0")
app_url = pkg_meta.get("Home-page", "https://github.com/user/narada")
musicbrainzngs.set_useragent(app_name, app_version, app_url)


@define(slots=True)
class MusicBrainzConnector:
    """Wrapper for MusicBrainz API with rate-limiting support.

    Specializes in ISRC → MBID resolution with efficient batch processing
    while strictly adhering to MusicBrainz rate limits (1 req/sec).

    Attributes:
        _last_request_time: Timestamp of last API request for rate limiting
        _request_lock: Asyncio lock to ensure sequential request handling
    """

    _last_request_time: float = field(default=0.0)
    _request_lock: asyncio.Lock = field(factory=asyncio.Lock, repr=False)

    def __attrs_post_init__(self) -> None:
        """Initialize MusicBrainz connector."""
        logger.debug("Initializing MusicBrainz connector")

    async def get_recording_by_isrc(self, isrc: str) -> str | None:
        """
        Get a MusicBrainz recording ID by ISRC.

        Args:
            isrc: The ISRC code

        Returns:
            MusicBrainz recording ID or None if not found
        """
        if not isrc:
            return None

        try:
            # Use existing implementation to get one recording
            result = await self._rate_limited_request(
                musicbrainzngs.get_recordings_by_isrc,
                isrc,
                includes=["artists"],
            )

            if result is None:
                return None

            recordings = result.get("isrc", {}).get("recording-list", [])
            if not recordings:
                return None

            # Return the first recording's MBID
            return recordings[0].get("id")

        except Exception as e:
            logger.exception(f"Error getting recording by ISRC: {e}")
            return None

    async def _rate_limited_request(self, func, *args, **kwargs) -> Any:
        """Execute a rate-limited MusicBrainz request ensuring 1 req/sec compliance."""
        async with self._request_lock:
            # Ensure at least 1.1s between requests (safety margin)
            now = time.time()
            time_since_last = now - self._last_request_time
            if time_since_last < 1.1:
                await asyncio.sleep(1.1 - time_since_last)

            # Execute request in thread pool
            try:
                self._last_request_time = time.time()
                return await asyncio.to_thread(func, *args, **kwargs)
            except musicbrainzngs.WebServiceError as e:
                # Handle 404 errors (not found) differently than other errors
                if "404" in str(e):
                    # Just return None for 404s rather than raising
                    return None
                else:
                    # For other API errors, log and re-raise
                    logger.error(f"MusicBrainz API error: {e}")
                    raise
            except Exception as e:
                logger.exception(f"MusicBrainz request error: {e}")
                raise

    @resilient_operation("batch_isrc_lookup")
    async def batch_isrc_lookup(
        self,
        isrcs: list[str],
        batch_size: int | None = None,
        concurrency: int | None = None,
    ) -> dict[str, str]:
        """Resolve multiple ISRCs to MBIDs with efficient batching."""
        if not isrcs:
            return {}

        # Deduplicate ISRCs
        unique_isrcs = list({isrc for isrc in isrcs if isrc})
        logger.info(f"Looking up {len(unique_isrcs)} unique ISRCs")

        # Get configuration values with defaults from config.py
        mb_batch_size = batch_size or get_config("MUSICBRAINZ_API_BATCH_SIZE", 50)
        mb_concurrency = concurrency or get_config("MUSICBRAINZ_API_CONCURRENCY", 5)
        mb_retry_count = get_config("MUSICBRAINZ_API_RETRY_COUNT", 3)
        mb_retry_base_delay = get_config("MUSICBRAINZ_API_RETRY_BASE_DELAY", 1.0)
        mb_retry_max_delay = get_config("MUSICBRAINZ_API_RETRY_MAX_DELAY", 30.0)
        mb_request_delay = get_config("MUSICBRAINZ_API_REQUEST_DELAY", 0.2)

        # Create batch processor with proper configuration
        processor = BatchProcessor[str, tuple[str, str | None]](
            batch_size=mb_batch_size,
            concurrency_limit=mb_concurrency,
            retry_count=mb_retry_count,
            retry_base_delay=mb_retry_base_delay,
            retry_max_delay=mb_retry_max_delay,
            request_delay=mb_request_delay,
            logger_instance=logger,
        )

        async def process_isrc(isrc: str) -> tuple[str, str | None]:
            """Process a single ISRC with rate limiting."""
            try:
                response = await self._rate_limited_request(
                    musicbrainzngs.get_recordings_by_isrc,
                    isrc,
                    includes=["artists"],
                )

                # Check if response is None (404 from _rate_limited_request)
                if response is None:
                    logger.debug("ISRC not found in MusicBrainz", isrc=isrc)
                    return isrc, None

                recordings = response.get("isrc", {}).get("recording-list", [])
                if not recordings:
                    logger.debug("ISRC found but no recordings associated", isrc=isrc)
                    return isrc, None

                # Return the first recording's MBID (most common case)
                mbid = recordings[0].get("id")
                if mbid:
                    logger.debug("ISRC successfully resolved", isrc=isrc, mbid=mbid)
                return isrc, mbid

            except Exception as e:
                logger.warning("Error processing ISRC lookup", isrc=isrc, error=str(e))
                return isrc, None

        # Use the batch processor to handle all ISRCs
        # Removed the sleep_time parameter which is no longer part of the API
        batch_results = await processor.process(
            items=unique_isrcs,
            process_func=process_isrc,
        )

        # Filter successful results into a dictionary
        results = {isrc: mbid for isrc, mbid in batch_results if mbid}

        logger.info(f"ISRC lookup complete, found {len(results)} matches")
        return results

    @resilient_operation("search_recording")
    @backoff.on_exception(
        backoff.expo,
        musicbrainzngs.WebServiceError,
        max_tries=3,
        giveup=lambda e: "404" in str(e),
    )
    async def search_recording(self, artist: str, title: str) -> dict | None:
        """Search for a recording by artist and title.

        Fallback method when ISRC is unavailable.
        """
        if not artist or not title:
            return None

        query = f'artist:"{artist}" AND recording:"{title}"'
        result = await self._rate_limited_request(
            musicbrainzngs.search_recordings,
            query=query,
            limit=1,
            strict=True,
        )

        recordings = result.get("recording-list", []) if result is not None else []
        return recordings[0] if recordings else None


def get_connector_config():
    """MusicBrainz connector configuration."""
    return {
        "extractors": {
            "mbid": lambda obj: obj.get("id", "")
            if isinstance(obj, dict)
            else getattr(obj, "id", ""),
            "title": lambda obj: obj.get("title", "")
            if isinstance(obj, dict)
            else getattr(obj, "title", ""),
        },
        "dependencies": [],
        "factory": lambda _params: MusicBrainzConnector(),
        "metrics": {"rating": "popularity"},
    }
