"""Narada domain layer - pure business logic with zero external dependencies."""

# Export all domain components
from . import entities, matching, transforms

# Re-export key types for convenience
from .entities import (
    Artist,
    OperationResult,
    Playlist,
    PlayRecord,
    SyncCheckpoint,
    Track,
    TrackList,
    TrackPlay,
    WorkflowResult,
)
from .matching import (
    ConfidenceEvidence,
    MatchResult,
    calculate_confidence,
    calculate_title_similarity,
)
from .transforms import (
    Transform,
    concatenate,
    create_pipeline,
    filter_by_predicate,
    filter_duplicates,
    limit,
    rename,
    sort_by_attribute,
)

__all__ = [
    # Modules
    "entities",
    "matching", 
    "transforms",
    # Key domain types
    "Artist",
    "Track", 
    "TrackList",
    "Playlist",
    "OperationResult",
    "WorkflowResult",
    "TrackPlay",
    "PlayRecord",
    "SyncCheckpoint",
    # Matching types
    "ConfidenceEvidence",
    "MatchResult",
    "calculate_confidence",
    "calculate_title_similarity",
    # Transform functions
    "create_pipeline",
    "Transform",
    "filter_by_predicate",
    "filter_duplicates",
    "sort_by_attribute", 
    "limit",
    "concatenate",
    "rename",
]