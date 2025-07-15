"""
Play deduplication utilities that reuse existing matcher confidence system.

These methods extend the proven track matching architecture for cross-service
play deduplication, maintaining DRY principles by reusing confidence scoring.
"""


from src.domain.entities import TrackPlay
from src.infrastructure.services.matcher import ConfidenceEvidence, calculate_confidence

# NOTE: Redundant helper functions removed - now using TrackPlay methods directly


def calculate_play_match_confidence(
    play1: TrackPlay,
    play2: TrackPlay,
    time_window_seconds: int = 300,
) -> tuple[int, ConfidenceEvidence]:
    """Calculate confidence that two plays represent the same listening event.
    
    Reuses existing track confidence system with time window penalty.
    
    Args:
        play1: First play (typically Spotify)
        play2: Second play (typically Last.fm)
        time_window_seconds: Maximum time difference to consider a match
        
    Returns:
        Tuple of (confidence_score, evidence)
    """
    # Check time window first - fail fast if outside window
    time_diff_seconds = abs((play1.played_at - play2.played_at).total_seconds())
    if time_diff_seconds > time_window_seconds:
        # Outside time window - no match
        evidence = ConfidenceEvidence(
            base_score=0,
            final_score=0,
        )
        return 0, evidence
    
    # Convert plays to data format expected by existing confidence system
    play1_data = play1.to_track_metadata()
    play2_data = play2.to_track_metadata()
    
    # Use play with more complete data as the "internal track"
    if len(play1_data) >= len(play2_data):
        internal_track = play1.to_track()
        service_track_data = play2_data
    else:
        internal_track = play2.to_track()
        service_track_data = play1_data
    
    # Calculate base confidence using existing track matching logic
    base_confidence, evidence = calculate_confidence(
        internal_track=internal_track,
        service_track_data=service_track_data,
        match_method="cross_service_time_match",
    )
    
    # Apply time-based penalty to reduce confidence
    # Linear penalty: 0 seconds = no penalty, time_window_seconds = max penalty
    time_penalty_factor = time_diff_seconds / time_window_seconds
    time_penalty = int(20 * time_penalty_factor)  # Max 20 point penalty
    
    # Calculate final confidence
    final_confidence = max(0, base_confidence - time_penalty)
    
    # Update evidence with time information
    evidence = ConfidenceEvidence(
        base_score=evidence.base_score,
        title_score=evidence.title_score,
        artist_score=evidence.artist_score,
        duration_score=evidence.duration_score - time_penalty,  # Include time penalty in duration
        title_similarity=evidence.title_similarity,
        artist_similarity=evidence.artist_similarity,
        duration_diff_ms=int(time_diff_seconds * 1000),  # Store time diff as "duration" diff
        final_score=final_confidence,
    )
    
    return final_confidence, evidence


def find_potential_duplicate_plays(
    target_play: TrackPlay,
    candidate_plays: list[TrackPlay],
    time_window_seconds: int = 300,
    min_confidence: int = 70,
) -> list[tuple[TrackPlay, int, ConfidenceEvidence]]:
    """Find plays that might be duplicates of the target play.
    
    Args:
        target_play: Play to find duplicates for
        candidate_plays: List of potential duplicate plays
        time_window_seconds: Time window for matching
        min_confidence: Minimum confidence threshold
        
    Returns:
        List of (play, confidence, evidence) tuples for potential duplicates
    """
    duplicates = []
    
    for candidate in candidate_plays:
        # Skip same service comparisons (handled by database deduplication)
        if target_play.service == candidate.service:
            continue
            
        # Skip if not within time window (optimization)
        time_diff = abs((target_play.played_at - candidate.played_at).total_seconds())
        if time_diff > time_window_seconds:
            continue
        
        # Calculate match confidence using existing system
        confidence, evidence = calculate_play_match_confidence(
            target_play, candidate, time_window_seconds
        )
        
        # Only include matches above confidence threshold
        if confidence >= min_confidence:
            duplicates.append((candidate, confidence, evidence))
    
    # Sort by confidence (highest first)
    duplicates.sort(key=lambda x: x[1], reverse=True)
    
    return duplicates