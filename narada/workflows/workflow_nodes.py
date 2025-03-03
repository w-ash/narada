"""
Workflow nodes for the Narada transformation pipeline.

This module registers all available nodes using a declarative pattern,
focusing on node definition rather than implementation details.
"""

from narada.config import get_logger
from narada.workflows.node_factories import (
    create_combiner_node,
    create_destination_node,
    create_enricher_node,
    create_filter_node,
    create_selector_node,
    create_sorter_node,
    spotify_playlist_source,
)
from narada.workflows.node_registry import node

logger = get_logger(__name__)

# === SOURCE NODES ===
node(
    "source.spotify_playlist",
    description="Fetches a playlist from Spotify and persists to database",
    output_type="tracklist",
)(spotify_playlist_source)

# === ENRICHER NODES ===
node(
    "enricher.resolve_lastfm",
    description="Resolves tracks to Last.fm and fetches play counts",
    input_type="tracklist",
    output_type="tracklist",
)(create_enricher_node("lastfm"))

# === FILTER NODES ===
node(
    "filter.deduplicate",
    description="Removes duplicate tracks",
    input_type="tracklist",
    output_type="tracklist",
)(create_filter_node("deduplicate"))

node(
    "filter.by_release_date",
    description="Filters tracks by release date range",
    input_type="tracklist",
    output_type="tracklist",
)(create_filter_node("by_release_date"))

node(
    "filter.by_tracks",
    description="Excludes tracks from input that are present in exclusion source",
    input_type="tracklist",
    output_type="tracklist",
)(create_filter_node("by_tracks"))

node(
    "filter.by_artists",
    description="Excludes tracks whose artists appear in exclusion source",
    input_type="tracklist",
    output_type="tracklist",
)(create_filter_node("by_artists"))

# === SORTER NODES ===
node(
    "sorter.by_user_plays",
    description="Sorts tracks by user play counts",
    input_type="tracklist",
    output_type="tracklist",
)(create_sorter_node("by_user_plays"))

node(
    "sorter.by_spotify_popularity",
    description="Sorts tracks by Spotify popularity",
    input_type="tracklist",
    output_type="tracklist",
)(create_sorter_node("by_spotify_popularity"))

# === SELECTOR NODES ===
node(
    "selector.limit_tracks",
    description="Limits playlist to specified number of tracks",
    input_type="tracklist",
    output_type="tracklist",
)(create_selector_node("limit_tracks"))

# === COMBINER NODES ===
node(
    "combiner.merge_playlists",
    description="Combines multiple playlists into one",
    input_type="tracklist",
    output_type="tracklist",
)(create_combiner_node("merge_playlists"))

node(
    "combiner.concatenate_playlists",
    description="Joins playlists in specified order",
    input_type="tracklist",
    output_type="tracklist",
)(create_combiner_node("concatenate_playlists"))

node(
    "combiner.interleave_playlists",
    description="Interleaves tracks from multiple playlists",
    input_type="tracklist",
    output_type="tracklist",
)(create_combiner_node("interleave_playlists"))

# === DESTINATION NODES ===
node(
    "destination.create_internal_playlist",
    description="Creates a playlist in the internal database only",
    input_type="tracklist",
    output_type="playlist_id",
)(create_destination_node("internal"))

node(
    "destination.create_spotify_playlist",
    description="Creates a playlist on Spotify and in the database",
    input_type="tracklist",
    output_type="playlist_id",
)(create_destination_node("spotify"))

node(
    "destination.update_spotify_playlist",
    description="Updates an existing Spotify playlist",
    input_type="tracklist",
    output_type="playlist_id",
)(create_destination_node("update_spotify"))
