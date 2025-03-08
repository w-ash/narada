"""
Entity resolution system for cross-service music track identification.

This module implements a composable resolution architecture that identifies
equivalent music tracks across different streaming services and metadata providers.
The design follows a functional pipeline approach with declarative configuration,
enabling flexible identity resolution with minimal coupling.

Architectural principles:
- Functional composition over inheritance hierarchies
- Declarative resolution chains for configuration-driven behavior
- Protocol-based interfaces for consistent boundary contracts
- Efficient batch processing with controlled concurrency
- Clean separation between resolution logic and persistence

Core components:
- Resolution primitives: Pure functions for specific matching strategies
- Strategy composition: Declarative chains that prioritize resolution approaches
- Batch operations: Efficient processing with database integration

Integration pattern:
Matcher sits between domain models and enrichers, answering the fundamental
question "Is this track in service A the same as that track in service B?"
This identity resolution is prerequisite to meaningful metadata enrichment
and cross-service operations.

Usage:
    results = await batch_match_tracks(
        tracks,                # List of tracks to match
        "lastfm",              # Target connector
        connector_instance,    # Connector implementation
        track_repository       # Database access layer
    )
"""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from attrs import define

from narada.config import get_logger
from narada.core.models import ConnectorTrackMapping, Track
from narada.core.repositories import TrackRepository
from narada.integrations.lastfm import LastFmConnector, LastFmPlayCount
from narada.integrations.musicbrainz import MusicBrainzConnector

logger = get_logger(__name__)

# Type definitions
ConnectorType = Literal["spotify", "lastfm", "musicbrainz"]


@define(frozen=True, slots=True)
class MatchResult:
    """Immutable result of track resolution across services."""

    track: Track
    play_count: LastFmPlayCount | None = None
    mapping: ConnectorTrackMapping | None = None
    success: bool = False

    @property
    def confidence(self) -> int:
        """Get match confidence score."""
        return self.mapping.confidence if self.mapping else 0

    @property
    def user_play_count(self) -> int:
        """Get user play count or 0 if unavailable."""
        return self.play_count.user_play_count if self.play_count else 0


# Confidence scores for different resolution methods
CONFIDENCE_SCORES = {
    "source": 100,  # Original source track (not used in matcher.py)
    "mbid": 95,  # Native MusicBrainz ID
    "isrc": 85,  # ISRC-based lookup
    "artist_title": 80,  # Artist/title search (least confident)
}


async def resolve_by_mbid(
    track: Track,
    connector: str,
    connector_instance: Any,
) -> dict:
    """Resolve track using MusicBrainz ID."""
    logger = get_logger(__name__)

    # Check if we have an MBID
    mbid = track.connector_track_ids.get("musicbrainz")
    if not mbid:
        logger.debug("No MBID available for track", track_id=track.id)
        return {
            "success": False,
            "external_id": "",
            "confidence": 0,
            "metadata": {},
            "method": "mbid",
        }

    # Handle LastFM resolution
    if connector == "lastfm" and isinstance(connector_instance, LastFmConnector):
        try:
            play_count = await connector_instance.get_mbid_play_count(mbid)
            if play_count and play_count.track_url:
                logger.debug("Successfully resolved track via MBID", mbid=mbid)
                return {
                    "success": True,
                    "external_id": play_count.track_url,
                    "confidence": CONFIDENCE_SCORES["mbid"],
                    "metadata": {
                        "user_play_count": play_count.user_play_count,
                        "global_play_count": play_count.global_play_count,
                    },
                    "method": "mbid",
                }
        except Exception as e:
            logger.exception(f"Error resolving track via MBID: {e}")

    # For other connector types, implement specific resolution logic here

    return {
        "success": False,
        "external_id": "",
        "confidence": 0,
        "metadata": {},
        "method": "mbid",
    }


async def resolve_by_isrc(
    track: Track,
    connector: str,
    connector_instance: Any,
) -> dict:
    """Resolve track using ISRC."""
    logger = get_logger(__name__)

    # Check if we have an ISRC
    isrc = track.isrc
    if not isrc:
        logger.debug("No ISRC available for track", track_id=track.id)
        return {
            "success": False,
            "external_id": "",
            "confidence": 0,
            "metadata": {},
            "method": "isrc",
        }

    # Handle MusicBrainz resolution
    if connector == "musicbrainz" and isinstance(
        connector_instance,
        MusicBrainzConnector,
    ):
        try:
            # MusicBrainzConnector.batch_isrc_lookup handles batching internally
            result = await connector_instance.batch_isrc_lookup([isrc])

            if result and isrc in result:
                mbid = result[isrc]
                logger.debug(
                    "Successfully resolved track via ISRC",
                    isrc=isrc,
                    mbid=mbid,
                )
                return {
                    "success": True,
                    "external_id": mbid,
                    "confidence": CONFIDENCE_SCORES["isrc"],
                    "metadata": {},
                    "method": "isrc",
                }
        except Exception as e:
            logger.exception(f"Error resolving track via ISRC: {e}")

    # For other connector types, implement specific resolution logic here

    return {
        "success": False,
        "external_id": "",
        "confidence": 0,
        "metadata": {},
        "method": "isrc",
    }


async def resolve_by_artist_title(
    track: Track,
    connector: str,
    connector_instance: Any,
) -> dict:
    """Resolve track using artist and title."""
    logger = get_logger(__name__)

    # Check if we have artist and title
    if not track.title or not track.artists:
        logger.debug("Missing artist or title for track", track_id=track.id)
        return {
            "success": False,
            "external_id": "",
            "confidence": 0,
            "metadata": {},
            "method": "artist_title",
        }

    artist = track.artists[0].name if track.artists else ""

    # Handle LastFM resolution
    if connector == "lastfm" and isinstance(connector_instance, LastFmConnector):
        try:
            play_count = await connector_instance.get_track_play_count(
                artist,
                track.title,
            )
            if play_count and play_count.track_url:
                logger.debug(
                    "Successfully resolved track via artist/title",
                    artist=artist,
                    title=track.title,
                )
                return {
                    "success": True,
                    "external_id": play_count.track_url,
                    "confidence": CONFIDENCE_SCORES["artist_title"],
                    "metadata": {
                        "user_play_count": play_count.user_play_count,
                        "global_play_count": play_count.global_play_count,
                    },
                    "method": "artist_title",
                }
        except Exception as e:
            logger.exception(f"Error resolving track via artist/title: {e}")

    # Handle MusicBrainz resolution
    elif connector == "musicbrainz" and isinstance(
        connector_instance,
        MusicBrainzConnector,
    ):
        try:
            recording = await connector_instance.search_recording(artist, track.title)
            if recording and "id" in recording:
                logger.debug(
                    "Successfully resolved track via artist/title",
                    artist=artist,
                    title=track.title,
                )
                return {
                    "success": True,
                    "external_id": recording["id"],
                    "confidence": CONFIDENCE_SCORES["artist_title"],
                    "metadata": {"title": recording.get("title")},
                    "method": "artist_title",
                }
        except Exception as e:
            logger.exception(f"Error resolving track via artist/title: {e}")

    return {
        "success": False,
        "external_id": "",
        "confidence": 0,
        "metadata": {},
        "method": "artist_title",
    }


async def resolve_via_intermediate(
    track: Track,
    target_connector: str,
    target_instance: Any,
    intermediate_connector: str,
    intermediate_instance: Any,
    intermediate_resolver: Callable,
    target_resolver: Callable = resolve_by_mbid,
) -> dict:
    """
    Resolve track through an intermediate connector.

    Example: Resolve to LastFM using MusicBrainz as intermediary:
    - First resolve track to MusicBrainz using ISRC
    - Then resolve to LastFM using the obtained MusicBrainz ID

    Args:
        track: The track to resolve
        target_connector: The final connector we want to resolve to
        target_instance: Instance of the target connector
        intermediate_connector: The intermediate connector to use
        intermediate_instance: Instance of the intermediate connector
        intermediate_resolver: Function to resolve track to intermediate connector
        target_resolver: Function to resolve from intermediate to target (default: MBID)

    Returns:
        Resolution result dictionary
    """
    logger = get_logger(__name__)

    # Step 1: Resolve to the intermediate connector
    intermediate_result = await intermediate_resolver(
        track,
        intermediate_connector,
        intermediate_instance,
    )

    if not intermediate_result["success"]:
        logger.debug(
            f"Failed to resolve to intermediate connector: {intermediate_connector}",
            track_id=track.id,
        )
        return {
            "success": False,
            "external_id": "",
            "confidence": 0,
            "metadata": {},
            "method": f"via_{intermediate_connector}",
        }

    # Step 2: Update track with intermediate ID
    updated_track = track.with_connector_track_id(
        intermediate_connector,
        intermediate_result["external_id"],
    )

    # Step 3: Resolve from intermediate to target
    target_result = await target_resolver(
        updated_track,
        target_connector,
        target_instance,
    )

    # Step 4: Adjust confidence for indirect resolution
    if target_result["success"]:
        # Reduce confidence by 10% to account for indirect resolution
        adjusted_confidence = int(target_result["confidence"] * 0.9)
        target_result["confidence"] = adjusted_confidence
        target_result["method"] = f"via_{intermediate_connector}"

        logger.debug(
            f"Successfully resolved via {intermediate_connector}",
            track_id=track.id,
            confidence=adjusted_confidence,
        )

    return target_result


# --- Section 2: Resolution Strategy Composition ---

# TTL configurations for different connectors (in hours)
CONNECTOR_TTL = {
    "lastfm": 168,  # 1 week
    "musicbrainz": 720,  # 30 days
    "spotify": 720,  # 30 days
}

# Minimum confidence threshold for accepting a match
MIN_CONFIDENCE = {
    "lastfm": 60,
    "musicbrainz": 70,
    "spotify": 80,
}

# Define resolution chains for each connector - ordered by priority
RESOLUTION_CHAINS = {
    "lastfm": [
        # First try direct MBID resolution
        {
            "resolver": resolve_by_mbid,
            "args": {},
        },
        # Then try via MusicBrainz using ISRC
        {
            "resolver": resolve_via_intermediate,
            "args": {
                "intermediate_connector": "musicbrainz",
                "intermediate_resolver": resolve_by_isrc,
            },
        },
        # Fallback to artist/title search
        {
            "resolver": resolve_by_artist_title,
            "args": {},
        },
    ],
    "musicbrainz": [
        # First try direct MBID lookup
        {
            "resolver": resolve_by_mbid,
            "args": {},
        },
        # Then try ISRC lookup
        {
            "resolver": resolve_by_isrc,
            "args": {},
        },
        # Fallback to artist/title search
        {
            "resolver": resolve_by_artist_title,
            "args": {},
        },
    ],
    # Add other connectors as needed
}


async def resolve_track(
    track: Track,
    connector: str,
    connector_instance: Any,
    musicbrainz_instance: Any = None,
    track_repo: TrackRepository | None = None,
) -> MatchResult:
    """
    Resolve a track to a target connector using configured resolution chains.

    Args:
        track: The track to resolve
        connector: The connector to resolve to (e.g., "lastfm", "musicbrainz")
        connector_instance: Instance of the connector
        musicbrainz_instance: Optional MusicBrainz connector instance for intermediate resolution
        track_repo: Optional track repository for database operations

    Returns:
        MatchResult with resolution status and details
    """
    logger = get_logger(__name__)

    # 1. Check for existing mapping in database
    if track.id is not None and track_repo is not None:
        try:
            # Check TTL for fresh mappings
            ttl_hours = CONNECTOR_TTL.get(connector, 168)  # Default 1 week

            # Get track mapping details
            mapping_details = await track_repo.get_track_mapping_details(
                track.id,
                connector,
            )

            if mapping_details:
                # Check freshness
                last_verified = mapping_details.last_verified
                if last_verified and last_verified.tzinfo is None:
                    last_verified = last_verified.replace(tzinfo=UTC)

                if datetime.now(UTC) - last_verified < timedelta(hours=ttl_hours):
                    # Create mapping and result from existing data
                    mapping = ConnectorTrackMapping(
                        connector_name=connector,
                        connector_track_id=mapping_details.connector_id,
                        match_method=mapping_details.match_method,
                        confidence=mapping_details.confidence,
                        metadata=mapping_details.connector_metadata or {},
                    )

                    # For LastFM, include play count data
                    play_count = None
                    if connector == "lastfm" and mapping_details.connector_metadata:
                        play_count = LastFmPlayCount(
                            user_play_count=mapping_details.connector_metadata.get(
                                "user_play_count",
                                0,
                            ),
                            global_play_count=mapping_details.connector_metadata.get(
                                "global_play_count",
                                0,
                            ),
                            track_url=mapping_details.connector_id,
                        )

                    logger.debug(
                        "Using existing mapping from database",
                        track_id=track.id,
                        connector=connector,
                        confidence=mapping_details.confidence,
                    )

                    return MatchResult(
                        track=track.with_connector_track_id(
                            connector,
                            mapping_details.connector_id,
                        ),
                        mapping=mapping,
                        play_count=play_count,
                        success=True,
                    )
                else:
                    logger.debug(
                        "Existing mapping is stale, resolving again",
                        track_id=track.id,
                        connector=connector,
                        age_hours=round(
                            (datetime.now(UTC) - last_verified).total_seconds() / 3600,
                            1,
                        ),
                    )
        except Exception as e:
            logger.exception(f"Error checking existing mapping: {e}")

    # 2. Execute resolution chain
    chain = RESOLUTION_CHAINS.get(connector, [])

    if not chain:
        logger.warning(f"No resolution chain defined for connector: {connector}")
        return MatchResult(track=track, success=False)

    # Track resolution attempts for debugging
    attempts = []

    # Try each resolver in the chain
    for step in chain:
        resolver_func = step["resolver"]
        args = step["args"].copy()

        # Handle intermediate resolution that needs other connector instances
        if (
            resolver_func == resolve_via_intermediate
            and "intermediate_connector" in args
        ):
            if (
                args["intermediate_connector"] == "musicbrainz"
                and not musicbrainz_instance
            ):
                logger.warning(
                    "Missing MusicBrainz instance for intermediate resolution",
                )
                continue

            # Provide the intermediate connector instance
            intermediate_instance = (
                musicbrainz_instance
                if args["intermediate_connector"] == "musicbrainz"
                else None
            )

            if not intermediate_instance:
                logger.warning(
                    f"No instance available for intermediate connector: {args['intermediate_connector']}",
                )
                continue

            # Execute with proper arguments
            try:
                result = await resolver_func(
                    track=track,
                    target_connector=connector,
                    target_instance=connector_instance,
                    intermediate_connector=args["intermediate_connector"],
                    intermediate_instance=intermediate_instance,
                    intermediate_resolver=args["intermediate_resolver"],
                )

                method = f"via_{args['intermediate_connector']}"
                attempts.append({"method": method, "success": result["success"]})

                if result["success"] and result["confidence"] >= MIN_CONFIDENCE.get(
                    connector,
                    0,
                ):
                    return _create_match_result(track, connector, result)
            except Exception as e:
                logger.exception(f"Error in intermediate resolution: {e}")
                attempts.append({
                    "method": f"via_{args['intermediate_connector']}",
                    "success": False,
                    "error": str(e),
                })
        else:
            # Direct resolution
            try:
                result = await resolver_func(track, connector, connector_instance)
                attempts.append({
                    "method": result["method"],
                    "success": result["success"],
                })

                if result["success"] and result["confidence"] >= MIN_CONFIDENCE.get(
                    connector,
                    0,
                ):
                    return _create_match_result(track, connector, result)
            except Exception as e:
                logger.exception(f"Error in resolution: {e}")
                attempts.append({
                    "method": resolver_func.__name__,
                    "success": False,
                    "error": str(e),
                })

    # If we reach here, all resolution attempts failed
    logger.debug(
        "All resolution attempts failed",
        track_id=track.id,
        track_title=track.title,
        attempts=attempts,
    )

    return MatchResult(track=track, success=False)


def _create_match_result(track: Track, connector: str, result: dict) -> MatchResult:
    """
    Create a MatchResult from a resolution result dictionary.

    Args:
        track: The original track
        connector: The connector name
        result: Resolution result dictionary

    Returns:
        Fully populated MatchResult
    """
    # Create mapping
    mapping = ConnectorTrackMapping(
        connector_name=connector,
        connector_track_id=result["external_id"],
        match_method=result["method"],
        confidence=result["confidence"],
        metadata=result["metadata"],
    )

    # For LastFM, create play count
    play_count = None
    if connector == "lastfm" and "user_play_count" in result["metadata"]:
        play_count = LastFmPlayCount(
            user_play_count=result["metadata"].get("user_play_count", 0),
            global_play_count=result["metadata"].get("global_play_count", 0),
            track_url=result["external_id"],
        )

    # Return result with updated track
    return MatchResult(
        track=track.with_connector_track_id(connector, result["external_id"]),
        mapping=mapping,
        play_count=play_count,
        success=True,
    )


# --- Section 3: Batch Operations & Database Integration ---


async def batch_match_tracks(
    tracks: list[Track],
    connector: str,
    connector_instance: Any,
    track_repo: TrackRepository,
    batch_size: int = 50,
    concurrency_limit: int = 5,
) -> dict[int, MatchResult]:
    """
    Process multiple tracks efficiently with batching and concurrency control.

    This is the primary public API for the matcher system, handling:
    - Efficient batched processing
    - Concurrency control for API rate limits
    - Database persistence of match results
    - Comprehensive error handling

    Args:
        tracks: List of tracks to match
        connector: Connector to match tracks against
        connector_instance: Connector API instance
        track_repo: Repository for database operations
        batch_size: Maximum batch size (default: 50)
        concurrency_limit: Maximum concurrent operations (default: 5)

    Returns:
        Dictionary mapping track IDs to match results
    """
    if not tracks:
        return {}

    logger = get_logger(__name__)
    results: dict[int, MatchResult] = {}

    # Initialize MusicBrainz connector if needed for intermediate resolution
    musicbrainz_instance = None
    if connector != "musicbrainz" and "musicbrainz" in [
        step["args"].get("intermediate_connector")
        for step in RESOLUTION_CHAINS.get(connector, [])
        if step["resolver"] == resolve_via_intermediate
    ]:
        try:
            from narada.integrations.musicbrainz import MusicBrainzConnector

            musicbrainz_instance = MusicBrainzConnector()
            logger.debug(
                "Initialized MusicBrainz connector for intermediate resolution",
            )
        except Exception as e:
            logger.warning(f"Failed to initialize MusicBrainz connector: {e}")

    # Filter out tracks without IDs
    valid_tracks = [t for t in tracks if t.id is not None]
    if len(valid_tracks) < len(tracks):
        logger.warning(f"Skipping {len(tracks) - len(valid_tracks)} tracks without IDs")

    # Process in batches with controlled concurrency
    semaphore = asyncio.Semaphore(concurrency_limit)

    async def process_track(track: Track) -> tuple[int, MatchResult]:
        """Process a single track with rate limiting."""
        async with semaphore:
            try:
                result = await resolve_track(
                    track=track,
                    connector=connector,
                    connector_instance=connector_instance,
                    musicbrainz_instance=musicbrainz_instance,
                    track_repo=track_repo,
                )

                # Persist successful matches to database
                if result.success and track.id is not None and result.mapping:
                    await _persist_match_result(track.id, result, track_repo)

                return track.id, result  # type: ignore - we've verified track.id is not None
            except Exception as e:
                logger.exception(f"Error processing track {track.id}: {e}")
                return track.id, MatchResult(track=track, success=False)  # type: ignore

    # Process tracks in batches
    for i in range(0, len(valid_tracks), batch_size):
        batch = valid_tracks[i : i + batch_size]

        # Log batch progress
        logger.info(
            f"Processing batch {i // batch_size + 1}/{(len(valid_tracks) + batch_size - 1) // batch_size}",
            batch_size=len(batch),
            total_tracks=len(valid_tracks),
        )

        # Process batch concurrently
        batch_tasks = [process_track(track) for track in batch]
        batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)

        # Collect successful results
        for item in batch_results:
            if isinstance(item, Exception):
                logger.error(f"Batch processing error: {item}")
                continue

            if not isinstance(item, tuple) or len(item) != 2:
                logger.error(f"Unexpected result type: {type(item)}")
                continue

            track_id, result = item
            if track_id is not None:
                results[track_id] = result

    # Log summary statistics
    success_count = sum(1 for r in results.values() if r.success)
    logger.info(
        f"Batch matching complete: {success_count}/{len(results)} successful matches",
        connector=connector,
    )

    if connector == "lastfm":
        play_count_available = sum(
            1 for r in results.values() if r.success and r.play_count is not None
        )
        logger.info(f"Play count data available: {play_count_available}/{len(results)}")

    return results


async def _persist_match_result(
    track_id: int,
    result: MatchResult,
    track_repo: TrackRepository,
) -> None:
    """
    Persist match result to database efficiently.

    This function handles the database persistence details while maintaining
    proper separation of concerns.

    Args:
        track_id: Database ID of the track
        result: Match result to persist
        track_repo: Repository for database operations
    """
    if not result.success or not result.mapping:
        return

    mapping = result.mapping

    # Extract metadata for persistence
    metadata = mapping.metadata.copy()

    # For LastFM, include play count data
    if mapping.connector_name == "lastfm" and result.play_count:
        metadata.update({
            "user_play_count": result.play_count.user_play_count,
            "global_play_count": result.play_count.global_play_count,
        })

    # For MusicBrainz matches, update the track's denormalized MBID
    if mapping.connector_name == "musicbrainz":
        try:
            # Update or get the track first to ensure it has the MBID
            track = await track_repo.get_track("internal", str(track_id))
            if track and not track.connector_track_ids.get("musicbrainz"):
                # If track doesn't have MBID, save it to ensure denormalized field is updated
                track = track.with_connector_track_id(
                    "musicbrainz",
                    mapping.connector_track_id,
                )
                await track_repo.save_track(track)
        except Exception as e:
            logger.exception(f"Error updating track MBID: {e}")

    # Use the repository's existing method for efficient mapping persistence
    await track_repo.save_connector_mappings([
        (
            track_id,
            mapping.connector_name,
            mapping.connector_track_id,
            mapping.confidence,
            mapping.match_method,
            metadata,
        ),
    ])


# Clear creation and connector factory functions
def create_match_engine(
    lastfm: LastFmConnector | None = None,
    musicbrainz: MusicBrainzConnector | None = None,
) -> dict[str, Any]:
    """
    Create a dictionary of connector instances.

    Args:
        lastfm: Optional LastFM connector instance
        musicbrainz: Optional MusicBrainz connector instance

    Returns:
        Dictionary of connector instances
    """
    connectors = {}

    if lastfm:
        connectors["lastfm"] = lastfm
    if musicbrainz:
        connectors["musicbrainz"] = musicbrainz

    return connectors
