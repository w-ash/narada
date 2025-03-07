"""Workflow orchestration system with node-based transformation pipeline."""

# Force eager registration of all nodes to ensure registry completeness
# This statement is key for registry population
from narada.workflows import node_catalog
from narada.workflows.node_context import NodeContext

# Factory tools for creating nodes programmatically
from narada.workflows.node_factories import (
    create_combiner_node,
    create_destination_node,
    create_enricher_node,
    create_filter_node,
    create_selector_node,
    create_sorter_node,
)
from narada.workflows.node_registry import get_node, node, registry

# Workflow execution
from narada.workflows.prefect import run_workflow


def validate_registry():
    """Validate registry integrity against critical node list."""
    critical_paths = [
        "source.spotify_playlist",
        "enricher.lastfm",
        "enricher.spotify",
        "filter.deduplicate",
        "filter.by_release_date",
        "filter.by_tracks",
        "filter.by_artists",
        "sorter.by_spotify_popularity",
        "sorter.by_user_plays",
        "selector.limit_tracks",
        "combiner.merge_playlists",
        "combiner.concatenate_playlists",
        "combiner.interleave_playlists",
        "destination.create_internal_playlist",
        "destination.create_spotify_playlist",
        "destination.update_spotify_playlist",
    ]

    registered = set(registry.list_nodes().keys())
    missing = [c for c in critical_paths if c not in registered]

    if missing:
        missing_str = ", ".join(missing)
        raise RuntimeError(f"Node registry incomplete: missing {missing_str}")

    return True, f"Node registry validated with {len(registered)} nodes"


# Validate at module load time to catch issues early
try:
    success, message = validate_registry()
except Exception as e:
    from narada.config import get_logger

    get_logger(__name__).error(f"Node registry validation failed: {e}")

# Export clean public API
__all__ = [
    "NodeContext",
    "create_combiner_node",
    "create_destination_node",
    "create_enricher_node",
    "create_filter_node",
    "create_selector_node",
    "create_sorter_node",
    "get_node",
    "node",
    "run_workflow",
    "validate_registry",
]
