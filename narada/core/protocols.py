"""Core protocols and interfaces for the node factory system.

Defines contract interfaces between system components, enabling loose coupling
and clear separation of concerns across domain boundaries.
"""

from collections.abc import Callable
from typing import Any, Protocol, TypedDict

# Domain types using PEP 695 type statements
type MatchResult = dict[str, Any]
type Track = dict[str, Any]
type NodeID = str
type MetricName = str
type AttributeName = str


# Simplified type aliases for complex types
type ExtractorMapping = dict[AttributeName, ExtractorProtocol]
type MetricMapping = dict[MetricName, MetricName]
type FactoryFunction = Callable[[dict], Any]


class ExtractorProtocol(Protocol):
    """Protocol for attribute extractors.

    Extractors transform raw connector results into standardized domain attributes,
    providing a uniform interface across different data sources.
    """

    def __call__(self, result: MatchResult, _: Track) -> Any:
        """Extract attribute from connector result.

        Args:
            result: Structured result from connector API
            _: Track object for context (usually unused)

        Returns:
            Extracted attribute value in standardized format
        """
        ...


class ConnectorConfig(TypedDict):
    """Configuration for a connector integration.

    Defines the contract between node factories and connector implementations,
    specifying how connector-specific data is mapped to domain concepts.
    """

    extractors: ExtractorMapping
    """Mapping of attribute names to their extractor functions."""

    dependencies: list[NodeID]
    """Node IDs this connector depends on for execution."""

    factory: FactoryFunction
    """Factory function to create connector instances."""

    metrics: MetricMapping
    """Mapping of connector-specific metric names to canonical metric names."""
