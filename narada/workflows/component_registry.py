"""
Component registry system for workflow execution.

This module provides the central registry for all workflow components,
handling registration, discovery, and metadata management. It facilitates
the dynamic lookup of components by name when building workflows.

The registry supports both direct component implementations and
factory-created components to enable consistent patterns across the system.
"""

from functools import wraps
from typing import Any, Awaitable, Callable, Dict, Literal, Optional, Protocol, Tuple

# Type definitions
ComponentFunc = Callable[[dict, dict], Awaitable[dict]]
ComponentMeta = Dict[str, Any]
ComponentType = Literal[
    "source", "enricher", "filter", "sorter", "selector", "combiner", "destination"
]


# Component protocol for static type checking
class Component(Protocol):
    """Protocol defining the interface for workflow components."""

    async def __call__(self, context: dict, config: dict) -> dict: ...


# Initialize global registry
_COMPONENT_REGISTRY: Dict[str, Tuple[ComponentFunc, ComponentMeta]] = {}


def component(
    component_id: str,
    *,
    description: str = "",
    input_type: Optional[str] = None,
    output_type: Optional[str] = None,
    category: Optional[ComponentType] = None,
) -> Callable[[ComponentFunc], ComponentFunc]:
    """
    Register a component with the global registry.

    Args:
        component_id: Unique identifier for the component
        description: Human-readable description
        input_type: Type of input the component expects
        output_type: Type of output the component produces
        category: Component category (source, filter, etc.)

    Returns:
        Decorator function that registers the component
    """

    def decorator(func: ComponentFunc) -> ComponentFunc:
        # Extract category from component_id if not provided
        derived_category = category or component_id.split(".", 1)[0]

        # Create component metadata
        metadata = {
            "id": component_id,
            "description": description,
            "input_type": input_type,
            "output_type": output_type,
            "category": derived_category,
            "factory_created": hasattr(func, "__factory__"),
            "transform_functions": getattr(func, "__transforms__", []),
        }

        # Preserve function metadata with wraps
        @wraps(func)
        async def wrapper(context: dict, config: dict) -> dict:
            return await func(context, config)

        # Store in registry
        _COMPONENT_REGISTRY[component_id] = (wrapper, metadata)
        return wrapper

    return decorator


def register_factory_component(
    component_id: str,
    factory_func: ComponentFunc,
    description: str = "",
    input_type: Optional[str] = None,
    output_type: Optional[str] = None,
    transforms: list[str] = None,
    category: Optional[ComponentType] = None,
) -> ComponentFunc:
    """
    Register a component created via factory pattern.

    Args:
        component_id: Unique identifier for the component
        factory_func: Factory-created component implementation
        description: Human-readable description
        input_type: Type of input the component expects
        output_type: Type of output the component produces
        transforms: List of transformation functions used
        category: Component category (source, filter, etc.)

    Returns:
        The registered component function
    """
    # Mark function as factory-created
    setattr(factory_func, "__factory__", True)
    if transforms:
        setattr(factory_func, "__transforms__", transforms)

    # Create the decorator
    decorator = component(
        component_id,
        description=description,
        input_type=input_type,
        output_type=output_type,
        category=category,
    )

    # Apply the decorator
    return decorator(factory_func)


def get_component(component_id: str) -> Tuple[ComponentFunc, ComponentMeta]:
    """
    Get a component implementation and metadata by its ID.

    Args:
        component_id: The unique identifier for the component

    Returns:
        Tuple of (component_function, component_metadata)

    Raises:
        ValueError: If component_id is not registered
    """
    if component_id not in _COMPONENT_REGISTRY:
        raise ValueError(f"Component not found: {component_id}")
    return _COMPONENT_REGISTRY[component_id]


def list_components() -> Dict[str, ComponentMeta]:
    """
    List all registered components and their metadata.

    Returns:
        Dictionary mapping component IDs to their metadata
    """
    return {cid: meta for cid, (_, meta) in _COMPONENT_REGISTRY.items()}


def get_components_by_category(category: ComponentType) -> Dict[str, ComponentMeta]:
    """
    Get all components of a specific category.

    Args:
        category: Component category to filter by

    Returns:
        Dictionary mapping component IDs to their metadata
    """
    return {
        cid: meta
        for cid, (_, meta) in _COMPONENT_REGISTRY.items()
        if meta["category"] == category
    }
