"""Narada music integration platform."""

# Version detection with environment-aware fallback pattern
try:
    from importlib.metadata import PackageNotFoundError, version

    try:
        __version__ = version("narada")
    except PackageNotFoundError:
        # Development environment fallback
        __version__ = "0.1.3-dev"
except ImportError:
    # Extreme fallback for environments without importlib.metadata
    __version__ = "0.1.3-dev"

__author__ = "Ash Wright"
__license__ = "MIT"

# Basic configuration and logging must come first
from narada.config import get_logger, resilient_operation, setup_loguru_logger

# Initialize logging early to ensure log directory exists
setup_loguru_logger()

# Now initialize logger that will be used by other modules
logger = get_logger(__name__)

# Import workflow core early to ensure registry initialization
from narada.workflows.node_registry import get_node, node  # noqa: E402

__all__ = [
    "app",
    "get_logger",
    "get_node",
    "main",
    "node",
    "resilient_operation",
    "run_workflow",
    "validate_registry",
]

# CLI components (must come after workflow initialization to avoid circular imports)
from narada.cli import app  # noqa: E402
from narada.cli.app import main  # noqa: E402
from narada.workflows import run_workflow, validate_registry  # noqa: E402

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

# Re-export key workflow functions for convenience
from narada.workflows import validate_registry  # noqa: E402
