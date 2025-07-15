"""
Track matching system for cross-service music identification.

The matcher module provides a unified interface for resolving track identity
across multiple music services (Spotify, LastFM, MusicBrainz).
"""

from collections.abc import Callable
from typing import Any, TypeVar

from attrs import define, field
from rapidfuzz import fuzz

from src.application.utilities.progress_integration import (
    batch_progress_wrapper,
    with_progress,
)
from src.domain.entities import Track, TrackList
from src.infrastructure.config import get_config, get_logger
from src.infrastructure.persistence.repositories.track import TrackRepositories

logger = get_logger(__name__)

T = TypeVar("T")

# Type aliases for clarity
TracksById = dict[int, Track]
MatchResultsById = dict[int, "MatchResult"]


async def process_in_batches(
    items: list[Any],
    process_func: Callable,
    *,
    batch_size: int | None = None,
    operation_name: str = "batch_process",
    connector: str | None = None,
) -> dict[int, Any]:
    """Legacy wrapper for unified progress system compatibility.
    
    Maintains API compatibility while using the new unified progress system.
    The progress_callback parameter is now bridged to the unified system.
    """
    if not items:
        logger.info(f"No items to process for {operation_name}")
        return {}

    # Get appropriate batch size based on connector config
    if connector and not batch_size:
        config_key = f"{connector.upper()}_API_BATCH_SIZE"
        batch_size = get_config(config_key, get_config("DEFAULT_API_BATCH_SIZE", 50))
    elif not batch_size:
        batch_size = get_config("DEFAULT_API_BATCH_SIZE", 50)

    # Use unified progress system
    process_with_progress = batch_progress_wrapper(
        items=items,
        process_func=process_func,
        operation_description=operation_name,
        batch_size=batch_size or 50,
    )
    
    return await process_with_progress()


# Confidence scoring configuration
CONFIDENCE_CONFIG = {
    # Base scores by match method
    "base_isrc": 95,
    "base_mbid": 95,
    "base_artist_title": 90,
    # Maximum penalties by category
    "title_max_penalty": 40,
    "artist_max_penalty": 40,
    "duration_max_penalty": 60,
    # Similarity thresholds
    "high_similarity": 0.9,  # Very similar text
    "low_similarity": 0.4,  # Somewhat similar
    # Duration configuration
    "duration_missing_penalty": 10,  # Penalty when either track lacks duration
    "duration_tolerance_ms": 1000,  # No penalty if within 1 second
    "duration_per_second_penalty": 1,  # Points to deduct per second difference
    # Confidence bounds
    "min_confidence": 0,
    "max_confidence": 100,
    # Title similarity constants
    "variation_similarity_score": 0.6,  # Score when a variation marker is found
    "identical_similarity_score": 1.0,  # Score for identical titles
}


@define(frozen=True, slots=True)
class ConfidenceEvidence:
    """Evidence used to calculate the confidence score.

    This class captures the details of how a confidence score was calculated,
    including similarity scores for different attributes and penalties applied.

    This is internal matching information that should be stored in
    track_mappings.confidence_evidence, never in connector_tracks.raw_metadata.
    """

    base_score: int
    title_score: float = 0.0
    artist_score: float = 0.0
    duration_score: float = 0.0
    title_similarity: float = 0.0
    artist_similarity: float = 0.0
    duration_diff_ms: int = 0
    final_score: int = 0

    def as_dict(self) -> dict:
        """Convert to dictionary for storage in track_mappings.confidence_evidence."""
        return {
            "base_score": self.base_score,
            "title_score": round(self.title_score, 2),
            "artist_score": round(self.artist_score, 2),
            "duration_score": round(self.duration_score, 2),
            "title_similarity": round(self.title_similarity, 2),
            "artist_similarity": round(self.artist_similarity, 2),
            "duration_diff_ms": self.duration_diff_ms,
            "final_score": self.final_score,
        }


@define(frozen=True, slots=True)
class MatchResult:
    """Result of track identity resolution with clean separation of concerns.

    This class represents a match between an internal track and an external service,
    containing both the match assessment and service-specific data.

    - Match assessment: Stored in track_mappings (confidence, method, evidence)
    - Service data: Stored in connector_tracks.raw_metadata
    """

    track: Track
    success: bool
    connector_id: str = ""  # ID in the target system
    confidence: int = 0
    match_method: str = ""  # "isrc", "mbid", "artist_title"
    service_data: dict = field(factory=dict)  # Data from external service
    evidence: ConfidenceEvidence | None = None  # Evidence for confidence calculation


def _create_match_result(
    track: Track,
    connector: str,
    connector_id: str,
    match_method: str,
    service_data: dict,
    track_data: dict | None = None,
) -> MatchResult:
    """Create a MatchResult with confidence calculation and logging."""
    # Use service_data as track_data if not provided
    if track_data is None:
        track_data = service_data

    confidence, evidence = calculate_confidence(track, track_data, match_method)

    # Log successful match
    artist_name = track.artists[0].name if track.artists else "Unknown"
    method_display = {
        "isrc": "ISRC",
        "mbid": "MBID",
        "artist_title": "artist/title",
    }.get(match_method, match_method)

    logger.info(
        f"Matched: {track.title} by {artist_name} → {connector.title()} via {method_display} ({confidence}%)",
        track_id=track.id,
        connector=connector,
        match_method=match_method,
        confidence=confidence,
    )

    return MatchResult(
        track=track.with_connector_track_id(connector, connector_id),
        success=True,
        connector_id=connector_id,
        confidence=confidence,
        match_method=match_method,
        service_data=service_data,
        evidence=evidence,
    )


def calculate_title_similarity(title1, title2):
    """Calculate title similarity accounting for variations like 'Live', 'Remix', etc."""
    # Normalize titles
    title1, title2 = title1.lower(), title2.lower()

    # 1. Check if titles are identical
    if title1 == title2:
        return CONFIDENCE_CONFIG["identical_similarity_score"]

    # 2. Check for containment with extra tokens
    # This catches cases like "Paranoid Android" vs "Paranoid Android - Live"
    variation_markers = [
        "live",
        "remix",
        "acoustic",
        "demo",
        "remaster",
        "radio edit",
        "extended",
        "instrumental",
        "album version",
        "single version",
    ]

    # Check if one is contained in the other with variation markers
    if title1 in title2:
        # Title1 is contained in title2, check for variation markers
        remaining = title2.replace(title1, "").strip("- ()[]").strip()
        if any(marker in remaining.lower() for marker in variation_markers):
            # Found variation marker, significantly reduce similarity
            return CONFIDENCE_CONFIG["variation_similarity_score"]
    elif title2 in title1:
        # Same check in reverse
        remaining = title1.replace(title2, "").strip("- ()[]").strip()
        if any(marker in remaining.lower() for marker in variation_markers):
            return CONFIDENCE_CONFIG["variation_similarity_score"]

    # 3. Use token_set_ratio for better handling of word order and extra words
    return fuzz.token_set_ratio(title1, title2) / 100.0


def calculate_confidence(
    internal_track: Track,
    service_track_data: dict,
    match_method: str,
) -> tuple[int, ConfidenceEvidence]:
    """
    Calculate confidence score based on multiple attributes.

    Args:
        internal_track: Our internal track representation
        service_track_data: Data from external service
        match_method: How the track was matched ("isrc", "mbid", "artist_title")

    Returns:
        Tuple of (confidence_score, evidence)
    """
    # Initialize base confidence by match method
    if match_method == "isrc":
        base_score = CONFIDENCE_CONFIG["base_isrc"]
    elif match_method == "mbid":
        base_score = CONFIDENCE_CONFIG["base_mbid"]
    else:  # artist_title or other
        base_score = CONFIDENCE_CONFIG["base_artist_title"]

    # Initialize evidence object
    evidence = ConfidenceEvidence(base_score=base_score)

    # Get service track attributes
    service_title = service_track_data.get("title", "")
    service_artist = service_track_data.get("artist", "")
    service_duration = service_track_data.get("duration_ms")

    # 1. Title similarity
    title_similarity = 0.0
    title_score = 0.0
    if internal_track.title and service_title:
        # Use custom title similarity function
        title_similarity = calculate_title_similarity(
            internal_track.title, service_title
        )

        if title_similarity >= CONFIDENCE_CONFIG["high_similarity"]:
            title_score = 0  # No deduction for high similarity
        else:
            # Linear penalty based on similarity
            # If similarity is 0, apply full penalty
            # If similarity is high_similarity (0.9), apply no penalty
            # Scale linearly in between
            penalty_factor = max(
                0,
                (CONFIDENCE_CONFIG["high_similarity"] - title_similarity)
                / CONFIDENCE_CONFIG["high_similarity"],
            )
            title_score = -CONFIDENCE_CONFIG["title_max_penalty"] * penalty_factor

    # 2. Artist similarity - only deductions
    artist_similarity = 0.0
    artist_score = 0.0
    if internal_track.artists and service_artist:
        internal_artist = internal_track.artists[0].name.lower()
        service_artist = service_artist.lower()

        artist_similarity = (
            fuzz.token_sort_ratio(internal_artist, service_artist) / 100.0
        )

        if artist_similarity >= CONFIDENCE_CONFIG["high_similarity"]:
            artist_score = 0  # No deduction for high similarity
        else:
            # Quadratic or cubic penalty to penalize small differences more severely
            penalty_factor = max(
                0,
                (CONFIDENCE_CONFIG["high_similarity"] - artist_similarity)
                / CONFIDENCE_CONFIG["high_similarity"],
            )
            # Square or cube the factor to make the penalty curve steeper
            penalty_factor = penalty_factor**2  # Square for quadratic curve
            artist_score = -CONFIDENCE_CONFIG["artist_max_penalty"] * penalty_factor
    # 3. Duration comparison
    duration_diff_ms = 0
    duration_score = 0.0

    # Check if both tracks have duration data
    if not internal_track.duration_ms or not service_duration:
        # If either track is missing duration, apply flat penalty
        duration_score = -CONFIDENCE_CONFIG["duration_missing_penalty"]
    else:
        # Both tracks have duration, calculate difference
        duration_diff_ms = abs(internal_track.duration_ms - service_duration)

        # No deduction if within tolerance
        if duration_diff_ms <= CONFIDENCE_CONFIG["duration_tolerance_ms"]:
            duration_score = 0
        else:
            # Convert ms difference to seconds
            seconds_diff = (
                duration_diff_ms - CONFIDENCE_CONFIG["duration_tolerance_ms"]
            ) / 1000
            # Round up to next second using integer division trick
            seconds_penalty = int(seconds_diff) + (seconds_diff > int(seconds_diff))
            duration_score = -min(
                CONFIDENCE_CONFIG["duration_per_second_penalty"] * seconds_penalty,
                CONFIDENCE_CONFIG["duration_max_penalty"],
            )

    # Calculate final confidence with all deductions
    final_score = int(base_score + title_score + artist_score + duration_score)

    # Ensure score is within bounds
    final_score = max(
        CONFIDENCE_CONFIG["min_confidence"],
        min(final_score, CONFIDENCE_CONFIG["max_confidence"]),
    )

    # Update evidence object with all calculated values
    evidence = ConfidenceEvidence(
        base_score=base_score,
        title_score=title_score,
        artist_score=artist_score,
        duration_score=duration_score,
        title_similarity=title_similarity,
        artist_similarity=artist_similarity,
        duration_diff_ms=duration_diff_ms,
        final_score=final_score,
    )

    return final_score, evidence


@with_progress("Matching tracks to external service", estimate_total=lambda track_list: len(track_list.tracks))
async def match_tracks(
    track_list: TrackList,
    connector: str,
    connector_instance: Any,
    track_repos: TrackRepositories,
) -> MatchResultsById:
    """
    Match tracks to a music service with efficient batching.

    This unified matcher combines:
    1. Database lookups for existing mappings
    2. Service-specific matching for new tracks
    3. Confidence scoring based on multiple attributes
    4. Database persistence of successful matches

    Returns dictionary of track IDs to match results.
    """
    if not track_list.tracks:
        return {}

    # Extract valid tracks with IDs for processing
    valid_tracks = [t for t in track_list.tracks if t.id is not None]
    if not valid_tracks:
        return {}

    # Get all track IDs for database lookup
    track_ids = [t.id for t in valid_tracks if t.id is not None]

    # Use contextual logging for the entire operation
    with logger.contextualize(
        operation="match_tracks", connector=connector, track_count=len(track_ids)
    ):
        # Step 1: Check database for existing mappings
        db_results = await _get_existing_mappings(track_ids, connector, track_repos)

        # Find tracks that need matching
        tracks_to_match = [t for t in valid_tracks if t.id not in db_results]

        if not tracks_to_match:
            logger.info(f"All {len(db_results)} tracks already mapped in database")
            return db_results

        # Step 2: Match new tracks based on connector type
        logger.info(f"Need to match {len(tracks_to_match)} new tracks to {connector}")

        # Select connector-specific matching function
        async def match_func(batch):
            """Process a batch of tracks using connector-specific matching."""
            if connector == "lastfm":
                return await _match_lastfm_tracks(batch, connector_instance)
            elif connector == "spotify":
                return await _match_spotify_tracks(batch, connector_instance)
            elif connector == "musicbrainz":
                return await _match_musicbrainz_tracks(batch, connector_instance)
            else:
                raise ValueError(f"Unsupported connector: {connector}")

        # Process matching in batches
        match_results = await process_in_batches(
            tracks_to_match,
            match_func,
            connector=connector,
            operation_name=f"match_{connector}_tracks",
        )

        # Step 3: Save new matches to database if any found
        if match_results:
            await _persist_matches(match_results, connector, track_repos)

        # Combine results and return
        return {**db_results, **match_results}


async def _get_existing_mappings(
    track_ids: list[int],
    connector: str,
    track_repos: TrackRepositories,
) -> MatchResultsById:
    """
    Get existing track mappings from the database using batch operations.

    Retrieves both service data (from connector_tracks.raw_metadata) and
    match assessment (from track_mappings) in an efficient batch approach.
    """
    if not track_ids:
        return {}

    with logger.contextualize(operation="get_existing_mappings", connector=connector):
        logger.info(f"Fetching existing mappings for {len(track_ids)} tracks")

        db_mapped_tracks = {}

        # Step 1: Get all mappings in a single batch call
        existing_mappings = await track_repos.connector.get_connector_mappings(
            track_ids, connector
        )

        # Early return if no mappings found
        if not existing_mappings:
            logger.info("No existing mappings found")
            return {}

        # Step 2: Create a list of track IDs with mappings and their connector IDs
        mapped_track_ids = []
        track_to_connector_id = {}

        for track_id in track_ids:
            if (
                track_id in existing_mappings
                and connector in existing_mappings[track_id]
            ):
                connector_id = existing_mappings[track_id][connector]
                mapped_track_ids.append(track_id)
                track_to_connector_id[track_id] = connector_id

        if not mapped_track_ids:
            logger.info("No valid mappings found")
            return {}

        # Step 3: Get all tracks in a single batch call
        tracks_by_id = await track_repos.core.find_tracks_by_ids(mapped_track_ids)

        # Step 4: Get metadata for all tracks in a batch
        connector_metadata = await track_repos.connector.get_connector_metadata(
            mapped_track_ids, connector
        )

        # Process tracks with existing mappings
        for track_id in mapped_track_ids:
            # Skip if track not found
            if track_id not in tracks_by_id:
                continue

            track = tracks_by_id[track_id]
            connector_id = track_to_connector_id[track_id]

            # Get service data from connector metadata
            service_data = connector_metadata.get(track_id, {})

            # Get mapping information
            mapping_data = await track_repos.connector.get_mapping_info(
                track_id=track_id,
                connector=connector,
                connector_id=connector_id,
            )

            if not mapping_data:
                continue

            confidence = mapping_data.get("confidence", 80)
            match_method = mapping_data.get("match_method", "unknown")
            confidence_evidence_dict = mapping_data.get("confidence_evidence", {})

            # Create evidence object if available
            evidence = None
            if confidence_evidence_dict:
                evidence = ConfidenceEvidence(
                    base_score=confidence_evidence_dict.get("base_score", 0),
                    title_score=confidence_evidence_dict.get("title_score", 0.0),
                    artist_score=confidence_evidence_dict.get("artist_score", 0.0),
                    duration_score=confidence_evidence_dict.get("duration_score", 0.0),
                    title_similarity=confidence_evidence_dict.get(
                        "title_similarity", 0.0
                    ),
                    artist_similarity=confidence_evidence_dict.get(
                        "artist_similarity", 0.0
                    ),
                    duration_diff_ms=confidence_evidence_dict.get(
                        "duration_diff_ms", 0
                    ),
                    final_score=confidence_evidence_dict.get("final_score", 0),
                )

            # Create result with clean separation between service data and match assessment
            db_mapped_tracks[track_id] = MatchResult(
                track=track,
                success=True,
                connector_id=connector_id,
                confidence=confidence,
                match_method=match_method,
                service_data=service_data,
                evidence=evidence,
            )

        logger.info(f"Found {len(db_mapped_tracks)} existing mappings in database")
        return db_mapped_tracks


async def _persist_matches(
    matches: dict[int, MatchResult],
    connector: str,
    track_repos: TrackRepositories,
) -> None:
    """
    Save successful matches to the database with confidence evidence using batch operations.

    Groups all matches for efficient batch persistence.
    """
    if not matches:
        return

    with logger.contextualize(operation="persist_matches", connector=connector):
        logger.info(f"Persisting {len(matches)} matches to database")

        # Get all track ids for batch lookup
        track_ids = [
            result.track.id
            for result in matches.values()
            if result.track.id is not None
        ]

        if not track_ids:
            logger.warning("No valid track IDs found in matches")
            return

        # Get all tracks in a single batch operation
        tracks_by_id = await track_repos.core.find_tracks_by_ids(track_ids)

        batch_size = get_config("DEFAULT_API_BATCH_SIZE", 50)
        success_count = 0

        # Process matches using our batch helper
        batch_items = list(matches.values())

        async def process_batch(batch):
            nonlocal success_count
            batch_results = {}

            for result in batch:
                if not result.track.id or result.track.id not in tracks_by_id:
                    continue

                track = tracks_by_id[result.track.id]

                try:
                    # Map track to connector
                    await track_repos.connector.map_track_to_connector(
                        track=track,
                        connector=connector,
                        connector_id=result.connector_id,
                        match_method=result.match_method,
                        confidence=result.confidence,
                        metadata=result.service_data.copy(),
                        confidence_evidence=result.evidence.as_dict()
                        if result.evidence
                        else None,
                    )
                    success_count += 1
                    batch_results[track.id] = True
                except Exception as e:
                    # For database errors, fail fast instead of continuing
                    if "database is locked" in str(e) or "OperationalError" in str(
                        type(e)
                    ):
                        logger.error(f"Database error encountered, stopping sync: {e}")
                        raise
                    # For other errors, log and continue
                    logger.error(f"Error mapping track {track.id}: {e}")

            return batch_results

        # Process all batches
        await process_in_batches(
            batch_items,
            process_batch,
            batch_size=batch_size,
            operation_name="persist_batch",
            connector=connector,
        )

        logger.info(f"Successfully persisted {success_count} matches")


async def _match_lastfm_tracks(
    tracks: list[Track],
    connector_instance: Any,
) -> MatchResultsById:
    """Match tracks to LastFM using batching."""
    if not tracks:
        return {}

    # LastFM connector already has a batch-oriented API
    # Just call it directly with all tracks at once
    with logger.contextualize(operation="match_lastfm", tracks_count=len(tracks)):
        logger.info(f"Matching {len(tracks)} tracks to LastFM")

        # Get batch track info from LastFM
        track_infos = await connector_instance.batch_get_track_info(
            tracks=tracks,
            lastfm_username=connector_instance.lastfm_username,
        )

        # Convert to match results
        results = {}
        for track_id, track_info in track_infos.items():
            if track_info and track_info.lastfm_url:
                # Find the original track
                track = next((t for t in tracks if t.id == track_id), None)
                if not track:
                    continue

                # Determine match method
                match_method = (
                    "mbid"
                    if track.connector_track_ids.get("musicbrainz")
                    else "artist_title"
                )

                # Extract service data
                service_data = {
                    "title": track_info.lastfm_title,
                    "artist": track_info.lastfm_artist_name,
                    "artists": [track_info.lastfm_artist_name]
                    if track_info.lastfm_artist_name
                    else [],
                    "duration_ms": track_info.lastfm_duration,
                    # LastFM specific data
                    "lastfm_user_playcount": track_info.lastfm_user_playcount,
                    "lastfm_global_playcount": track_info.lastfm_global_playcount,
                    "lastfm_listeners": track_info.lastfm_listeners,
                    "lastfm_user_loved": track_info.lastfm_user_loved,
                }

                # Create match result with logging
                results[track_id] = _create_match_result(
                    track=track,
                    connector="lastfm",
                    connector_id=track_info.lastfm_url,
                    match_method=match_method,
                    service_data=service_data,
                )

        logger.info(f"Found {len(results)} matches from {len(tracks)} tracks")
        return results


async def _match_spotify_tracks(
    tracks: list[Track],
    connector_instance: Any,
) -> MatchResultsById:
    """Match tracks to Spotify using our batch helper."""
    if not tracks:
        return {}

    with logger.contextualize(operation="match_spotify", track_count=len(tracks)):
        # Group tracks by matching method for processing efficiency
        isrc_tracks = [t for t in tracks if t.isrc]
        other_tracks = [t for t in tracks if not t.isrc and t.artists and t.title]

        results = {}

        # Process ISRC tracks first (higher confidence)
        if isrc_tracks:
            logger.info(f"Processing {len(isrc_tracks)} tracks with ISRCs")

            async def process_isrc_batch(batch):
                batch_results = {}
                for track in batch:
                    try:
                        if not track.id or not track.isrc:
                            continue

                        spotify_track = await connector_instance.search_by_isrc(
                            track.isrc
                        )
                        if spotify_track and spotify_track.get("id"):
                            # Process the match result
                            spotify_id = spotify_track["id"]

                            # Extract service data
                            service_data = {
                                "title": spotify_track.get("name"),
                                "album": spotify_track.get("album", {}).get("name"),
                                "artists": [
                                    artist.get("name", "")
                                    for artist in spotify_track.get("artists", [])
                                ],
                                "duration_ms": spotify_track.get("duration_ms"),
                                "release_date": spotify_track.get("album", {}).get(
                                    "release_date"
                                ),
                                "popularity": spotify_track.get("popularity"),
                                "isrc": spotify_track.get("external_ids", {}).get(
                                    "isrc"
                                ),
                            }

                            # Add to results with logging
                            batch_results[track.id] = _create_match_result(
                                track=track,
                                connector="spotify",
                                connector_id=spotify_id,
                                match_method="isrc",
                                service_data=service_data,
                            )
                    except Exception as e:
                        logger.warning(f"ISRC match failed: {e}", track_id=track.id)

                return batch_results

            # Process ISRC tracks in batches
            isrc_results = await process_in_batches(
                isrc_tracks,
                process_isrc_batch,
                operation_name="match_spotify_isrc",
                connector="spotify",
            )

            # Add results to the main results dict
            results.update(isrc_results)

        # Process remaining tracks using artist/title search
        remaining_tracks = [t for t in other_tracks if t.id not in results]
        if remaining_tracks:
            logger.info(f"Processing {len(remaining_tracks)} tracks with artist/title")

            async def process_artist_title_batch(batch):
                batch_results = {}
                for track in batch:
                    try:
                        if not track.id or not track.artists or not track.title:
                            continue

                        artist = track.artists[0].name if track.artists else ""
                        spotify_track = await connector_instance.search_track(
                            artist, track.title
                        )

                        if spotify_track and spotify_track.get("id"):
                            spotify_id = spotify_track["id"]

                            # Extract service data
                            service_data = {
                                "title": spotify_track.get("name"),
                                "album": spotify_track.get("album", {}).get("name"),
                                "artists": [
                                    artist.get("name", "")
                                    for artist in spotify_track.get("artists", [])
                                ],
                                "duration_ms": spotify_track.get("duration_ms"),
                                "release_date": spotify_track.get("album", {}).get(
                                    "release_date"
                                ),
                                "popularity": spotify_track.get("popularity"),
                                "isrc": spotify_track.get("external_ids", {}).get(
                                    "isrc"
                                ),
                            }

                            # Add to results with logging
                            batch_results[track.id] = _create_match_result(
                                track=track,
                                connector="spotify",
                                connector_id=spotify_id,
                                match_method="artist_title",
                                service_data=service_data,
                            )
                    except Exception as e:
                        logger.warning(
                            f"Artist/title match failed: {e}", track_id=track.id
                        )

                return batch_results

            # Process artist/title tracks in batches
            artist_title_results = await process_in_batches(
                remaining_tracks,
                process_artist_title_batch,
                operation_name="match_spotify_artist_title",
                connector="spotify",
            )

            # Add to main results
            results.update(artist_title_results)

        logger.info(f"Found {len(results)} matches from {len(tracks)} tracks")
        return results


async def _match_musicbrainz_tracks(
    tracks: list[Track],
    connector_instance: Any,
) -> MatchResultsById:
    """Match tracks to MusicBrainz using our batch helper."""
    if not tracks:
        return {}

    with logger.contextualize(operation="match_musicbrainz", track_count=len(tracks)):
        # MusicBrainz already has good batch methods
        # Group tracks by matching method
        isrc_tracks = [t for t in tracks if t.isrc]
        other_tracks = [t for t in tracks if not t.isrc and t.artists and t.title]

        results = {}

        # Process ISRC tracks first (higher confidence)
        if isrc_tracks:
            logger.info(f"Processing {len(isrc_tracks)} tracks with ISRCs")

            # Extract ISRCs for batch lookup
            isrcs = [t.isrc for t in isrc_tracks if t.isrc is not None]

            # Use native batch lookup which is already optimized
            isrc_results = await connector_instance.batch_isrc_lookup(isrcs)

            # Map results back to tracks
            for track in isrc_tracks:
                if track.id is None or track.isrc is None:
                    continue

                if track.isrc in isrc_results:
                    mbid = isrc_results[track.isrc]

                    # Create minimal service data
                    service_data = {
                        "title": track.title,
                        "mbid": mbid,
                        "isrc": track.isrc,
                    }

                    # Add to results with logging
                    results[track.id] = _create_match_result(
                        track=track,
                        connector="musicbrainz",
                        connector_id=mbid,
                        match_method="isrc",
                        service_data=service_data,
                        track_data={},  # Empty for ISRC matches
                    )

            logger.info(f"Found {len(isrc_results)} matches from ISRCs")

        # Process remaining tracks using artist/title search
        remaining_tracks = [t for t in other_tracks if t.id not in results]
        if remaining_tracks:
            logger.info(f"Processing {len(remaining_tracks)} tracks with artist/title")

            async def process_artist_title_batch(batch):
                batch_results = {}
                for track in batch:
                    try:
                        if not track.id or not track.artists or not track.title:
                            continue

                        artist = track.artists[0].name if track.artists else ""
                        recording = await connector_instance.search_recording(
                            artist, track.title
                        )

                        if recording and "id" in recording:
                            mbid = recording["id"]

                            # Extract service data
                            service_data = {
                                "title": recording.get("title", ""),
                                "mbid": mbid,
                            }

                            # Add artists if available
                            if "artist-credit" in recording:
                                service_data["artists"] = [
                                    credit["name"]
                                    for credit in recording.get("artist-credit", [])
                                    if isinstance(credit, dict) and "name" in credit
                                ]

                            # Add to results with logging
                            track_data = {
                                "title": recording.get("title", ""),
                                "artist": artist,  # Use our original artist as proxy
                            }
                            batch_results[track.id] = _create_match_result(
                                track=track,
                                connector="musicbrainz",
                                connector_id=mbid,
                                match_method="artist_title",
                                service_data=service_data,
                                track_data=track_data,
                            )
                    except Exception as e:
                        logger.warning(
                            f"Artist/title match failed: {e}", track_id=track.id
                        )

                return batch_results

            # Process artist/title tracks in batches
            artist_title_results = await process_in_batches(
                remaining_tracks,
                process_artist_title_batch,
                operation_name="match_musicbrainz_artist_title",
                connector="musicbrainz",
            )

            # Add to main results
            results.update(artist_title_results)

        logger.info(f"Found {len(results)} matches from {len(tracks)} tracks")
        return results
