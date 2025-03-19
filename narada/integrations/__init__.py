"""Service connectors for external music platforms and APIs."""

import importlib
import pkgutil
import sys
from typing import Any

from narada.config import get_logger
from narada.core.protocols import ConnectorConfig

# Import main connector classes for re-export
from narada.integrations.lastfm import (
    LastFMConnector,
    LastFmMetricResolver,
    LastFMTrackInfo,
)
from narada.integrations.musicbrainz import MusicBrainzConnector
from narada.integrations.spotify import (
    SpotifyConnector,
    convert_spotify_playlist_to_domain,
    convert_spotify_track_to_domain,
)

logger = get_logger(__name__)

# Connector registry cache
_CONNECTORS: dict[str, ConnectorConfig] = {}


def discover_connectors() -> dict[str, ConnectorConfig]:
    """Discover and register connector configurations.

    Dynamically loads connector modules from the integrations package
    that implement the `get_connector_config()` interface. This creates a
    clean extension point for new connectors without factory code changes.

    Returns:
        Dictionary mapping connector names to their configurations
    """
    global _CONNECTORS

    # Return cached registry if already populated
    if _CONNECTORS:
        return _CONNECTORS

    # Get our own module for introspection
    module = sys.modules[__name__]
    package_path = module.__name__

    # Use pkgutil to find all modules in the package
    for _, name, ispkg in pkgutil.iter_modules(
        module.__path__,
        prefix=f"{package_path}.",
    ):
        if ispkg:
            continue  # Skip subpackages

        module_name = name.split(".")[-1]

        # Skip the __init__ module itself to avoid circular imports
        if module_name == "__init__":
            continue

        try:
            # Import the module
            connector_module = importlib.import_module(name)

            # Check if module implements connector interface
            if hasattr(connector_module, "get_connector_config"):
                # Register the connector by name
                _CONNECTORS[module_name] = connector_module.get_connector_config()
                logger.debug(f"Registered connector: {module_name}")
        except ImportError as e:
            logger.warning(f"Could not import connector module {module_name}: {e}")

    logger.info(
        f"Discovered {len(_CONNECTORS)} connectors: {', '.join(_CONNECTORS.keys())}",
    )
    return _CONNECTORS


# Initialize connector registry at module load time
CONNECTORS = discover_connectors()


# Define public API with explicit exports
__all__ = [
    "CONNECTORS",
    "LastFMConnector",
    "LastFMTrackInfo",
    "LastFmMetricResolver",
    "MusicBrainzConnector",
    "SpotifyConnector",
    "convert_spotify_playlist_to_domain",
    "convert_spotify_track_to_domain",
    "discover_connectors",
]
