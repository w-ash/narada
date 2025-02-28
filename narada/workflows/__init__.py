"""Workflow orchestration system with node-based transformation pipeline."""

# Step 1: Import core infrastructure first
# Step 2: Force eager loading of all nodes to ensure registry completeness
from narada.workflows import workflow_nodes  # noqa: F401
from narada.workflows.node_factories import Context, make_result  # noqa: F401
from narada.workflows.node_registry import get_node, node, registry


# Step 3: Provide package validation function
def validate_registry():
    """Validate node registry integrity."""
    critical_paths = [
        "source.spotify_playlist",
        "enricher.resolve_lastfm",
        "filter.deduplicate",
        "filter.by_release_date",
        "filter.not_in_playlist",
        "sorter.by_popularity",
        "selector.limit",
        "combiner.merge_playlists",
        "destination.create_spotify_playlist",
    ]

    registered = set(registry.list_nodes().keys())
    missing = [c for c in critical_paths if c not in registered]

    if missing:
        missing_str = ", ".join(missing)
        raise RuntimeError(f"Node registry incomplete: missing {missing_str}")

    return True


# Step 4: Export clean public API
__all__ = ["node", "get_node", "run_workflow", "validate_registry"]

# Re-export key workflow functions
from narada.workflows.prefect import run_workflow  # noqa: F402
