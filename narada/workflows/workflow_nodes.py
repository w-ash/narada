"""
Workflow nodes for the Narada transformation pipeline.

This module provides a clean, declarative implementation of all workflow
nodes using the unified factory system. Nodes are organized by
functional category with consistent patterns.
"""

from narada.core.matcher import batch_match_tracks
from narada.core.models import TrackList
from narada.integrations.lastfm import LastFmConnector
from narada.integrations.spotify import SpotifyConnector
from narada.workflows.node_factories import (
    Context,
    combiner_factory,
    exclusion_predicate,
    make_date_filter,
    make_dedup_filter,
    make_node,
    selector_factory,
    sorter_factory,
)
from narada.workflows.node_registry import node

# === SOURCE NODES ===


@node(
    "source.spotify_playlist",
    description="Fetches a playlist from Spotify",
    output_type="tracklist",
)
async def spotify_playlist_source(context: dict, config: dict) -> dict:
    """Load a playlist from Spotify and convert to tracklist."""
    ctx = Context(context)
    playlist_id = ctx.require(config.get("playlist_id_param", "playlist_id"))

    # Initialize Spotify client and fetch playlist
    spotify = SpotifyConnector()
    playlist = await spotify.get_spotify_playlist(playlist_id)

    # Create tracklist from playlist
    tracklist = TrackList.from_playlist(playlist) if playlist.tracks else TrackList()

    return {
        "tracklist": tracklist,
        "source_id": playlist_id,
        "source_name": playlist.name,
        "track_count": len(playlist.tracks),
    }


# === ENRICHER NODES ===


@node(
    "enricher.resolve_lastfm",
    description="Resolves tracks to Last.fm and fetches play counts",
)
async def resolve_lastfm(context: dict, config: dict) -> dict:
    """Match tracks to Last.fm and get play counts."""
    ctx = Context(context)
    tracklist = ctx.extract_tracklist()

    # Get matching parameters from config
    username = config.get("username")
    batch_size = config.get("batch_size", 50)
    concurrency = config.get("concurrency", 5)

    # Match tracks to Last.fm using the user's account
    lastfm = LastFmConnector(username=username)
    match_results = await batch_match_tracks(
        tracklist.tracks,
        lastfm,
        username=username or lastfm.username,
        batch_size=batch_size,
        concurrency=concurrency,
    )

    successful_matches = sum(1 for r in match_results.values() if r.success)

    return {
        "tracklist": tracklist,
        "match_results": match_results,
        "match_success_rate": f"{successful_matches}/{len(tracklist.tracks)}",
        "operation": "lastfm_resolution",
    }


# === FILTER NODES ===


@node(
    "filter.deduplicate",
    description="Removes duplicate tracks",
    input_type="tracklist",
    output_type="tracklist",
)
async def deduplicate_filter(context: dict, config: dict) -> dict:
    """Remove duplicate tracks from playlist."""
    return await make_node(lambda _, __: make_dedup_filter(), "deduplicate")(
        context, config
    )


@node(
    "filter.by_release_date",
    description="Filters tracks by release date range",
    input_type="tracklist",
    output_type="tracklist",
)
async def filter_by_date(context: dict, config: dict) -> dict:
    """Filter tracks by release date range."""
    return await make_node(
        lambda _, cfg: make_date_filter(
            cfg.get("min_age_days"), cfg.get("max_age_days")
        ),
        "filter_by_date",
    )(context, config)


@node(
    "filter.not_in_playlist",
    description="Excludes tracks found in another playlist",
    input_type="tracklist",
    output_type="tracklist",
)
async def filter_not_in_playlist(context: dict, config: dict) -> dict:
    """Exclude tracks present in reference playlist."""
    return await make_node(
        lambda ctx, cfg: make_node(
            lambda c, cf: exclusion_predicate(
                c, {"reference_task_id": cf.get("reference")}
            ),
            "exclude_tracks",
        )(ctx, cfg),
        "filter_not_in_playlist",
    )(context, {"reference": config.get("reference", config.get("upstream", [])[-1])})


@node(
    "filter.not_artist_in_playlist",
    description="Excludes tracks whose artist appears in reference playlist",
    input_type="tracklist",
    output_type="tracklist",
)
async def filter_not_artist_in_playlist(context: dict, config: dict) -> dict:
    """Exclude tracks whose artists appear in reference playlist."""
    return await make_node(
        lambda ctx, cfg: make_node(
            lambda c, cf: exclusion_predicate(
                c, {"reference_task_id": cf.get("reference"), "exclude_artists": True}
            ),
            "exclude_artists",
        )(ctx, cfg),
        "filter_not_artist_in_playlist",
    )(context, {"reference": config.get("reference", config.get("upstream", [])[-1])})


# === SORTER NODES ===


@node(
    "sorter.sort_by_user_plays",
    description="Sorts tracks by user play counts",
    input_type="tracklist",
    output_type="tracklist",
)
async def sort_by_user_plays(context: dict, config: dict) -> dict:
    """Sort tracks by user's play count."""
    return await make_node(
        lambda ctx, cfg: make_node(
            lambda c, cf: sorter_factory(c, {"sort_by": "play_count", **cf}),
            "sort_by_plays",
        )(ctx, cfg),
        "sort_by_play_count",
    )(context, config)


@node(
    "sorter.by_spotify_popularity",
    description="Sorts tracks by Spotify popularity",
    input_type="tracklist",
    output_type="tracklist",
)
async def sort_by_spotify_popularity(context: dict, config: dict) -> dict:
    """Sort tracks by Spotify popularity."""
    return await make_node(
        lambda ctx, cfg: make_node(
            lambda c, cf: sorter_factory(c, {"sort_by": "popularity", **cf}),
            "sort_by_popularity",
        )(ctx, cfg),
        "sort_by_popularity",
    )(context, config)


# === SELECTOR NODES ===


@node(
    "selector.limit_tracks",
    description="Limits playlist to specified number of tracks",
    input_type="tracklist",
    output_type="tracklist",
)
async def limit_tracks(context: dict, config: dict) -> dict:
    """Limit tracklist to specified number of tracks."""
    return await make_node(selector_factory, "limit_tracks")(context, config)


# === COMBINER NODES ===


@node(
    "combiner.merge_playlists",
    description="Combines multiple playlists into one",
    input_type="tracklist",
    output_type="tracklist",
)
async def merge_playlists(context: dict, config: dict) -> dict:
    """Merge multiple playlists into one."""
    sources = config.get("sources", context.get("upstream", []))
    return await make_node(
        lambda ctx, cfg: combiner_factory(
            ctx, {"sources": sources, "interleaved": False}
        ),
        "merge_playlists",
    )(context, config)


@node(
    "combiner.concatenate_playlists",
    description="Joins playlists in specified order",
    input_type="tracklist",
    output_type="tracklist",
)
async def concatenate_playlists(context: dict, config: dict) -> dict:
    """Concatenate playlists in specified order."""
    order = config.get("order", context.get("upstream", []))
    return await make_node(
        lambda ctx, cfg: combiner_factory(
            ctx, {"sources": order, "interleaved": False}
        ),
        "concatenate_playlists",
    )(context, config)


@node(
    "combiner.interleave_playlists",
    description="Interleaves tracks from multiple playlists",
    input_type="tracklist",
    output_type="tracklist",
)
async def interleave_playlists(context: dict, config: dict) -> dict:
    """Interleave tracks from multiple playlists."""
    sources = config.get("sources", context.get("upstream", []))
    return await make_node(
        lambda ctx, cfg: combiner_factory(
            ctx, {"sources": sources, "interleaved": True}
        ),
        "interleave_playlists",
    )(context, config)


# === DESTINATION NODES ===


@node(
    "destination.create_spotify_playlist",
    description="Creates a new Spotify playlist",
    input_type="tracklist",
    output_type="playlist_id",
)
async def create_spotify_playlist(context: dict, config: dict) -> dict:
    """Create a new Spotify playlist with the transformed tracks."""
    ctx = Context(context)
    tracklist = ctx.extract_tracklist()
    name = config.get("name", "Narada Playlist")
    description = config.get("description", "Created by Narada")

    # Convert tracklist to playlist
    from narada.core.models import Playlist

    playlist = Playlist(name=name, description=description, tracks=tracklist.tracks)

    # Initialize Spotify client and create playlist
    spotify = SpotifyConnector()
    playlist_id = await spotify.create_spotify_playlist(playlist)

    return {
        "playlist_id": playlist_id,
        "playlist_name": name,
        "track_count": len(playlist.tracks),
        "operation": "create_playlist",
    }
