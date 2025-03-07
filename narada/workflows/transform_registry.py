"""
Transformation strategy implementations for workflow nodes.

This module implements the Strategy pattern for workflow transformations,
providing concrete algorithms that power different node types. Each strategy
is a pure functional transformation that can be composed and configured through
the node factory system.

The module maintains a registry of available strategies organized by category:
- Filters: Strategies that selectively include/exclude tracks
- Sorters: Strategies that reorder tracks based on attributes or metrics
- Selectors: Strategies that select subsets of tracks
- Combiners: Strategies that merge multiple tracklists

Each strategy focuses on a single responsibility and adheres to a consistent
interface, making the system extensible through new strategy implementations.
"""

from narada.config import get_logger
from narada.core.transforms import (
    concatenate,
    exclude_artists,
    exclude_tracks,
    filter_by_date_range,
    filter_duplicates,
    interleave,
    select_by_method,
    sort_by_attribute,
)

logger = get_logger(__name__)

# === TRANSFORM STRATEGIES ===

TRANSFORM_REGISTRY = {
    "filter": {
        "deduplicate": lambda _ctx, _cfg: filter_duplicates(),
        "by_release_date": lambda _ctx, cfg: filter_by_date_range(
            cfg.get("min_age_days"),
            cfg.get("max_age_days"),
        ),
        "by_tracks": lambda ctx, cfg: exclude_tracks(
            ctx.data[cfg["exclusion_source"]]["tracklist"].tracks,
        ),
        "by_artists": lambda ctx, cfg: exclude_artists(
            ctx.data[cfg["exclusion_source"]]["tracklist"].tracks,
            cfg.get("exclude_all_artists", False),
        ),
    },
    "sorter": {
        "by_user_plays": lambda ctx, cfg: sort_by_attribute(
            key_fn=lambda track: (
                ctx.get(f"match_results.{track.id}.user_play_count", 0)
                if track.id
                else 0
            ),
            metric_name="user_play_count",
            reverse=cfg.get("reverse", True),
        ),
        "by_spotify_popularity": lambda _ctx, cfg: sort_by_attribute(
            key_fn=lambda track: track.get_connector_attribute(
                "spotify",
                "popularity",
                0,
            ),
            metric_name="spotify_popularity",
            reverse=cfg.get("reverse", True),
        ),
    },
    "selector": {
        "limit_tracks": lambda _ctx, cfg: select_by_method(
            cfg.get("count", 10),
            cfg.get("method", "first"),
        ),
    },
    "combiner": {
        "merge_playlists": lambda ctx, cfg: concatenate(
            ctx.collect_tracklists(cfg.get("sources", [])),
        ),
        "concatenate_playlists": lambda ctx, cfg: concatenate(
            ctx.collect_tracklists(cfg.get("order", [])),
        ),
        "interleave_playlists": lambda ctx, cfg: interleave(
            ctx.collect_tracklists(cfg.get("sources", [])),
        ),
    },
}
