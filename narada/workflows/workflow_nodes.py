"""
Workflow nodes for the Narada transformation pipeline.

This module provides a clean, declarative implementation of all workflow
nodes using the unified factory system. Nodes are organized by
functional category with consistent patterns.
"""

from narada.config import get_logger
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
    make_sorter,
    persist_tracks_and_playlist,
    playlist_destination_factory,
    selector_factory,
    spotify_popularity_key,
    user_play_count_key,
)
from narada.workflows.node_registry import node

logger = get_logger(__name__)

# === SOURCE NODES ===


@node(
    "source.spotify_playlist",
    description="Fetches a playlist from Spotify and persists to database",
    output_type="tracklist",
)
async def spotify_playlist_source(_context: dict, config: dict) -> dict:
    """Load a playlist from Spotify, persist to database, and convert to tracklist."""
    if "playlist_id" not in config:
        raise ValueError("Missing required config parameter: playlist_id")

    playlist_id = config["playlist_id"]
    logger.info(f"Fetching Spotify playlist: {playlist_id}")

    # Initialize Spotify client and fetch playlist
    spotify = SpotifyConnector()
    spotify_playlist = await spotify.get_spotify_playlist(playlist_id)

    # Persist all tracks and the playlist to database
    db_tracks, db_playlist_id, stats = await persist_tracks_and_playlist(
        spotify_playlist.tracks,
        playlist_name=spotify_playlist.name,
        playlist_description=spotify_playlist.description,
        playlist_connector_ids={"spotify": playlist_id},
    )

    # Create tracklist from persisted tracks
    tracklist = TrackList(tracks=db_tracks)
    if spotify_playlist.name:
        tracklist = tracklist.with_metadata(
            "source_playlist_name",
            spotify_playlist.name,
        )
        tracklist = tracklist.with_metadata("spotify_playlist_id", playlist_id)

    # Add database ID to metadata
    if db_playlist_id:
        tracklist = tracklist.with_metadata("db_playlist_id", db_playlist_id)

    # Add stats to metadata
    for key, value in stats.items():
        tracklist = tracklist.with_metadata(key, value)

    return {
        "tracklist": tracklist,
        "source_id": playlist_id,
        "source_name": spotify_playlist.name,
        "track_count": len(tracklist.tracks),
        "db_playlist_id": db_playlist_id,
        **stats,
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
        context,
        config,
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
            cfg.get("min_age_days"),
            cfg.get("max_age_days"),
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
    # Get required reference parameter - no fallback needed
    reference = config.get("reference")

    if not reference:
        raise ValueError(
            "Missing required 'reference' parameter in filter.not_in_playlist node",
        )

    # Create a simple transform factory that directly returns the filter function
    async def transform_factory(ctx, _):  # noqa
        predicate = exclusion_predicate(ctx, {"reference_task_id": reference})
        from narada.core.transforms import filter_by_predicate

        return filter_by_predicate(predicate)

    # Use a single make_node call with our async factory
    return await make_node(transform_factory, "filter_not_in_playlist")(context, {})


@node(
    "filter.not_artist_in_playlist",
    description="Excludes tracks whose artist appears in reference playlist",
    input_type="tracklist",
    output_type="tracklist",
)
async def filter_not_artist_in_playlist(context: dict, config: dict) -> dict:
    """Exclude tracks whose artists appear in reference playlist."""
    # Get required reference parameter - no fallback needed
    reference = config.get("reference")

    if not reference:
        raise ValueError(
            "Missing required 'reference' parameter in filter.not_artist_in_playlist node",
        )

    # Create a simple transform factory that directly returns the filter function
    async def transform_factory(ctx, _):  # noqa
        predicate = exclusion_predicate(
            ctx,
            {"reference_task_id": reference, "exclude_artists": True},
        )
        from narada.core.transforms import filter_by_predicate

        return filter_by_predicate(predicate)

    # Use a single make_node call with our async factory
    return await make_node(transform_factory, "filter_not_artist_in_playlist")(
        context,
        {},
    )


# === SORTER NODES ===


@node(
    "sorter.by_user_plays",
    description="Sorts tracks by user play counts",
    input_type="tracklist",
    output_type="tracklist",
)
async def sort_by_user_plays(context: dict, config: dict) -> dict:  # noqa
    """Sort tracks by user's play count."""
    ctx = Context(context)
    tracklist = ctx.extract_tracklist()
    original_count = len(tracklist.tracks)

    # Extract config parameters
    reverse = config.get("reverse", True)

    # Use factory directly to create key function
    key_fn = user_play_count_key(ctx, config)

    # Create and apply sorter
    sorter = make_sorter(key_fn, reverse)
    sorted_tracklist = sorter(tracklist)

    # Return raw dictionary to satisfy type system
    return {
        "tracklist": sorted_tracklist,
        "operation": "sort_by_plays",
        "original_count": original_count,
        "tracks_count": len(sorted_tracklist.tracks),
        "metric": "user_play_count",
    }


@node(
    "sorter.by_spotify_popularity",
    description="Sorts tracks by Spotify popularity",
    input_type="tracklist",
    output_type="tracklist",
)
async def sort_by_spotify_popularity(context: dict, config: dict) -> dict:  # noqa
    """Sort tracks by Spotify popularity."""
    ctx = Context(context)
    tracklist = ctx.extract_tracklist()
    original_count = len(tracklist.tracks)

    # Extract config parameters
    reverse = config.get("reverse", True)

    # Use factory directly to create key function
    key_fn = spotify_popularity_key(ctx, config)

    # Create and apply sorter
    sorter = make_sorter(key_fn, reverse)
    sorted_tracklist = sorter(tracklist)

    # Return raw dictionary to satisfy type system
    return {
        "tracklist": sorted_tracklist,
        "operation": "sort_by_popularity",
        "original_count": original_count,
        "tracks_count": len(sorted_tracklist.tracks),
        "metric": "popularity",
    }


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
        lambda ctx, _cfg: combiner_factory(
            ctx,
            {"sources": sources, "interleaved": False},
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
        lambda ctx, _cfg: combiner_factory(
            ctx,
            {"sources": order, "interleaved": False},
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
        lambda ctx, _cfg: combiner_factory(
            ctx,
            {"sources": sources, "interleaved": True},
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
# Replace the existing create_spotify_playlist node and add the other two nodes
@node(
    "destination.create_internal_playlist",
    description="Creates a playlist in the internal database only",
    input_type="tracklist",
    output_type="playlist_id",
)
async def create_internal_playlist(context: dict, config: dict) -> dict:
    """Create a playlist in the internal database only."""
    ctx = Context(context)
    return await playlist_destination_factory(ctx, config, "create_internal")


@node(
    "destination.create_spotify_playlist",
    description="Creates a playlist on Spotify and in the database",
    input_type="tracklist",
    output_type="playlist_id",
)
async def create_spotify_playlist(context: dict, config: dict) -> dict:
    """Create a new playlist on Spotify and save to database."""
    ctx = Context(context)
    return await playlist_destination_factory(ctx, config, "create_spotify")


@node(
    "destination.update_spotify_playlist",
    description="Updates an existing Spotify playlist",
    input_type="tracklist",
    output_type="playlist_id",
)
async def update_spotify_playlist(context: dict, config: dict) -> dict:
    """Update an existing Spotify playlist.

    Configuration:
        playlist_id: Spotify playlist ID to update
        append: If True, append tracks; if False, replace (default: False)
    """
    ctx = Context(context)
    return await playlist_destination_factory(ctx, config, "update_spotify")
