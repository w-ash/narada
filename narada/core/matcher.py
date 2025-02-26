"""Entity resolution and cross-service matching with functional composition.

This module implements a cascading resolution strategy that maps tracks between
music services while supporting functional transformation patterns.
"""

import asyncio
from typing import Callable, Dict, List, Optional, Tuple, TypeVar

from attrs import define

from narada.config import get_logger
from narada.core.models import ConnectorTrackMapping, Track
from narada.integrations.lastfm import LastFmConnector, LastFmPlayCount
from narada.integrations.musicbrainz import MusicBrainzConnector

# Get contextual logger
logger = get_logger(__name__)

# Type aliases for functional composition
T = TypeVar("T", bound=Track)
TrackTransform = Callable[[T], T]

# Resolution configuration with tunable parameters
RESOLUTION_CONFIG = {
    "confidence": {
        "isrc_mbid": 95,  # Base confidence for ISRC→MBID path
        "direct": 85,  # Base confidence for direct artist/title path
        "duration_missing": 5,  # Penalty for missing duration
        "duration_mismatch": 20,  # Penalty for mismatched duration
    },
    "tolerances": {
        "duration_ms": 2000,  # 2 seconds tolerance for duration comparison
    },
    "methods": {
        "isrc_mbid": "isrc_mbid",
        "direct": "direct",
    },
}


@define(frozen=True, slots=True)
class MatchResult:
    """Immutable result of track resolution across services.

    Attributes:
        track: The resolved track with any additional identifiers
        play_count: Last.fm play count data if available
        mapping: Service mapping with confidence scoring
        success: Whether the match was successful
    """

    track: Track
    play_count: Optional[LastFmPlayCount] = None
    mapping: Optional[ConnectorTrackMapping] = None
    success: bool = False

    @property
    def confidence(self) -> int:
        """Get match confidence score."""
        return self.mapping.confidence if self.mapping else 0

    @property
    def user_play_count(self) -> int:
        """Get user play count or 0 if unavailable."""
        return self.play_count.user_play_count if self.play_count else 0


async def resolve_mbid_from_isrc(
    track: Track, musicbrainz_connector: MusicBrainzConnector
) -> Tuple[Optional[str], Track]:
    """Resolve MBID from ISRC using MusicBrainz.

    Args:
        track: Track to resolve
        musicbrainz_connector: MusicBrainz client

    Returns:
        Tuple of (mbid if found, updated track with mbid if resolved)
    """
    if not track.isrc:
        return None, track

    # Check if track already has MBID
    if "musicbrainz" in track.connector_track_ids:
        return track.connector_track_ids["musicbrainz"], track

    # Try to resolve from MusicBrainz
    try:
        match await musicbrainz_connector.get_recording_by_isrc(track.isrc):
            case {"id": mbid}:
                logger.debug(
                    "Resolved MBID from ISRC",
                    track_id=track.id,
                    isrc=track.isrc,
                    mbid=mbid,
                )
                return mbid, track.with_connector_track_id("musicbrainz", mbid)
            case _:
                return None, track
    except Exception as e:
        logger.error(f"Error resolving MBID: {e}", track_id=track.id, isrc=track.isrc)
        return None, track


def validate_metadata(track: Track, confidence: int) -> int:
    """Validate track metadata and adjust confidence score.

    Args:
        track: Track to validate
        confidence: Base confidence score

    Returns:
        Adjusted confidence score
    """
    # Apply duration missing penalty if applicable
    if track.duration_ms is None:
        confidence -= RESOLUTION_CONFIG["confidence"]["duration_missing"]
        logger.debug(
            "Applied duration missing penalty",
            track_id=track.id,
            penalty=RESOLUTION_CONFIG["confidence"]["duration_missing"],
        )

    # Ensure confidence is within 0-100 range
    return max(0, min(100, confidence))


async def match_track(
    track: Track,
    lastfm_connector: LastFmConnector,
    musicbrainz_connector: Optional[MusicBrainzConnector] = None,
    username: Optional[str] = None,
) -> MatchResult:
    """Match a track to Last.fm and retrieve play count.

    Implements a cascading resolution strategy:
    1. Try ISRC→MBID→Last.fm path if ISRC available
    2. Fall back to direct artist/title→Last.fm

    Args:
        track: Track to match
        lastfm_connector: Last.fm client
        musicbrainz_connector: Optional MusicBrainz client
        username: Last.fm username for play counts

    Returns:
        MatchResult with resolution details
    """
    if not track.title or not track.artists:
        logger.warning("Cannot match track without title/artists", track_id=track.id)
        return MatchResult(track=track, success=False)

    artist_name = track.artists[0].name if track.artists else ""
    logger.debug("Starting track match", track_id=track.id, title=track.title)

    play_count = None
    confidence = 0
    match_method = None
    updated_track = track

    # STRATEGY #1: ISRC → MBID → Last.fm
    if track.isrc and musicbrainz_connector:
        mbid, updated_track = await resolve_mbid_from_isrc(track, musicbrainz_connector)

        if mbid:
            play_count = await lastfm_connector.get_mbid_play_count(mbid, username)
            if play_count and play_count.track_url:
                confidence = RESOLUTION_CONFIG["confidence"]["isrc_mbid"]
                match_method = RESOLUTION_CONFIG["methods"]["isrc_mbid"]
                logger.info(
                    "Matched track via ISRC+MBID",
                    track_id=track.id,
                    isrc=track.isrc,
                    mbid=mbid,
                )

    # STRATEGY #2: Direct artist/title → Last.fm
    if not play_count or not play_count.track_url:
        play_count = await lastfm_connector.get_track_play_count(
            artist_name, track.title, username
        )

        if play_count and play_count.track_url:
            confidence = RESOLUTION_CONFIG["confidence"]["direct"]
            match_method = RESOLUTION_CONFIG["methods"]["direct"]
            logger.info(
                "Matched track via direct artist/title",
                track_id=track.id,
                title=track.title,
            )

    # Handle no match found
    if not play_count or not play_count.track_url:
        logger.warning("Failed to match track", track_id=track.id, title=track.title)
        return MatchResult(track=updated_track, success=False)

    # Validate metadata and adjust confidence
    confidence = validate_metadata(updated_track, confidence)

    # Create connector mapping
    mapping = ConnectorTrackMapping(
        connector_name="lastfm",
        connector_track_id=play_count.track_url,
        match_method=match_method or "unknown",
        confidence=confidence,
        metadata={"user_play_count": play_count.user_play_count},
    )

    # Update track with Last.fm URL
    updated_track = updated_track.with_connector_track_id(
        "lastfm", play_count.track_url
    )

    return MatchResult(
        track=updated_track, play_count=play_count, mapping=mapping, success=True
    )


async def batch_match_tracks(
    tracks: List[Track],
    lastfm_connector: LastFmConnector,
    musicbrainz_connector: Optional[MusicBrainzConnector] = None,
    username: Optional[str] = None,
    batch_size: int = 50,
    concurrency: int = 10,
) -> Dict[int, MatchResult]:
    """Match multiple tracks in batches with controlled concurrency.

    Args:
        tracks: List of tracks to match
        lastfm_connector: Last.fm client
        musicbrainz_connector: Optional MusicBrainz client
        username: Last.fm username for play counts
        batch_size: Number of tracks per batch
        concurrency: Maximum concurrent operations

    Returns:
        Dictionary mapping track IDs to match results
    """
    if not tracks:
        return {}

    results: Dict[int, MatchResult] = {}
    total_batches = (len(tracks) + batch_size - 1) // batch_size

    # Process tracks in batches
    for batch_idx, batch_start in enumerate(range(0, len(tracks), batch_size)):
        batch = tracks[batch_start : batch_start + batch_size]
        logger.info(
            f"Processing batch {batch_idx+1}/{total_batches} ({len(batch)} tracks)"
        )

        # Create a semaphore to limit concurrency
        semaphore = asyncio.Semaphore(concurrency)

        async def process_track(track: Track) -> Tuple[Optional[int], MatchResult]:
            """Process a single track with rate limiting."""
            async with semaphore:
                # Small delay to avoid API rate limits
                await asyncio.sleep(0.1)
                try:
                    result = await match_track(
                        track, lastfm_connector, musicbrainz_connector, username
                    )
                    return track.id, result
                except Exception as e:
                    logger.error(f"Match error: {e}", track_id=track.id)
                    return track.id, MatchResult(track=track, success=False)

        # Process batch concurrently
        batch_tasks = [process_track(track) for track in batch]
        batch_results = await asyncio.gather(*batch_tasks)

        # Store valid results
        for track_id, result in batch_results:
            if track_id is not None:
                results[track_id] = result

        # Log batch completion with metrics
        matched = sum(1 for r in results.values() if r.success)
        success_rate = matched / max(1, len(results)) * 100

        logger.info(
            f"Batch {batch_idx+1}/{total_batches} complete",
            success_rate=f"{success_rate:.1f}%",
            matched=f"{matched}/{len(results)}",
        )

    # Final statistics
    successful = sum(1 for r in results.values() if r.success)
    high_confidence = sum(
        1 for r in results.values() if r.success and r.confidence >= 80
    )

    logger.info(
        "Track matching complete",
        total_tracks=len(tracks),
        matched=successful,
        high_confidence=high_confidence,
        success_rate=f"{(successful/len(tracks))*100:.1f}%",
    )

    return results
