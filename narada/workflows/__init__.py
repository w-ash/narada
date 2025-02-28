"""Workflow orchestration system with node-based transformation pipeline."""

# Step 1: Import core infrastructure first
# Step 3: Force eager loading of all nodes to ensure registry completeness
from narada.workflows import node_factories, workflow_nodes

# Step 2: Import node factories which define node creation patterns
from narada.workflows.node_factories import Context, make_result
from narada.workflows.node_registry import get_node, node, registry

# Step 4: Import workflow execution function
from narada.workflows.prefect import run_workflow


# Step 5: Provide package validation function with complete critical node list
def validate_registry():
    """Validate node registry integrity."""
    critical_paths = [
        "source.spotify_playlist",
        "enricher.resolve_lastfm",
        "filter.deduplicate",
        "filter.by_release_date",
        "filter.not_in_playlist",
        "filter.not_artist_in_playlist",
        "sorter.by_spotify_popularity",  # Corrected from by_popularity
        "sorter.sort_by_user_plays",
        "selector.limit_tracks",  # Corrected from limit
        "combiner.merge_playlists",
        "combiner.concatenate_playlists",
        "combiner.interleave_playlists",
        "destination.create_spotify_playlist",
    ]

    registered = set(registry.list_nodes().keys())
    missing = [c for c in critical_paths if c not in registered]

    if missing:
        missing_str = ", ".join(missing)
        raise RuntimeError(f"Node registry incomplete: missing {missing_str}")

    return True, f"Node registry validated with {len(registered)} nodes"


# Step 6: Execute validation at module load time to catch issues early
try:
    success, message = validate_registry()
except Exception as e:
    from narada.config import get_logger  # Use project's logger

    get_logger(__name__).error(f"Node registry validation failed: {e}")
    # Optionally re-raise to prevent improper module initialization
    # raise

# Step 7: Export clean public API
__all__ = [
    "Context",
    "get_node",
    "make_result",
    "node",
    "run_workflow",
    "validate_registry",
]
