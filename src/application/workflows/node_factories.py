"""
Factory system for workflow nodes with unified patterns.

This module provides a declarative, configuration-driven approach to node creation
that minimizes code surface area while maintaining maximum flexibility.

Clean Architecture compliant - uses dependency injection for external concerns.
"""

from collections.abc import Awaitable, Callable

# match_tracks import removed - modern enricher uses TrackMetadataEnricher directly
from src.config import get_logger
from src.domain.entities.track import TrackList
from src.infrastructure.connectors import CONNECTORS

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

    # === LEGACY ENRICHER IMPLEMENTATION REMOVED ===
    # The create_enricher_node method has been removed in favor of the
    # standalone create_enricher_node function that uses the modern
    # TrackMetadataEnricher with clean architecture separation.


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

        logger.info(
            f"Starting {enricher_type} enrichment for {len(tracklist.tracks)} tracks"
        )

        # Initialize connector instance
        connector_instance = enricher_config["factory"](node_config)

        # Create repository instance using shared session from workflow context
        from src.infrastructure.persistence.repositories.track import TrackRepositories

        # Use the shared session from workflow context to prevent database locks
        shared_session = context.get("shared_session")
        if not shared_session:
            raise ValueError("No shared session available in workflow context")

        track_repos = TrackRepositories(shared_session)

        # Get freshness configuration for this enricher
        max_age_hours = node_config.get("max_age_hours")
        if max_age_hours is None:
            # Get default freshness requirement from config
            from src.config import get_config

            config_key = f"ENRICHER_DATA_FRESHNESS_{enricher_type.upper()}"
            max_age_hours = get_config(config_key)

        if max_age_hours is not None:
            logger.info(
                f"Using data freshness requirement: {max_age_hours} hours for {enricher_type}"
            )

        # Use the new TrackMetadataEnricher for clean separation of concerns
        from src.infrastructure.services.track_metadata_enricher import (
            TrackMetadataEnricher,
        )

        enricher = TrackMetadataEnricher(track_repos)

        enriched, metrics = await enricher.enrich_tracks(
            tracklist,
            enricher_type,
            connector_instance,
            enricher_config["extractors"],
            max_age_hours,
        )

        return {
            "tracklist": enriched,
            "operation": f"{enricher_type}_enrichment",
            "metrics_count": sum(len(values) for values in metrics.values()),
        }

    return node_impl


def create_play_history_enricher_node() -> NodeFn:
    """Create a play history enricher node following Clean Architecture principles.

    This node enriches tracklists with play history data from the internal database,
    using dependency injection for repository access and proper separation of concerns.

    Returns:
        Workflow node function with standard (context, config) -> dict signature
    """

    async def node_impl(context: dict, config: dict) -> dict:
        from src.application.services.play_history_enricher import PlayHistoryEnricher
        from src.infrastructure.persistence.repositories.track import TrackRepositories

        ctx = NodeContext(context)
        tracklist = ctx.extract_tracklist()

        # Get configuration
        metrics = config.get("metrics", ["total_plays", "last_played_dates"])
        period_days = config.get("period_days")

        logger.info(
            f"Starting play history enrichment for {len(tracklist.tracks)} tracks"
        )

        # Use shared session from workflow context to prevent database locks
        shared_session = context.get("shared_session")
        if not shared_session:
            raise ValueError("No shared session available in workflow context")

        track_repos = TrackRepositories(shared_session)
        enricher = PlayHistoryEnricher(track_repos)

        enriched = await enricher.enrich_with_play_history(
            tracklist=tracklist,
            metrics=metrics,
            period_days=period_days,
        )

        play_metrics = enriched.metadata.get("metrics", {})
        metrics_count = sum(len(values) for values in play_metrics.values())

        return {
            "tracklist": enriched,
            "operation": "play_history_enrichment",
            "metrics_count": metrics_count,
            "enriched_metrics": list(play_metrics.keys()),
        }

    return node_impl
