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
    that map between different identification systems.
    """

    connector_name: Mapped[str]
    connector_id: Mapped[str]
