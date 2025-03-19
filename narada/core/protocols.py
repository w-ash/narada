"""Core protocols and interfaces for the node factory system.

Defines contract interfaces between system components, enabling loose coupling
and clear separation of concerns across domain boundaries.
"""

from collections.abc import Callable
from typing import Any, ClassVar, Protocol, TypedDict

from sqlalchemy.orm import Mapped

# Domain types using PEP 695 type statements
type MatchResult = dict[str, Any]
type NodeID = str
type MetricName = str
type AttributeName = str


# Simplified type aliases for complex types
type MetricMapping = dict[MetricName, MetricName]
type FactoryFunction = Callable[[dict], Any]


class MatchResultProtocol(Protocol):
    """Protocol for match results from entity resolution."""

    success: bool
    play_count: Any  # Can be more specific if needed
    confidence: int


class Extractor(Protocol):
    """Generic extractor for connector data."""

    def __call__(self, obj: Any) -> Any: ...


class ConnectorConfig(TypedDict):
    """Connector configuration with extractors."""

    extractors: dict[str, Extractor]
    dependencies: list[str]
    factory: Callable[[dict], Any]
    metrics: dict[str, str]


class ModelClass(Protocol):
    """Protocol for database model classes.

    Defines the contract that SQLAlchemy model classes must satisfy,
    enabling type-safe repository operations.
    """

    # Instance attributes
    id: Mapped[int]
    is_deleted: Mapped[bool]

    # Class attribute - this is what SQLAlchemy expects
    __mapper__: ClassVar[Any]


class MappingTable(Protocol):
    """Protocol for mapping tables.

    Defines the contract for cross-connector entity resolution tables
    that map tracks between different identification systems.
    """

    connector_name: Mapped[str]
    connector_track_id: Mapped[str]


class MetricResolver(Protocol):
    """Protocol for resolving metrics from persistence layer."""

    async def resolve(
        self,
        track_ids: list[int],
        metric_name: str,
    ) -> dict[str, Any]: ...


# Simple module-level registries
metric_resolvers: dict[str, MetricResolver] = {}
metric_freshness: dict[str, int] = {
    # Default freshness for all metrics (in hours)
    "default": 24,
    # Specific overrides for time-sensitive metrics
    "lastfm_user_playcount": 1,
    "lastfm_global_playcount": 24,
    "lastfm_listeners": 24,
    "spotify_popularity": 24,
}


def register_metric_resolver(metric_name: str, resolver: MetricResolver) -> None:
    """Register a metric resolver implementation."""
    metric_resolvers[metric_name] = resolver
    
    
def get_metric_freshness(metric_name: str) -> int:
    """Get the freshness requirement (in hours) for a metric.
    
    Args:
        metric_name: The name of the metric to check
        
    Returns:
        Maximum age in hours before the metric is considered stale
    """
    return metric_freshness.get(metric_name, metric_freshness["default"])
