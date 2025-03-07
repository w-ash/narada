"""
Factory system for workflow nodes with unified patterns.

This module provides a declarative, configuration-driven approach to node creation
that minimizes code surface area while maintaining maximum flexibility.
"""

from collections.abc import Awaitable, Callable
from typing import cast

from narada.config import get_logger
from narada.core.matcher import ConnectorType, batch_match_tracks, create_engine
from narada.core.models import TrackList
from narada.core.repositories import TrackRepository
from narada.database.database import get_session
from narada.integrations import CONNECTORS
from narada.workflows.destination_nodes import DESTINATION_HANDLERS
from narada.workflows.node_context import NodeContext
from narada.workflows.source_nodes import spotify_playlist_source
from narada.workflows.transform_registry import TRANSFORM_REGISTRY

logger = get_logger(__name__)

# Type definitions
type NodeFn = Callable[[dict, dict], Awaitable[dict]]


# === CORE NODE FACTORY ===


def make_node(
    category: str,
    node_type: str,
    operation_name: str | None = None,
) -> NodeFn:
    """
    Create a node function from registry configuration.

    Args:
        category: Node category (filter, sorter, etc.)
        node_type: Specific node type within category
        operation_name: Optional operation name for logging

    Returns:
        Async node function compatible with workflow system
    """
    if category not in TRANSFORM_REGISTRY:
        raise ValueError(f"Unknown node category: {category}")

    if node_type not in TRANSFORM_REGISTRY[category]:
        raise ValueError(f"Unknown node type: {node_type} in category {category}")

    # Get transform factory from registry
    transform_factory = TRANSFORM_REGISTRY[category][node_type]
    operation = operation_name or f"{category}.{node_type}"

    async def node_impl(context: dict, config: dict) -> dict:  # noqa
        ctx = NodeContext(context)

        # Special handling for combiners which use multiple upstreams
        if category == "combiner":
            # Get upstream task IDs
            upstream_task_ids = context.get("upstream_task_ids", [])

            if not upstream_task_ids:
                raise ValueError(f"Combiner node {operation} requires upstream tasks")

            # Collect tracklists from all upstream tasks
            upstream_tracklists = ctx.collect_tracklists(upstream_task_ids)

            if not upstream_tracklists:
                raise ValueError(
                    f"No valid tracklists found in upstream tasks for {operation}",
                )

            # Apply transformation using collected tracklists
            transform = transform_factory(ctx, config)
            result = transform(TrackList())  # Transform handles collection

            return {
                "tracklist": result,
                "operation": operation,
                "input_count": len(upstream_tracklists),
                "output_count": len(result.tracks),
            }

        else:
            # Standard case - single upstream dependency
            try:
                # Extract tracklist from primary upstream task
                tracklist = ctx.extract_tracklist()

                # Create and apply the transformation
                transform = transform_factory(ctx, config)
                result = transform(tracklist)

                return {
                    "tracklist": result,
                    "operation": operation,
                    "input_count": len(tracklist.tracks),
                    "output_count": len(result.tracks),
                }
            except Exception as e:
                logger.error(f"Error in node {operation}: {e}")
                raise

    return node_impl


# === ENRICHER FACTORY ===


def create_enricher_node(config: dict) -> NodeFn:
    """Create an enricher node for metadata enrichment of tracks.

    The enricher node is responsible for enhancing a tracklist with metadata
    from external services (e.g., LastFM, Spotify). It:

    1. Takes tracks from an input tracklist
    2. Uses the matcher to resolve track identities across services
    3. Retrieves metadata for successfully matched tracks
    4. Attaches the metadata as metrics to the tracklist

    This maintains a separation where the matcher handles identity resolution
    while the enricher focuses on metadata retrieval and attachment.

    Args:
        config: Configuration for the enricher, including:
            - connector: Name of the connector to use (e.g., "lastfm", "spotify")
            - attributes: List of attributes to extract from the connector

    Returns:
        An async node function compatible with the workflow system
    """
    enricher_type = config.get("connector")

    if enricher_type not in CONNECTORS:
        raise ValueError(f"Unsupported connector: {enricher_type}")

    # Store configuration for this specific enricher
    enricher_config = CONNECTORS[enricher_type]

    async def node_impl(context: dict, node_config: dict) -> dict:
        ctx = NodeContext(context)
        tracklist = ctx.extract_tracklist()

        logger = get_logger(__name__)
        with logger.contextualize(operation="enrichment", connector=enricher_type):
            logger.info(
                f"Starting enrichment with {enricher_type}",
                track_count=len(tracklist.tracks),
            )

            # Initialize primary connector
            connector_instance = enricher_config["factory"](node_config)

            # Initialize dependencies
            dependencies = {}
            for dep_name in enricher_config.get("dependencies", []):
                if dep_name in CONNECTORS:
                    dependencies[dep_name] = CONNECTORS[dep_name]["factory"](
                        node_config,
                    )

            # Create engine with properly assigned connectors
            engine = create_engine(
                lastfm=connector_instance
                if enricher_type == "lastfm"
                else dependencies.get("lastfm"),
                musicbrainz=connector_instance
                if enricher_type == "musicbrainz"
                else dependencies.get("musicbrainz"),
            )

            # Match tracks to target service
            async with get_session() as session:
                track_repo = TrackRepository(session)

                logger.debug("Matching tracks to service", connector=enricher_type)
                match_results = await batch_match_tracks(
                    tracklist.tracks,
                    cast("ConnectorType", enricher_type),
                    engine,
                    track_repo,
                )

                # Extract metrics from match results
                metrics = {}

                for attr in config.get("attributes", []):
                    extractor = enricher_config["extractors"].get(attr)
                    if not extractor:
                        logger.warning(
                            f"No extractor defined for {attr}",
                            connector=enricher_type,
                        )
                        continue

                    with logger.contextualize(attribute=attr):
                        logger.debug("Extracting attribute")
                        values = {}

                        for track_id, result in match_results.items():
                            if not result.success:
                                continue

                            try:
                                # Special handling for play counts
                                if attr == "user_play_count" and hasattr(
                                    result,
                                    "play_count",
                                ):
                                    value = (
                                        result.play_count.user_play_count
                                        if result.play_count
                                        else None
                                    )
                                elif attr == "global_play_count" and hasattr(
                                    result,
                                    "play_count",
                                ):
                                    value = (
                                        result.play_count.global_play_count
                                        if result.play_count
                                        else None
                                    )
                                else:
                                    # Use the configured extractor for other attributes
                                    value = extractor(result)

                                if value is not None:
                                    values[str(track_id)] = value
                            except Exception as e:
                                logger.exception(
                                    "Failed to extract attribute",
                                    track_id=track_id,
                                    error=str(e),
                                )

                        if values:
                            metrics[attr] = values
                            logger.info("Extracted attribute", count=len(values))
                        else:
                            logger.warning("No values extracted")

                # Add metrics to tracklist
                enriched = tracklist
                if metrics:
                    current = enriched.metadata.get("metrics", {})
                    enriched = enriched.with_metadata("metrics", {**current, **metrics})

                logger.info("Enrichment complete", metrics_count=len(metrics))
                return {
                    "tracklist": enriched,
                    "match_results": match_results,
                    "operation": f"{enricher_type}_enrichment",
                }

    return node_impl


# === DESTINATION FACTORY ===


def create_destination_node(destination_type: str) -> NodeFn:
    """Create a destination node using handler registry."""
    if destination_type not in DESTINATION_HANDLERS:
        raise ValueError(f"Unsupported destination type: {destination_type}")

    handler = DESTINATION_HANDLERS[destination_type]

    async def node_impl(context: dict, config: dict) -> dict:
        ctx = NodeContext(context)
        tracklist = ctx.extract_tracklist()

        logger.debug(
            "Destination received tracklist with metrics",
            metrics_keys=list(tracklist.metadata.get("metrics", {}).keys()),
        )

        return await handler(tracklist, config, context)

    return node_impl


# === NODE CREATION HELPERS ===


def create_filter_node(filter_type: str, operation_name: str | None = None) -> NodeFn:
    """Create a filter node of specified type."""
    return make_node("filter", filter_type, operation_name)


def create_sorter_node(sorter_type: str, operation_name: str | None = None) -> NodeFn:
    """Create a sorter node of specified type."""
    return make_node("sorter", sorter_type, operation_name)


def create_selector_node(
    selector_type: str,
    operation_name: str | None = None,
) -> NodeFn:
    """Create a selector node of specified type."""
    return make_node("selector", selector_type, operation_name)


def create_combiner_node(
    combiner_type: str,
    operation_name: str | None = None,
) -> NodeFn:
    """Create a combiner node of specified type."""
    return make_node("combiner", combiner_type, operation_name)


# Export direct reference to source node for registry
spotify_playlist_source = spotify_playlist_source
