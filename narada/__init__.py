"""Narada music integration platform."""

from importlib.metadata import version

__version__ = version("narada")
__author__ = "Ash Wright"
__license__ = "MIT"

# CLI components (must come after workflow initialization to avoid circular imports)
from narada.cli import app
from narada.cli.app import main

# Basic configuration and logging must come first
from narada.config import get_logger, resilient_operation

# Re-export key workflow functions for convenience
from narada.workflows import run_workflow, validate_registry

# Import workflow core early to ensure registry initialization
from narada.workflows.node_registry import get_node, node

__all__ = [
    # CLI interfaces
    "app",
    "main",
    # Configuration and utilities
    "get_logger",
    "resilient_operation",
    # Workflow system
    "run_workflow",
    "validate_registry",
    "get_node",
    "node",
]

# Trigger workflows validation during package import
# Using a try/except to prevent issues during import
try:
    success, message = validate_registry()
    logger = get_logger(__name__)
    if success:
        logger.debug(f"Workflow registry: {message}")
    else:
        logger.warning(f"Workflow registry validation issue: {message}")
except Exception as e:
    # Only log at debug level to avoid noise during normal imports
    # Actual validation will happen again during CLI startup
    import logging

    logging.getLogger(__name__).debug(f"Early workflow validation deferred: {e}")
