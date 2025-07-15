"""Pure functional transformations for domain entities."""

from .core import *

__all__ = [
    # Core pipeline functions
    "create_pipeline",
    "Transform",
    # Track filtering
    "filter_by_predicate",
    "filter_duplicates", 
    "filter_by_date_range",
    "exclude_tracks",
    "exclude_artists",
    "filter_by_metric_range",
    # Track sorting
    "sort_by_attribute",
    # Track selection
    "limit",
    "take_last",
    "sample_random",
    "select_by_method",
    # Track list combination
    "concatenate",
    "interleave",
    # Playlist operations
    "rename",
    "set_description",
]