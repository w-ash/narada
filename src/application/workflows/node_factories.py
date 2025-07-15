"""
Factory system for workflow nodes with unified patterns.

This module provides a declarative, configuration-driven approach to node creation
that minimizes code surface area while maintaining maximum flexibility.

Clean Architecture compliant - uses dependency injection for external concerns.
"""

from collections.abc import Awaitable, Callable

from src.domain.entities.track import TrackList
from src.infrastructure.config import get_logger
from src.infrastructure.connectors import CONNECTORS
from src.application.use_cases.match_tracks import match_tracks

from .destination_nodes import DESTINATION_HANDLERS
from .node_context import NodeContext
from .protocols import WorkflowContext
from .transform_registry import TRANSFORM_REGISTRY

# Type definitions
type NodeFn = Callable[[dict, dict], Awaitable[dict]]

logger = get_logger(__name__)


# === CORE NODE FACTORY ===


class WorkflowNodeFactory:
    """Factory for creating workflow nodes with dependency injection."""

    def __init__(self, context: WorkflowContext):
        """Initialize factory with workflow context."""
        self.context = context
        self.logger = context.logger

    def make_node(
        self,
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
                    raise ValueError(
                        f"Combiner node {operation} requires upstream tasks"
                    )

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
                    self.logger.error(f"Error in node {operation}: {e}")
                    raise

        return node_impl

    # === ENRICHER FACTORY ===

    def create_enricher_node(self, config: dict) -> NodeFn:
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
        if not enricher_type:
            raise ValueError("Connector type is required")
        if enricher_type not in CONNECTORS:
            raise ValueError(f"Unsupported connector: {enricher_type}")

        # Retrieve connector configuration once at creation time
        enricher_config = CONNECTORS[enricher_type]

        # Get connector from registry via dependency injection

        async def node_impl(context: dict, node_config: dict) -> dict:
            ctx = NodeContext(context)
            tracklist = ctx.extract_tracklist()

            # Initialize connector instance
            connector_instance = enricher_config["factory"](node_config)

            # Create repository instance for matcher (short-lived for workflow execution)
            from src.infrastructure.persistence.database.db_connection import (
                get_session,
            )
            from src.infrastructure.persistence.repositories.track import (
                TrackRepositories,
            )
            from src.application.use_cases.match_tracks import match_tracks

            async with get_session() as session:
                track_repos = TrackRepositories(session)

                # Resolve track identities through matcher service
                match_results = await match_tracks(
                    tracklist,
                    enricher_type,
                    connector_instance,
                    track_repos,
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

                    value = extractor(result.service_data)
                    if value is not None:
                        values[track_id] = value

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


# Compatibility functions for existing workflow code
def make_node(
    category: str, node_type: str, operation_name: str | None = None
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
    enricher_config = CONNECTORS[enricher_type]

    async def node_impl(context: dict, node_config: dict) -> dict:
        ctx = NodeContext(context)
        tracklist = ctx.extract_tracklist()

        # Initialize connector instance
        connector_instance = enricher_config["factory"](node_config)

        # Create repository instance for matcher (short-lived for workflow execution)
        from src.infrastructure.persistence.database.db_connection import get_session
        from src.infrastructure.persistence.repositories.track import TrackRepositories

        async with get_session() as session:
            track_repos = TrackRepositories(session)

            # Resolve track identities through matcher service
            match_results = await match_tracks(
                tracklist,
                enricher_type,
                connector_instance,
                track_repos,
            )

        # Extract configured metrics from match results
        metrics = {}

        for attr in config.get("attributes", []):
            extractor = enricher_config["extractors"].get(attr)
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
                    elif extractor:
                        # Use configured extractor for standard attributes
                        value = extractor(result)
                    else:
                        # Skip if no extractor and not in service_data
                        continue

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
