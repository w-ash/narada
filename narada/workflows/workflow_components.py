"""
Workflow components for the Narada transformation engine.

This module contains the implementation of all workflow components
used in the transformation pipelines. Each component is registered
with the component registry and implements a standard interface.

Components follow a clear domain model separation:
- Source components: Convert persistent Playlists to ephemeral TrackLists
- Transformer components: Operate exclusively on TrackLists
- Destination components: Convert TrackLists back to persistent Playlists
"""

from narada.core.matcher import batch_match_tracks
from narada.integrations.lastfm import LastFmConnector
from narada.integrations.spotify import SpotifyConnector
from narada.workflows.component_context import (
    ComponentContext,
    create_combine_component,
    create_date_filter_component,
    create_dedup_component,
    create_reference_filter_component,
    create_selection_component,
    create_sort_component,
    create_spotify_popularity_key,
    create_user_play_count_key,
    ensure_playlist,
)
from narada.workflows.registry import component

# === SOURCE COMPONENTS ===


@component(
    "source.spotify_playlist",
    description="Fetches a playlist from Spotify",
    output_type="tracklist",
)
async def spotify_playlist_source(context: dict, config: dict) -> dict:
    """Load a playlist from Spotify by ID."""
    ctx = ComponentContext(context)
    playlist_id = ctx.get_required_config(config, "playlist_id")

    # Initialize Spotify client and fetch playlist
    spotify = SpotifyConnector()
    playlist = await spotify.get_spotify_playlist(playlist_id)

    # Create tracklist from playlist
    from narada.core.models import TrackList

    tracklist = TrackList.from_playlist(playlist) if playlist.tracks else TrackList()

    return {
        "tracklist": tracklist,
        "source_id": playlist_id,
        "source_name": playlist.name,
    }


# === ENRICHER COMPONENTS ===


@component(
    "enricher.resolve_lastfm",
    description="Resolves tracks to Last.fm and fetches play counts",
)
async def resolve_lastfm(context: dict, config: dict) -> dict:
    """Resolve playlist tracks to Last.fm and get play counts."""
    ctx = ComponentContext(context)
    playlist = ctx.extract_playlist()

    # Match tracks to Last.fm using the user's account
    lastfm = LastFmConnector()
    match_results = await batch_match_tracks(
        playlist.tracks, lastfm, username=lastfm.username
    )

    return {
        "playlist": playlist,
        "match_results": match_results,
        "match_success_rate": f"{sum(1 for r in match_results.values() if r.success)}/{len(playlist.tracks)}",
    }


# === FILTER COMPONENTS ===

# Create deduplicate component using factory
deduplicate_tracks = component(
    "filter.deduplicate",
    description="Removes duplicate tracks",
    input_type="tracklist",
    output_type="tracklist",
)(create_dedup_component("deduplicate"))

# Create date filter component using factory
filter_by_release_date = component(
    "filter.by_release_date",
    description="Filters tracks by release date",
    input_type="tracklist",
    output_type="tracklist",
)(create_date_filter_component("filter_by_date"))

# Create not-in-playlist filter using factory
filter_not_in_playlist = component(
    "filter.not_in_playlist",
    description="Excludes tracks found in another playlist",
    input_type="tracklist",
    output_type="tracklist",
)(create_reference_filter_component("tracks", "filter_not_in_playlist"))

# Create not-artist-in-playlist filter using factory
filter_not_artist_in_playlist = component(
    "filter.not_artist_in_playlist",
    description="Excludes tracks whose artist appears in another playlist",
    input_type="tracklist",
    output_type="tracklist",
)(create_reference_filter_component("artists", "filter_not_artist_in_playlist"))


# === SORTER COMPONENTS ===

# Create user play count sorter using factory
sort_by_user_plays = component(
    "sorter.sort_by_user_plays",
    description="Sorts tracks by user's play count",
    input_type="tracklist",
    output_type="tracklist",
)(create_sort_component(create_user_play_count_key, "sort_by_plays"))

# Create popularity sorter using factory
sort_by_spotify_popularity = component(
    "sorter.by_spotify_popularity",
    description="Sorts tracks by Spotify popularity",
    input_type="tracklist",
    output_type="tracklist",
)(create_sort_component(create_spotify_popularity_key, "sort_by_popularity"))


# === SELECTOR COMPONENTS ===

# Create selection component using factory
limit_tracks_selection = component(
    "selector.limit",
    description="Selects a subset of tracks from a tracklist",
    input_type="tracklist",
    output_type="tracklist",
)(create_selection_component("limit"))


# === COMBINER COMPONENTS ===

# Create concatenation component using factory
concatenate_tracklists = component(
    "combiner.concatenate_tracklists",
    description="Joins tracklists end-to-end in specified order",
    input_type="tracklist",
    output_type="tracklist",
)(create_combine_component("concatenate_tracklists", interleaved=False))

# Create interleaving component using factory
alternate_tracklists = component(
    "combiner.alternate_tracklists",
    description="Interleaves tracks from multiple tracklists",
    input_type="tracklist",
    output_type="tracklist",
)(create_combine_component("alternate_tracklists", interleaved=True))


# === DESTINATION COMPONENTS ===


@component(
    "destination.create_spotify_playlist",
    description="Creates a new Spotify playlist",
    input_type="tracklist",
    output_type="playlist_id",
)
async def create_spotify_playlist(context: dict, config: dict) -> dict:
    """Create a new Spotify playlist with the transformed tracks."""
    ctx = ComponentContext(context)
    tracklist = ctx.extract_tracklist()
    name = ctx.get_required_config(config, "name")
    description = config.get("description", "")

    # Convert tracklist back to playlist for storage
    playlist = ensure_playlist(tracklist, name=name, description=description)

    # Initialize Spotify client and create playlist
    spotify = SpotifyConnector()
    playlist_id = await spotify.create_spotify_playlist(playlist)

    return {
        "playlist_id": playlist_id,
        "playlist_name": name,
        "track_count": len(playlist.tracks),
        "operation": "create_playlist",
    }
