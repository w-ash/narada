"""MusicBrainz service connector for entity resolution."""

import asyncio
import time
from typing import Dict, List, Optional

import backoff
import musicbrainzngs

from narada.config import get_logger, resilient_operation

# Get contextual logger with service binding
logger = get_logger(__name__).bind(service="musicbrainz")

# Configure MusicBrainz client
musicbrainzngs.set_useragent(
    "Narada", "0.1.0", "https://github.com/yourusername/narada"
)


class MusicBrainzConnector:
    """Thin wrapper around musicbrainzngs with rate limiting.

    Specializes in:
    - ISRC → MBID resolution
    - Batch lookups for efficient API usage
    - Strict rate limiting compliance (1 req/sec)

    All methods handle proper rate limiting to comply with
    MusicBrainz API terms of service.
    """

    def __init__(self) -> None:
        """Initialize MusicBrainz connector."""
        logger.debug("Initializing MusicBrainz connector")
        # Timestamp of last request to enforce rate limiting
        self._last_request_time = 0
        # Lock to ensure sequential access in async context
        self._request_lock = asyncio.Lock()

    async def _rate_limited_request(self, func, *args, **kwargs):
        """Execute a rate-limited MusicBrainz request.

        Ensures at least 1.1 seconds between requests to comply with
        rate limits (1 req/sec with safety margin).

        Args:
            func: MusicBrainz function to call
            *args: Arguments to pass to function
            **kwargs: Keyword arguments to pass to function

        Returns:
            Result from MusicBrainz API
        """
        async with self._request_lock:
            # Calculate time to wait to comply with rate limit
            now = time.time()
            time_since_last = now - self._last_request_time
            if time_since_last < 1.1:  # 1.1 seconds for safety margin
                await asyncio.sleep(1.1 - time_since_last)

            # Execute request in thread pool to avoid blocking
            try:
                self._last_request_time = time.time()
                result = await asyncio.to_thread(func, *args, **kwargs)
                return result
            except musicbrainzngs.WebServiceError as e:
                logger.error(f"MusicBrainz API error: {e}")
                raise
            except Exception as e:
                logger.exception(f"Error in MusicBrainz request: {e}")
                raise

    @resilient_operation("get_recording_by_isrc")
    @backoff.on_exception(
        backoff.expo,
        musicbrainzngs.WebServiceError,
        max_tries=3,
        giveup=lambda e: "404" in str(e),  # Don't retry not found
    )
    async def get_recording_by_isrc(self, isrc: str) -> Optional[Dict]:
        """Get recording details by ISRC.

        Args:
            isrc: International Standard Recording Code

        Returns:
            Dictionary with recording details or None if not found
        """
        if not isrc:
            return None

        try:
            result = await self._rate_limited_request(
                musicbrainzngs.get_recordings_by_isrc,
                isrc,
                includes=["artists", "releases"],
            )

            # Check if we have any recordings
            if not result.get("isrc", {}).get("recording-list", []):
                logger.debug(f"No recordings found for ISRC: {isrc}")
                return None

            # Return the recording with the most releases (likely primary version)
            recordings = result["isrc"]["recording-list"]
            if not recordings:
                return None

            # Sort by number of releases (descending)
            sorted_recordings = sorted(
                recordings, key=lambda r: len(r.get("release-list", [])), reverse=True
            )

            return sorted_recordings[0]

        except musicbrainzngs.WebServiceError as e:
            if "404" in str(e):
                logger.debug(f"ISRC not found: {isrc}")
                return None
            raise
        except Exception as e:
            logger.exception(f"Error getting recording by ISRC: {e}")
            return None

    @resilient_operation("batch_isrc_lookup")
    async def batch_isrc_lookup(self, isrcs: List[str]) -> Dict[str, str]:
        """Batch lookup of ISRC to MBID mappings.

        Process ISRCs in parallel while respecting rate limits.

        Args:
            isrcs: List of ISRCs to resolve

        Returns:
            Dictionary mapping ISRC to MBID
        """
        if not isrcs:
            return {}

        # Deduplicate ISRCs
        unique_isrcs = list(set(isrc for isrc in isrcs if isrc))
        logger.info(f"Looking up {len(unique_isrcs)} unique ISRCs")

        results = {}

        # Create batches of 10 ISRCs each for parallel processing
        batch_size = 10
        batches = [
            unique_isrcs[i : i + batch_size]
            for i in range(0, len(unique_isrcs), batch_size)
        ]

        # Process each batch with proper rate limiting
        for batch_idx, batch in enumerate(batches):
            # Create tasks for this batch
            tasks = []
            for isrc in batch:
                task = asyncio.create_task(self._process_single_isrc(isrc))
                tasks.append((isrc, task))

            # Wait for all tasks in this batch to complete
            for isrc, task in tasks:
                try:
                    mbid = await task
                    if mbid:
                        results[isrc] = mbid
                except Exception as e:
                    logger.exception(f"Error processing ISRC {isrc}: {e}")

            # Log progress
            processed = (batch_idx + 1) * batch_size
            logger.debug(
                f"Processed {min(processed, len(unique_isrcs))}/{len(unique_isrcs)} ISRCs"
            )

        logger.info(f"ISRC lookup complete, found {len(results)} matches")
        return results

    async def _process_single_isrc(self, isrc: str) -> Optional[str]:
        """Process a single ISRC and extract MBID.

        Helper method for batch_isrc_lookup.

        Args:
            isrc: ISRC to process

        Returns:
            MBID if found, None otherwise
        """
        recording = await self.get_recording_by_isrc(isrc)
        if not recording:
            return None

        # Extract MBID from recording
        return recording.get("id")

    @resilient_operation("search_recording")
    async def search_recording(self, artist: str, title: str) -> Optional[Dict]:
        """Search for a recording by artist and title.

        Fallback method when ISRC is unavailable.

        Args:
            artist: Artist name
            title: Track title

        Returns:
            Recording details if found, None otherwise
        """
        if not artist or not title:
            return None

        try:
            # Use strict query to improve match quality
            query = f'artist:"{artist}" AND recording:"{title}"'
            result = await self._rate_limited_request(
                musicbrainzngs.search_recordings, query=query, limit=5, strict=True
            )

            recordings = result.get("recording-list", [])
            if not recordings:
                return None

            # Return the recording with highest score
            return recordings[0]

        except musicbrainzngs.WebServiceError as e:
            logger.error(f"MusicBrainz search error: {e}")
            return None
        except Exception as e:
            logger.exception(f"Error searching MusicBrainz: {e}")
            return None

    @resilient_operation("get_recording_by_mbid")
    async def get_recording_by_mbid(self, mbid: str) -> Optional[Dict]:
        """Get detailed recording information by MBID.

        Args:
            mbid: MusicBrainz recording ID

        Returns:
            Recording details if found, None otherwise
        """
        if not mbid:
            return None

        try:
            result = await self._rate_limited_request(
                musicbrainzngs.get_recording_by_id,
                mbid,
                includes=["artists", "releases", "isrcs"],
            )

            return result.get("recording")

        except musicbrainzngs.WebServiceError as e:
            if "404" in str(e):
                logger.debug(f"MBID not found: {mbid}")
                return None
            raise
        except Exception as e:
            logger.exception(f"Error getting recording by MBID: {e}")
            return None
