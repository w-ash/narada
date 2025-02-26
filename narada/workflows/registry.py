"""Component registry system for workflow definitions.

This module provides a lean type system for registering and retrieving
workflow components. It uses a simple decorator pattern to minimize
boilerplate while maintaining clear component contracts.

Interactions:
    Consumes: Component implementations from components.py
    Produces: Registration system and lookup functionality
    Key principle: Registry knows components exist but not how they work

This is the type system - it maintains the mapping between component names in workflow definitions and their implementations.

"""

import inspect
from typing import Callable, Optional, TypedDict


# Type definition for component metadata
class ComponentMeta(TypedDict, total=False):
    """Component metadata with optional documentation."""

    name: str
    description: str
    input_schema: dict
    output_type: str


# Central component registry
_COMPONENTS: dict[str, tuple[Callable, ComponentMeta]] = {}


def component(
    type_name: str,
    *,
    description: str = "",
    input_schema: Optional[dict] = None,
    output_type: str = "playlist",
) -> Callable:
    """Register a function as a workflow component.

    Args:
        type_name: Unique identifier for this component (e.g., "filter.by_date")
        description: Human-readable description for UI/documentation
        input_schema: JSON Schema for component configuration
        output_type: Expected output type identifier

    Returns:
        Decorator function that registers the component
    """

    def decorator(func: Callable) -> Callable:
        # Extract docstring if description not provided
        doc = description or inspect.getdoc(func) or ""

        # Create minimal metadata
        meta: ComponentMeta = {
            "name": type_name,
            "description": doc,
            "output_type": output_type,
        }

        # Add schema if provided
        if input_schema:
            meta["input_schema"] = input_schema

        # Register the component
        _COMPONENTS[type_name] = (func, meta)
        return func

    return decorator


def get_component(type_name: str) -> tuple[Callable, ComponentMeta]:
    """Get a component implementation by its type name.

    Args:
        type_name: Component type identifier

    Returns:
        Tuple of (component_function, metadata)

    Raises:
        ValueError: If component type doesn't exist
    """
    if type_name not in _COMPONENTS:
        raise ValueError(f"Unknown component: {type_name}")
    return _COMPONENTS[type_name]


def list_components() -> list[ComponentMeta]:
    """List all registered components with their metadata.

    Returns:
        List of component metadata dictionaries
    """
    return [meta for _, meta in _COMPONENTS.values()]


def get_component_types() -> list[str]:
    """Get all registered component type names.

    Returns:
        List of component type strings
    """
    return list(_COMPONENTS.keys())
