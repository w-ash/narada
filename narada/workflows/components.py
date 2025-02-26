"""
Workflow components for the Narada transformation engine.

This module contains the implementation of all workflow components
used in the transformation pipelines. Each component is registered
with the component registry and implements a standard interface.

Interactions:
    Consumes: Transforms from transforms.py, matches from matcher.py, data from repositories.py
    Produces: Workflow components that handle context and configuration
    Key principle: Components orchestrate pure functions, don't implement core logic themselves

These the  business operations - they define what your system actually does in user-facing terms.
"""

import datetime

from narada.core.matcher import batch_match_tracks
from narada.core.models import Playlist, Track
from narada.core.transforms import (
    Transform,
    filter_by_predicate,
    limit,
    sort_by_attribute,
)
from narada.integrations.lastfm import LastFmConnector
from narada.integrations.spotify import SpotifyConnector
from narada.workflows.registry import component

# === HELPER FUNCTIONS ===


def apply_transform(transform_func: Transform, playlist: Playlist) -> Playlist:
    """Apply a transformation to a playlist with proper type handling.

    This helper ensures type checkers understand the transformation result.

    Args:
        transform_func: The transformation function to apply
        playlist: The playlist to transform

    Returns:
        The transformed playlist
    """
    return transform_func(playlist)


def apply_curried_transform(transform_generator, *args, playlist: Playlist) -> Playlist:
    """Apply a curried transformation to a playlist with proper type handling.

    Args:
        transform_generator: A curried transform generator like sort_by_attribute
        *args: Arguments to pass to the transform generator
        playlist: The playlist to transform

    Returns:
        The transformed playlist
    """
    transform_func = transform_generator(*args)
    return transform_func(playlist)


# === SOURCE COMPONENTS ===


@component("source.spotify_playlist", description="Fetches a playlist from Spotify")
async def spotify_playlist_source(context: dict, config: dict) -> dict:
    """Load a playlist from Spotify by ID.

    Configuration:
        playlist_id: Spotify playlist ID to fetch
    """
    playlist_id = config.get("playlist_id")
    if not playlist_id:
        raise ValueError("Missing required config: playlist_id")

    # Initialize Spotify client
    spotify = SpotifyConnector()

    # Fetch playlist
    playlist = await spotify.get_spotify_playlist(playlist_id)

    return {"playlist": playlist, "source_name": playlist.name}


# === ENRICHER COMPONENTS ===


@component(
    "enricher.resolve_lastfm",
    description="Resolves tracks to Last.fm and fetches play counts",
)
async def resolve_lastfm(context: dict, config: dict) -> dict:
    """Resolve playlist tracks to Last.fm and get play counts."""
    playlist = context.get("playlist")
    if not playlist:
        raise ValueError("Missing required input: playlist")

    # Initialize Last.fm client
    lastfm = LastFmConnector()

    # Match tracks to Last.fm
    match_results = await batch_match_tracks(
        playlist.tracks, lastfm, username=lastfm.username
    )

    return {
        "playlist": playlist,
        "match_results": match_results,
        "match_success_rate": f"{sum(1 for r in match_results.values() if r.success)}/{len(playlist.tracks)}",
    }


# === TRANSFORMER COMPONENTS ===


@component("transformer.sort_by_plays", description="Sorts tracks by play count")
async def sort_by_plays(context: dict, config: dict) -> dict:
    """Sort playlist by user play counts.

    Configuration:
        reverse: Sort in descending order (default: True)
        min_confidence: Minimum match confidence (default: 60)
    """
    playlist = context.get("playlist")
    match_results = context.get("match_results", {})

    if not playlist:
        raise ValueError("Missing required input: playlist")

    if not match_results:
        raise ValueError("Missing required input: match_results")

    reverse = config.get("reverse", True)
    min_confidence = config.get("min_confidence", 60)

    # Create a play count getter function
    def get_play_count(track: Track) -> int:
        if not track.id:
            return 0

        result = match_results.get(track.id)
        if not result or not result.success:
            return 0

        # Skip low confidence matches if configured
        if result.confidence < min_confidence:
            return 0

        return result.user_play_count

    # Apply the transformation using the curried helper
    sorted_playlist = apply_curried_transform(
        sort_by_attribute, get_play_count, reverse, playlist=playlist
    )

    return {
        "playlist": sorted_playlist,
        "operation": "sort_by_plays",
        "tracks_count": len(sorted_playlist.tracks),
    }


@component(
    "transformer.filter_by_release_date", description="Filters tracks by release date"
)
async def filter_by_release_date(context: dict, config: dict) -> dict:
    """Filter playlist to tracks within a specified age range.

    Configuration:
        max_age_days: Maximum age in days (optional)
        min_age_days: Minimum age in days (optional)
    """
    playlist = context.get("playlist")
    if not playlist:
        raise ValueError("Missing required input: playlist")

    max_age_days = config.get("max_age_days")
    min_age_days = config.get("min_age_days")

    # Current date for age calculation
    now = datetime.datetime.now()

    # Create a date filter predicate
    def in_date_range(track: Track) -> bool:
        if not track.release_date:
            return False

        age_days = (now - track.release_date).days

        if max_age_days is not None and age_days > max_age_days:
            return False

        if min_age_days is not None and age_days < min_age_days:
            return False

        return True

    # Apply the filter using the curried helper
    filtered_playlist = apply_curried_transform(
        filter_by_predicate, in_date_range, playlist=playlist
    )

    return {
        "playlist": filtered_playlist,
        "operation": "filter_by_date",
        "tracks_count": len(filtered_playlist.tracks),
        "original_count": len(playlist.tracks),
    }


@component(
    "transformer.limit_tracks",
    description="Limits playlist to specified number of tracks",
)
async def limit_tracks(context: dict, config: dict) -> dict:
    """Limit playlist to a maximum number of tracks.

    Configuration:
        count: Maximum number of tracks (required)
    """
    playlist = context.get("playlist")
    if not playlist:
        raise ValueError("Missing required input: playlist")

    count = config.get("count")
    if not count:
        raise ValueError("Missing required config: count")

    # Apply limit transformation with curried helper
    limited_playlist = apply_curried_transform(limit, count, playlist=playlist)

    return {
        "playlist": limited_playlist,
        "operation": "limit",
        "tracks_count": len(limited_playlist.tracks),
    }


@component(
    "transformer.sort_by_popularity", description="Sorts tracks by Spotify popularity"
)
async def sort_by_popularity(context: dict, config: dict) -> dict:
    """Sort playlist by Spotify popularity metric.

    Configuration:
        reverse: True for descending order (most popular first)
    """
    playlist = context.get("playlist")
    if not playlist:
        raise ValueError("Missing required input: playlist")

    reverse = config.get("reverse", True)

    # Create a function to get popularity using connector metadata
    def get_popularity(track: Track) -> int:
        return track.get_connector_attribute("spotify", "popularity", 0)

    # Apply the sort transformation using the helper
    sorted_playlist = apply_curried_transform(
        sort_by_attribute, get_popularity, reverse, playlist=playlist
    )

    return {
        "playlist": sorted_playlist,
        "operation": "sort_by_popularity",
        "tracks_count": len(sorted_playlist.tracks),
    }


@component("transformer.deduplicate", description="Removes duplicate tracks")
async def deduplicate_tracks(context: dict, config: dict) -> dict:
    """Remove duplicate tracks from playlist.

    Deduplication is based on track IDs if available, otherwise
    falls back to artist+title comparison.
    """
    playlist = context.get("playlist")
    if not playlist:
        raise ValueError("Missing required input: playlist")

    # Track seen track IDs or artist+title combinations
    seen = set()
    unique_tracks = []

    for track in playlist.tracks:
        # Check for ID-based duplicates first
        if track.id and track.id in seen:
            continue

        # Fall back to artist+title deduplication
        if track.id:
            key = track.id
        else:
            # Create a composite key from first artist + title
            artist = track.artists[0].name if track.artists else "Unknown"
            key = f"{artist}:{track.title}"

        if key not in seen:
            seen.add(key)
            unique_tracks.append(track)

    # Create a new playlist with deduplicated tracks
    deduplicated_playlist = playlist.with_tracks(unique_tracks)

    return {
        "playlist": deduplicated_playlist,
        "operation": "deduplicate",
        "tracks_count": len(deduplicated_playlist.tracks),
        "removed_count": len(playlist.tracks) - len(deduplicated_playlist.tracks),
    }


# === FILTER COMPONENTS ===


@component(
    "filter.not_in_playlist", description="Excludes tracks found in another playlist"
)
async def filter_not_in_playlist(context: dict, config: dict) -> dict:
    """Filter out tracks that exist in another playlist.

    This component requires two upstream tasks:
    1. The main playlist to filter
    2. The reference playlist (tracks to exclude)
    """
    # Find the main playlist and reference playlist
    main_playlist = None
    reference_playlist = None

    for key, value in context.items():
        if isinstance(value, dict) and "playlist" in value:
            if main_playlist is None:
                main_playlist = value["playlist"]
            else:
                reference_playlist = value["playlist"]

    if not main_playlist or not reference_playlist:
        raise ValueError(
            "Missing required inputs: need two playlists from upstream tasks"
        )

    # Create set of track IDs to exclude
    exclude_ids = set()
    for track in reference_playlist.tracks:
        if track.id:
            exclude_ids.add(track.id)

    # Filter out tracks that exist in the reference playlist
    def not_in_reference(track: Track) -> bool:
        return track.id not in exclude_ids if track.id else True

    # Apply the filter using the curried helper
    filtered_playlist = apply_curried_transform(
        filter_by_predicate, not_in_reference, playlist=main_playlist
    )

    return {
        "playlist": filtered_playlist,
        "operation": "filter_not_in_playlist",
        "tracks_count": len(filtered_playlist.tracks),
        "removed_count": len(main_playlist.tracks) - len(filtered_playlist.tracks),
    }


@component(
    "filter.not_artist_in_playlist",
    description="Excludes tracks whose artist appears in another playlist",
)
async def filter_not_artist_in_playlist(context: dict, config: dict) -> dict:
    """Filter out tracks whose primary artist appears in another playlist.

    This component requires two upstream tasks:
    1. The main playlist to filter
    2. The reference playlist (artists to exclude)
    """
    # Find the main playlist and reference playlist
    main_playlist = None
    reference_playlist = None

    for key, value in context.items():
        if isinstance(value, dict) and "playlist" in value:
            if main_playlist is None:
                main_playlist = value["playlist"]
            else:
                reference_playlist = value["playlist"]

    if not main_playlist or not reference_playlist:
        raise ValueError(
            "Missing required inputs: need two playlists from upstream tasks"
        )

    # Create set of artist names to exclude
    exclude_artists = set()
    for track in reference_playlist.tracks:
        if track.artists and len(track.artists) > 0:
            exclude_artists.add(track.artists[0].name.lower())

    # Filter out tracks whose primary artist is in the exclude set
    def artist_not_in_reference(track: Track) -> bool:
        if not track.artists or len(track.artists) == 0:
            return True
        return track.artists[0].name.lower() not in exclude_artists

    # Apply the filter using the curried helper
    filtered_playlist = apply_curried_transform(
        filter_by_predicate, artist_not_in_reference, playlist=main_playlist
    )

    return {
        "playlist": filtered_playlist,
        "operation": "filter_not_artist_in_playlist",
        "tracks_count": len(filtered_playlist.tracks),
        "removed_count": len(main_playlist.tracks) - len(filtered_playlist.tracks),
    }


# === COMBINER COMPONENTS ===


@component(
    "combiner.merge_playlists", description="Combines multiple playlists into one"
)
async def merge_playlists(context: dict, config: dict) -> dict:
    """Merge multiple playlists into a single playlist.

    This component extracts playlists from all upstream task results
    and combines them into a single playlist.
    """
    # Find all playlists in context from upstream tasks
    playlists = []
    for key, value in context.items():
        if isinstance(value, dict) and "playlist" in value:
            playlists.append(value["playlist"])

    if not playlists:
        raise ValueError("No playlists found in upstream tasks")

    # Create a new playlist with all tracks
    all_tracks = []
    for playlist in playlists:
        all_tracks.extend(playlist.tracks)

    # Create a new playlist with the combined tracks
    merged_playlist = Playlist(
        name="Merged Playlist",
        tracks=all_tracks,
        description="Combined from multiple sources",
    )

    return {
        "playlist": merged_playlist,
        "operation": "merge_playlists",
        "tracks_count": len(merged_playlist.tracks),
        "source_count": len(playlists),
    }


@component(
    "combiner.concatenate_playlists", description="Joins playlists in specified order"
)
async def concatenate_playlists(context: dict, config: dict) -> dict:
    """Concatenate playlists in a specific order.

    Unlike merge, this preserves the order specified in the config.

    Configuration:
        order: List of task IDs in desired concatenation order
    """
    order = config.get("order", [])
    if not order:
        raise ValueError("Missing required config: order")

    # Collect tracks in specified order
    all_tracks = []
    for task_id in order:
        if task_id in context and "playlist" in context[task_id]:
            all_tracks.extend(context[task_id]["playlist"].tracks)

    # Create a new playlist with the concatenated tracks
    concat_playlist = Playlist(
        name="Concatenated Playlist",
        tracks=all_tracks,
        description="Concatenated in specified order",
    )

    return {
        "playlist": concat_playlist,
        "operation": "concatenate_playlists",
        "tracks_count": len(concat_playlist.tracks),
    }


# === DESTINATION COMPONENTS ===


@component(
    "destination.create_spotify_playlist", description="Creates a new Spotify playlist"
)
async def create_spotify_playlist(context: dict, config: dict) -> dict:
    """Create a new Spotify playlist with the transformed tracks.

    Configuration:
        name: Name for the new playlist
        description: Optional description
    """
    playlist = context.get("playlist")
    if not playlist:
        raise ValueError("Missing required input: playlist")

    name = config.get("name")
    if not name:
        raise ValueError("Missing required config: name")

    description = config.get("description", "")

    # Initialize Spotify client
    spotify = SpotifyConnector()

    # Create a new domain playlist with the specified name
    new_playlist = Playlist(name=name, description=description, tracks=playlist.tracks)

    # Create on Spotify
    playlist_id = await spotify.create_spotify_playlist(new_playlist)

    return {
        "playlist_id": playlist_id,
        "playlist_name": name,
        "track_count": len(playlist.tracks),
        "operation": "create_playlist",
    }
