"""
Track matching system for cross-service music identification.

The matcher module provides a unified interface for resolving track identity
across multiple music services (Spotify, LastFM, MusicBrainz).

Design principles:
1. Batch-first - All matching uses batch operations
2. Single source of truth - Database is primary resolver
3. Immutable results - Clean functional approach with no side effects
4. Clear boundaries - Matchers handle resolution, repos handle persistence
"""

import asyncio
from datetime import UTC, datetime
from typing import Any, Protocol, TypeVar

from attrs import define, field
from rapidfuzz import fuzz

from narada.config import get_logger
from narada.core.models import Track, TrackList
from narada.database.db_connection import get_session
from narada.integrations.lastfm import LastFMConnector
from narada.integrations.musicbrainz import MusicBrainzConnector
from narada.integrations.spotify import SpotifyConnector
from narada.repositories.track import UnifiedTrackRepository

logger = get_logger(__name__)

T = TypeVar("T")

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
class MatchResult:
    """Immutable result of track identity resolution."""

    track: Track
    success: bool
    connector_id: str = ""  # ID in the target system
    confidence: int = 0
    match_method: str = ""  # "isrc", "mbid", "artist_title"
    metadata: dict = field(factory=dict)


@define(frozen=True, slots=True)
class ConfidenceEvidence:
    """Evidence used to calculate the confidence score."""

    base_score: int
    title_score: float = 0.0
    artist_score: float = 0.0
    duration_score: float = 0.0
    title_similarity: float = 0.0
    artist_similarity: float = 0.0
    duration_diff_ms: int = 0
    final_score: int = 0

    def as_dict(self) -> dict:
        """Convert to dictionary for logging and metadata."""
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


class MatcherService(Protocol):
    """Protocol for service-specific identity resolution."""

    connector_name: str

    async def batch_match_tracks(
        self,
        tracks: list[Track],
    ) -> dict[int, tuple[bool, str, int, str, dict]]:
        """Match multiple tracks in batch to an external service."""
        ...


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


@define
class SpotifyMatcher:
    """Spotify track matcher using native batch APIs."""

    connector: SpotifyConnector
    connector_name: str = "spotify"

    async def batch_match_tracks(
        self,
        tracks: list[Track],
    ) -> dict[int, tuple[bool, str, int, str, dict]]:
        """Match tracks to Spotify using ISRC and artist/title lookups."""
        if not tracks:
            return {}

        results = {}

        # Group tracks for optimal batch processing
        isrc_tracks = {t.id: t for t in tracks if t.id is not None and t.isrc}

        # Process ISRC tracks (higher confidence)
        if isrc_tracks:
            for track_id, track in isrc_tracks.items():
                try:
                    # Add explicit check to satisfy type checker
                    if not track.isrc:
                        continue

                    spotify_track = await self.connector.search_by_isrc(track.isrc)
                    if spotify_track and spotify_track.get("id"):
                        spotify_id = spotify_track["id"]

                        # Calculate confidence with evidence
                        track_data = {
                            "title": spotify_track.get("name", ""),
                            "artist": spotify_track.get("artists", [{}])[0].get(
                                "name", ""
                            ),
                            "duration_ms": spotify_track.get("duration_ms", 0),
                        }
                        confidence, evidence = calculate_confidence(
                            track, track_data, "isrc"
                        )

                        # Build metadata with evidence
                        metadata = {
                            "matched_at": datetime.now(tz=UTC).isoformat(),
                            "confidence_evidence": evidence.as_dict(),
                        }
                        results[track_id] = (
                            True,
                            spotify_id,
                            confidence,
                            "isrc",
                            metadata,
                        )
                except Exception as e:
                    logger.warning(f"ISRC match failed for Spotify: {track_id=}, {e}")

            # Rate limit protection
            if isrc_tracks:
                await asyncio.sleep(0.2)

        # Find tracks that need artist/title matching
        artist_title_tracks = {
            t.id: t
            for t in tracks
            if t.id is not None and t.id not in results and t.artists and t.title
        }

        # Process artist/title tracks
        for track_id, track in artist_title_tracks.items():
            try:
                artist = track.artists[0].name if track.artists else ""
                spotify_track = await self.connector.search_track(artist, track.title)
                if spotify_track and spotify_track.get("id"):
                    spotify_id = spotify_track["id"]

                    # Calculate confidence with evidence
                    track_data = {
                        "title": spotify_track.get("name", ""),
                        "artist": spotify_track.get("artists", [{}])[0].get("name", ""),
                        "duration_ms": spotify_track.get("duration_ms", 0),
                    }
                    confidence, evidence = calculate_confidence(
                        track,
                        track_data,
                        "artist_title",
                    )

                    # Build metadata with evidence
                    metadata = {
                        "matched_at": datetime.now(tz=UTC).isoformat(),
                        "confidence_evidence": evidence.as_dict(),
                    }
                    results[track_id] = (
                        True,
                        spotify_id,
                        confidence,
                        "artist_title",
                        metadata,
                    )
            except Exception as e:
                logger.warning(
                    f"Artist/title match failed for Spotify: {track_id=}, {e}"
                )

        return results


@define
class LastFMMatcher:
    """LastFM track matcher using native batch APIs."""

    connector: LastFMConnector
    connector_name: str = "lastfm"

    async def batch_match_tracks(
        self,
        tracks: list[Track],
    ) -> dict[int, tuple[bool, str, int, str, dict]]:
        """Match tracks to LastFM using MBID and artist/title lookups."""
        if not tracks:
            return {}

        # Use LastFM's native batch implementation
        track_infos = await self.connector.batch_get_track_info(
            tracks=tracks,
            lastfm_username=self.connector.lastfm_username,
        )

        # Convert to standard match results format
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

                # Calculate confidence with evidence
                track_data = {
                    "title": track_info.lastfm_title or "",
                    "artist": track_info.lastfm_artist_name or "",
                    "duration_ms": track_info.lastfm_duration,
                }
                confidence, evidence = calculate_confidence(
                    track, track_data, match_method
                )

                # Build metadata including playcount data and confidence evidence
                metadata = {
                    "lastfm_user_playcount": track_info.lastfm_user_playcount,
                    "lastfm_global_playcount": track_info.lastfm_global_playcount,
                    "lastfm_listeners": track_info.lastfm_listeners,
                    "lastfm_user_loved": track_info.lastfm_user_loved,
                    "confidence_evidence": evidence.as_dict(),
                }
                results[track_id] = (
                    True,
                    track_info.lastfm_url,
                    confidence,
                    match_method,
                    metadata,
                )

        return results


@define
class MusicBrainzMatcher:
    """MusicBrainz track matcher using native batch APIs."""

    connector: MusicBrainzConnector
    connector_name: str = "musicbrainz"

    async def batch_match_tracks(
        self,
        tracks: list[Track],
    ) -> dict[int, tuple[bool, str, int, str, dict]]:
        """Match tracks to MusicBrainz using ISRC and artist/title lookups."""
        if not tracks:
            return {}

        results = {}

        # Extract ISRCs for batch lookup
        track_to_isrc = {t.id: t for t in tracks if t.id is not None and t.isrc}
        if track_to_isrc:
            # Use native batch lookup
            isrc_results = await self.connector.batch_isrc_lookup(
                [t.isrc for t in track_to_isrc.values() if t.isrc is not None],
            )

            # Map results back to tracks
            for track_id, track in track_to_isrc.items():
                if track.isrc is not None and isrc_results.get(track.isrc):
                    mbid = isrc_results[track.isrc]

                    # For MusicBrainz we have limited metadata for confidence scoring
                    # Most attributes will just use base score
                    confidence, evidence = calculate_confidence(track, {}, "isrc")

                    metadata = {
                        "matched_at": datetime.now(tz=UTC).isoformat(),
                        "confidence_evidence": evidence.as_dict(),
                    }
                    results[track_id] = (True, mbid, confidence, "isrc", metadata)

        # Find unmatched tracks with artist/title
        artist_title_tracks = {
            t.id: t
            for t in tracks
            if t.id is not None and t.id not in results and t.artists and t.title
        }

        # Process each unmatched track
        for track_id, track in artist_title_tracks.items():
            try:
                artist = track.artists[0].name if track.artists else ""
                recording = await self.connector.search_recording(artist, track.title)
                if recording and "id" in recording:
                    mbid = recording["id"]

                    # Calculate confidence with minimal data available
                    track_data = {
                        "title": recording.get("title", ""),
                        # Artist is often not directly available in recording result
                        "artist": artist,  # Use our original artist as proxy
                    }
                    confidence, evidence = calculate_confidence(
                        track, track_data, "artist_title"
                    )

                    metadata = {
                        "title": recording.get("title"),
                        "matched_at": datetime.now(tz=UTC).isoformat(),
                        "confidence_evidence": evidence.as_dict(),
                    }
                    results[track_id] = (
                        True,
                        mbid,
                        confidence,
                        "artist_title",
                        metadata,
                    )
            except Exception as e:
                logger.warning(
                    f"Artist/title match failed for MusicBrainz: {track_id=}, {e}"
                )

        return results


def create_matcher(connector: str, connector_instance: Any) -> MatcherService:
    """Create appropriate matcher service based on connector type."""
    if connector == "spotify":
        return SpotifyMatcher(connector_instance)
    elif connector == "lastfm":
        return LastFMMatcher(connector_instance)
    elif connector == "musicbrainz":
        return MusicBrainzMatcher(connector_instance)
    else:
        raise ValueError(f"Unsupported connector: {connector}")


async def match_tracks(
    track_list: TrackList,
    connector: str,
    connector_instance: Any,
) -> dict[int, MatchResult]:
    """
    Match tracks to a music service with efficient batching.

    This unified matcher combines:
    1. Database lookups for existing mappings
    2. Service-specific batch matching for new resolutions
    3. Confidence scoring based on multiple attributes
    4. Database persistence of successful matches

    Returns dictionary of track IDs to match results.
    """
    if not track_list.tracks:
        return {}

    # Extract valid tracks for processing
    valid_tracks = [t for t in track_list.tracks if t.id is not None]
    if not valid_tracks:
        return {}

    # Use type assertion to inform the type checker these are definitely non-None integers
    track_ids: list[int] = [t.id for t in valid_tracks if t.id is not None]

    # Step 1: Check database for existing mappings
    db_results = await _get_existing_mappings(track_ids, connector)

    # Find tracks that need matching
    tracks_to_match = [t for t in valid_tracks if t.id not in db_results]
    if not tracks_to_match:
        return db_results

    # Step 2: Match new tracks using service-specific matcher
    logger.info(
        f"Matching {len(tracks_to_match)} tracks to {connector}, "
        f"{len(db_results)} already in database"
    )

    matcher = create_matcher(connector, connector_instance)
    batch_results = await matcher.batch_match_tracks(tracks_to_match)

    # Convert to MatchResults
    new_matches = {}
    for track_id, result_tuple in batch_results.items():
        success, connector_id, confidence, match_method, metadata = result_tuple
        if success:
            track = next((t for t in tracks_to_match if t.id == track_id), None)
            if track:
                new_matches[track_id] = MatchResult(
                    track=track.with_connector_track_id(connector, connector_id),
                    success=True,
                    connector_id=connector_id,
                    confidence=confidence,
                    match_method=match_method,
                    metadata=metadata,
                )

    # Step 3: Save new matches to database
    if new_matches:
        await _persist_matches(new_matches, connector)

    # Combine all results
    return {**db_results, **new_matches}


async def _get_existing_mappings(
    track_ids: list[int],
    connector: str,
) -> dict[int, MatchResult]:
    """
    Get existing track mappings from the database.

    Retrieves both traditional track metadata and confidence evidence
    from the track_mappings table if available.
    """
    db_mapped_tracks = {}

    async with get_session() as session:
        track_repo = UnifiedTrackRepository(session)
        existing_mappings = await track_repo.get_connector_mappings(
            track_ids, connector
        )

        # Process tracks with existing mappings
        for track_id in track_ids:
            if (
                track_id in existing_mappings
                and connector in existing_mappings[track_id]
            ):
                connector_id = existing_mappings[track_id][connector]

                # Get track with details
                track = await track_repo.find_track("internal", str(track_id))
                if not track:
                    continue

                metadata = track.connector_metadata.get(connector, {})

                # Get confidence evidence from track_mappings table
                confidence_evidence = await track_repo.get_mapping_confidence_evidence(
                    track_id=track_id, connector=connector, connector_id=connector_id
                )

                # Include evidence in metadata if available
                if confidence_evidence:
                    metadata["confidence_evidence"] = confidence_evidence

                # Create result using existing mapping
                db_mapped_tracks[track_id] = MatchResult(
                    track=track,
                    success=True,
                    connector_id=connector_id,
                    confidence=metadata.get("confidence", 80),
                    match_method=metadata.get("match_method", "unknown"),
                    metadata=metadata,
                )

    return db_mapped_tracks


async def _persist_matches(
    matches: dict[int, MatchResult],
    connector: str,
) -> None:
    """
    Save successful matches to the database with confidence evidence.

    Uses the explicit mapping API to ensure match_method is properly recorded.
    """
    async with get_session() as session:
        track_repo = UnifiedTrackRepository(session)

        for result in matches.values():
            if not result.track.id:
                continue

            # Get track from database
            track = await track_repo.find_track("internal", str(result.track.id))
            if not track:
                continue

            # Create clean metadata copy
            metadata = result.metadata.copy()
            
            # Use the explicit mapping API to create the mapping with the correct match method
            await track_repo.map_track_to_connector(
                track=track,
                connector=connector,
                connector_id=result.connector_id,
                match_method=result.match_method,  # This is the key improvement - using matcher-determined method
                confidence=result.confidence,      # And matcher-determined confidence
                metadata=metadata,                 # Including any evidence or other metadata
            )

        await session.commit()


# Function aliases for backward compatibility
batch_match_tracks = match_tracks
