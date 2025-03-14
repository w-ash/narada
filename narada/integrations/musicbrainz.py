"""MusicBrainz service connector for entity resolution."""

import asyncio
from importlib.metadata import metadata
import time

import backoff
import musicbrainzngs

from narada.config import get_logger, resilient_operation

# Get contextual logger with service binding
logger = get_logger(__name__).bind(service="musicbrainz")

# Configure MusicBrainz client
pkg_meta = metadata("narada")
app_name = pkg_meta.get("Name", "Narada")
app_version = pkg_meta.get("Version", "0.1.0")
app_url = pkg_meta.get("Home-page", "https://github.com/user/narada")
musicbrainzngs.set_useragent(app_name, app_version, app_url)


class MusicBrainzConnector:
    """Thin wrapper around musicbrainzngs with rate limiting.

    Specializes in ISRC → MBID resolution with efficient batch processing
    while strictly adhering to MusicBrainz rate limits (1 req/sec).
    """

    def __init__(self) -> None:
        """Initialize MusicBrainz connector."""
        logger.debug("Initializing MusicBrainz connector")
        self._last_request_time = 0
        self._request_lock = asyncio.Lock()
        
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

    async def _rate_limited_request(self, func, *args, **kwargs):
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
                    # Let the calling function handle the logging with context
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
        batch_size: int = 50,
        concurrency: int = 5,
    ) -> dict[str, str]:
        """Resolve multiple ISRCs to MBIDs with efficient batching."""
        if not isrcs:
            return {}

        # Deduplicate ISRCs
        unique_isrcs = list({isrc for isrc in isrcs if isrc})
        logger.info(f"Looking up {len(unique_isrcs)} unique ISRCs")
        results = {}

        # Process ISRCs with controlled concurrency
        semaphore = asyncio.Semaphore(concurrency)

        async def process_isrc(isrc: str) -> tuple[str, str | None]:
            """Process a single ISRC with rate limiting."""
            async with semaphore:
                try:
                    response = await self._rate_limited_request(
                        musicbrainzngs.get_recordings_by_isrc,
                        isrc,
                        includes=["artists"],
                    )

                    # Check if response is None (404 from _rate_limited_request)
                    if response is None:
                        logger.warning(
                            "ISRC not found in MusicBrainz",
                            isrc=isrc,
                            status="not_found",
                        )
                        return isrc, None

                    recordings = response.get("isrc", {}).get("recording-list", [])
                    if not recordings:
                        logger.debug(
                            "ISRC found but no recordings associated",
                            isrc=isrc,
                        )
                        return isrc, None

                    # Return the first recording's MBID (most common case)
                    mbid = recordings[0].get("id")
                    if mbid:
                        logger.debug(
                            "ISRC successfully resolved",
                            isrc=isrc,
                            mbid=mbid,
                        )
                    return isrc, mbid

                except Exception as e:
                    logger.warning(
                        "Error processing ISRC lookup",
                        isrc=isrc,
                        error=str(e),
                        error_type=type(e).__name__,
                    )
                    return isrc, None

        # Process ISRCs in batches
        for i in range(0, len(unique_isrcs), batch_size):
            batch = unique_isrcs[i : i + batch_size]
            batch_tasks = [process_isrc(isrc) for isrc in batch]
            batch_results = await asyncio.gather(*batch_tasks)

            # Add successful results to mapping using dictionary comprehension
            results.update({isrc: mbid for isrc, mbid in batch_results if mbid})

            # Log progress
            processed = min(i + batch_size, len(unique_isrcs))
            logger.debug(f"Processed {processed}/{len(unique_isrcs)} ISRCs")

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
