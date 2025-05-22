"""
Factory system for workflow nodes with unified patterns.

This module provides a declarative, configuration-driven approach to node creation
that minimizes code surface area while maintaining maximum flexibility.
"""

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from narada.config import get_logger
from narada.core.matcher import batch_match_tracks
from narada.core.models import TrackList
from narada.integrations import CONNECTORS
from narada.workflows.destination_nodes import DESTINATION_HANDLERS
from narada.workflows.node_context import NodeContext
from narada.workflows.source_nodes import spotify_playlist_source
from narada.workflows.transform_registry import TRANSFORM_REGISTRY

if TYPE_CHECKING:
    from narada.integrations.protocols import ConnectorConfig

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
    """Create an enricher node for metadata extraction and attachment.

    Architectural separation of concerns:
    - Matcher: Resolves identity ("Is internal track X the same as connector track X?")
    - Integration: Handles external API communication
    - Repository: Manages persistence of identified tracks
    - Enricher: Coordinates the process and extracts/attaches metadata

    This clean architecture ensures:
    1. Each component has a single responsibility
    2. Components can evolve independently
    3. Testing can be performed in isolation

    Workflow steps:
    1. Extract tracks from input tracklist
    2. Resolve track identity across services via matcher
    3. Extract valuable metadata attributes
    4. Attach metrics to tracklist for downstream operations

    Args:
        config: Configuration dictionary containing:
            - connector: Service to extract data from (e.g., "lastfm", "spotify")
            - attributes: Metadata fields to extract and attach

    Returns:
        Workflow node function with standard (context, config) -> dict signature
    """
    enricher_type = config.get("connector")

    if enricher_type not in CONNECTORS:
        raise ValueError(f"Unsupported connector: {enricher_type}")

    # Retrieve connector configuration once at creation time
    enricher_config: ConnectorConfig = CONNECTORS[enricher_type]

    async def node_impl(context: dict, node_config: dict) -> dict:
        ctx = NodeContext(context)
        tracklist = ctx.extract_tracklist()

        # Initialize connector instance
        connector_instance = enricher_config["factory"](node_config)

        # Resolve track identities through matcher service
        match_results = await batch_match_tracks(
            tracklist,
            enricher_type,
            connector_instance,
        )

        # Extract configured metrics from match results
        metrics = {}

        for attr in config.get("attributes", []):
            extractor = enricher_config["extractors"].get(attr)
            if not extractor:
                continue

            values = {}

            # Extract metrics from successful matches
            for track_id, result in match_results.items():
                if not result.success or track_id is None:
                    continue

                try:
                    # Extract value using the appropriate method based on the attribute
                    if attr in result.service_data:
                        # Direct access from service_data if available there
                        value = result.service_data.get(attr)
                    else:
                        # Use configured extractor for standard attributes
                        value = extractor(result)

                    if value is not None:
                        # Use integer track IDs consistently
                        values[track_id] = value
                except Exception as e:
                    logger.debug(
                        f"Failed to extract attribute '{attr}' for track {track_id}: {e}"
                    )

            if values:
                metrics[attr] = values

        # Attach metrics to tracklist
        if metrics:
            current_metrics = tracklist.metadata.get("metrics", {})
            enriched = tracklist.with_metadata(
                "metrics",
                {**current_metrics, **metrics},
            )
        else:
            enriched = tracklist

        return {
            "tracklist": enriched,
            "match_results": match_results,
            "operation": f"{enricher_type}_enrichment",
            "metrics_count": len(metrics),
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
    """Create a sorter node with integrated metadata resolution."""
    # Get base transform
    transform_fn = make_node("sorter", sorter_type, operation_name)

    async def node_with_resolution(context: dict, config: dict) -> dict:
        """Node wrapper that resolves metrics before transformation."""
        ctx = NodeContext(context)

        # Extract the metric name from config for by_metric
        needed_metric = (
            config.get("metric_name") if sorter_type == "by_metric" else None
        )

        # Only attempt resolution if this transform needs metrics
        if needed_metric:
            tracklist = ctx.extract_tracklist()
            metrics = tracklist.metadata.get("metrics", {})

            # Check if metrics need resolution
            if needed_metric not in metrics or not metrics[needed_metric]:
                # We're already in async context, so we can await directly
                from narada.integrations.metrics_registry import metric_resolvers

                if needed_metric in metric_resolvers:
                    track_ids = [t.id for t in tracklist.tracks if t.id]
                    if track_ids:
                        # Resolve and log metrics in a simpler way
                        resolved = await metric_resolvers[needed_metric].resolve(
                            track_ids,
                            needed_metric,
                        )

                        if resolved:
                            # Single, focused log with key metrics
                            non_zero_count = sum(1 for v in resolved.values() if v != 0)
                            logger.info(
                                f"Resolved {needed_metric} metrics",
                                tracks=len(track_ids),
                                metrics_found=len(resolved),
                                non_zero=non_zero_count,
                            )

                            # Update tracklist in context with resolved metrics
                            updated = tracklist.with_metadata(
                                "metrics",
                                {
                                    **metrics,
                                    needed_metric: resolved,
                                },
                            )

                            # Update in context for transform to use
                            upstream_id = ctx.data.get("upstream_task_id")
                            if upstream_id in context:
                                context[upstream_id]["tracklist"] = updated

        # Now run transform with metrics available
        return await transform_fn(context, config)

    return node_with_resolution


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
