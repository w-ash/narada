"""
Component registry system for workflow orchestration.

This module provides a centralized registry with a clean, declarative API for
component registration and discovery. It serves as the connection point between
workflow definitions and component implementations.
"""

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import (
    Literal,
    NotRequired,
    TypeAlias,
    TypedDict,
    get_origin,
    get_type_hints,
)

# Type definitions with modern annotation style
ComponentType: TypeAlias = Literal[
    "source",
    "enricher",
    "filter",
    "sorter",
    "selector",
    "combiner",
    "destination",
]

# Define strict component function type
ComponentFn: TypeAlias = Callable[[dict, dict], Awaitable[dict]]


class ComponentMetadata(TypedDict):
    """Type-safe component metadata."""

    id: str
    description: str
    category: ComponentType
    input_type: NotRequired[str]
    output_type: NotRequired[str]
    factory_created: NotRequired[bool]


# Singleton registry using a class-based pattern
class ComponentRegistry:
    """Registry for workflow components with simplified discovery."""

    def __init__(self) -> None:
        self._registry: dict[str, tuple[ComponentFn, ComponentMetadata]] = {}

    def register(
        self,
        component_id: str,
        *,
        description: str = "",
        input_type: str | None = None,
        output_type: str | None = None,
        category: ComponentType | None = None,
    ) -> Callable[[ComponentFn], ComponentFn]:
        """Register a component with the registry.

        Args:
            component_id: Unique identifier (e.g., "source.spotify_playlist")
            description: Human-readable description
            input_type: Type of input the component expects
            output_type: Type of output the component produces
            category: Component category (source, filter, etc.)

        Returns:
            Decorator that registers the component
        """

        def decorator(func: ComponentFn) -> ComponentFn:
            # Derive category from ID if not provided
            derived_category = category
            if not derived_category and "." in component_id:
                prefix = component_id.split(".", 1)[0]
                if prefix in self.get_valid_categories():
                    derived_category = prefix

            # Enforce category type
            if derived_category not in self.get_valid_categories():
                raise ValueError(f"Invalid component category: {derived_category}")

            # Create metadata
            metadata: ComponentMetadata = {
                "id": component_id,
                "description": description,
                "category": derived_category,  # type: ignore - we validated above
            }
            if input_type is not None:
                metadata["input_type"] = input_type
            if output_type is not None:
                metadata["output_type"] = output_type
            if hasattr(func, "__factory__"):
                metadata["factory_created"] = True

            # Preserve function metadata with wraps
            @wraps(func)
            async def wrapper(context: dict, config: dict) -> dict:
                return await func(context, config)

            # Store in registry
            self._registry[component_id] = (wrapper, metadata)
            return wrapper

        return decorator

    def component(
        self, component_id: str, **kwargs
    ) -> Callable[[ComponentFn], ComponentFn]:
        """Simpler alias for register."""
        return self.register(component_id, **kwargs)

    def get_component(self, component_id: str) -> tuple[ComponentFn, ComponentMetadata]:
        """Get a component by ID.

        Args:
            component_id: The component's unique identifier

        Returns:
            Tuple of (component_function, metadata)

        Raises:
            KeyError: If component not found
        """
        if component_id not in self._registry:
            raise KeyError(f"Component not found: {component_id}")
        return self._registry[component_id]

    def list_components(self) -> dict[str, ComponentMetadata]:
        """List all registered components."""
        return {cid: meta for cid, (_, meta) in self._registry.items()}

    def get_by_category(self, category: ComponentType) -> dict[str, ComponentMetadata]:
        """Get components filtered by category."""
        return {
            cid: meta
            for cid, (_, meta) in self._registry.items()
            if meta["category"] == category
        }

    @staticmethod
    def get_valid_categories() -> set[ComponentType]:
        """Get all valid component categories."""
        # Extract literals from ComponentType annotation
        origin = get_origin(ComponentType)
        if origin is Literal:
            args = get_type_hints(ComponentType)["__args__"]
            return set(args)
        return set()


# Create global registry instance
registry = ComponentRegistry()

# Export main decorator for clean imports
component = registry.component

# Export utility functions with clear names
get_component = registry.get_component
list_components = registry.list_components
get_components_by_category = registry.get_by_category
