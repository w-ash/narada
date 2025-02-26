"""Concrete playlist transformations built from primitives."""

from datetime import datetime
from typing import Callable, Union

from toolz import curry

from narada.config import get_logger
from narada.core.matcher import MatchResult
from narada.core.models import Playlist, Track
from narada.playlists.operations import (
    PlaylistTransform,
    create_pipeline,
    filter_by_predicate,
    limit,
    rename,
    sort_by_attribute,
)

logger = get_logger(__name__)


def play_count_getter(match_results: dict[int, MatchResult]) -> Callable[[Track], int]:
    """Create a function that extracts play count for a track."""
    def get_play_count(track: Track) -> int:
        if not track.id:
            return -1
        
        result = match_results.get(track.id, {})
        if not result or not result.get("success"):
            return -1
            
        play_count = result.get("play_count")
        return play_count.user_play_count if play_count else -1
        
    return get_play_count


def sort_by_play_count(match_results: dict[int, MatchResult], 
                       min_confidence: int = 60) -> PlaylistTransform:
    """Create a transformation that sorts tracks by play count.
    
    Args:
        match_results: Results from entity resolution
        min_confidence: Minimum match confidence (0-100)
        
    Returns:
        Transformation function that sorts playlist by play count
    """
    # Filter by confidence threshold
    confidence_predicate = lambda t: (
        t.id and 
        t.id in match_results and
        match_results[t.id].get("success", False) and
        match_results[t.id].get("mapping", {}).get("confidence", 0) >= min_confidence
    )
    
    # Create pipeline: filter by confidence then sort by play count
    return create_pipeline(
        filter_by_predicate(confidence_predicate),
        sort_by_attribute(play_count_getter(match_results), reverse=True)
    )


@curry
def filter_by_release_date(max_age_days: int = None, 
                           min_age_days: int = None,
                           playlist: Playlist = None) -> Union[PlaylistTransform, Playlist]:
    """Filter tracks based on release date age.
    
    Creates a transformation for use case 1B (discovery mix) that keeps
    only tracks within the specified age range.
    """
    def transform(p: Playlist) -> Playlist:
        now = datetime.now()
        
        def in_date_range(track: Track) -> bool:
            if not track.release_date:
                return False
                
            age = (now - track.release_date).days
            
            if max_age_days is not None and age > max_age_days:
                return False
                
            if min_age_days is not None and age < min_age_days:
                return False
                
            return True
            
        return filter_by_predicate(in_date_range)(p)
    
    return transform(playlist) if playlist is not None else transform


@curry
def filter_not_in_playlist(other_playlist: Playlist,
                          playlist: Playlist = None) -> Union[PlaylistTransform, Playlist]:
    """Filter out tracks that exist in another playlist.
    
    Useful for "not in my library" style operations.
    """
    def transform(p: Playlist) -> Playlist:
        other_ids = {t.id for t in other_playlist.tracks if t.id}
        return filter_by_predicate(lambda t: t.id not in other_ids)(p)
    
    return transform(playlist) if playlist is not None else transform


def create_discovery_mix(match_results: dict[int, MatchResult],
                        max_age_days: int = 180,
                        limit_count: int = 50) -> PlaylistTransform:
    """Create a discovery playlist transformation (Use Case 1B).
    
    Filters to recent tracks, sorts by play count, limits to desired size.
    """
    return create_pipeline(
        filter_by_release_date(max_age_days),
        sort_by_play_count(match_results),
        limit(limit_count),
        rename("Discovery Mix")
    )        sort_by_play_count(match_results),
        limit(limit_count),
        rename("Discovery Mix")
    )