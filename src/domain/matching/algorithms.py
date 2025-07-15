"""Pure algorithms for track matching and confidence scoring.

These functions contain no external dependencies and implement the core business logic
for determining how well tracks match across different music services.
"""

from typing import Any

from rapidfuzz import fuzz

from .types import ConfidenceEvidence

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


def calculate_title_similarity(title1: str, title2: str) -> float:
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
    internal_track_data: dict[str, Any],
    service_track_data: dict[str, Any],
    match_method: str,
) -> tuple[int, ConfidenceEvidence]:
    """
    Calculate confidence score based on multiple attributes.

    Args:
        internal_track_data: Data from our internal track representation
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

    # Get track attributes
    internal_title = internal_track_data.get("title", "")
    internal_artists = internal_track_data.get("artists", [])
    internal_duration = internal_track_data.get("duration_ms")

    service_title = service_track_data.get("title", "")
    service_artist = service_track_data.get("artist", "")
    service_duration = service_track_data.get("duration_ms")

    # 1. Title similarity
    title_similarity = 0.0
    title_score = 0.0
    if internal_title and service_title:
        # Use custom title similarity function
        title_similarity = calculate_title_similarity(internal_title, service_title)

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
    if internal_artists and service_artist:
        # Get first artist name for comparison
        internal_artist = (
            internal_artists[0]
            if isinstance(internal_artists[0], str)
            else internal_artists[0].get("name", "")
        )
        internal_artist = internal_artist.lower()
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
    if not internal_duration or not service_duration:
        # If either track is missing duration, apply flat penalty
        duration_score = -CONFIDENCE_CONFIG["duration_missing_penalty"]
    else:
        # Both tracks have duration, calculate difference
        duration_diff_ms = abs(internal_duration - service_duration)

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
