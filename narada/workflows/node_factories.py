"""
Factory system for workflow nodes with unified patterns.

Provides a declarative, configuration-driven approach to node creation that
minimizes code surface area while maintaining maximum flexibility.
"""

from collections.abc import Awaitable, Callable
import importlib
from typing import Any

from narada.config import get_logger
from narada.core.matcher import MatchResult, batch_match_tracks, create_engine
from narada.core.models import Playlist, Track, TrackList
from narada.core.protocols import ConnectorConfig
from narada.core.repositories import PlaylistRepository, TrackRepository
from narada.core.transforms import (
    concatenate,
    exclude_artists,
    exclude_tracks,
    filter_by_date_range,
    filter_duplicates,
    interleave,
    select_by_method,
    sort_by_attribute,
)
from narada.data.database import get_session
from narada.workflows.node_context import Context

logger = get_logger(__name__)


# === TYPE DEFINITIONS ===
type NodeFn = Callable[[dict, dict], Awaitable[dict]]
type KeyFn = Callable[[Track], Any]
type PredicateFn = Callable[[Track], bool]
type TrackExtractor = Callable[[Track], Any]
type ResultExtractor = Callable[[MatchResult], Any]
type AnyExtractor = TrackExtractor | ResultExtractor


# === CONNECTOR REGISTRY ===

CONNECTORS: dict[str, ConnectorConfig] = {}


def discover_connectors() -> dict[str, ConnectorConfig]:
    """Dynamically discover and register connector configurations.

    Scans the integrations package for modules that implement the
    connector interface (get_connector_config). This creates a clean
    extension point for new connectors without modifying factory code.

    Returns:
        Dictionary mapping connector names to their configurations
    """
    if CONNECTORS:  # Return cached registry if already populated
        return CONNECTORS

    # Identify the integrations package
    base_package = "narada.integrations"

    try:
        # Import the base package
        package = importlib.import_module(base_package)

        # Get all modules in the package
        for module_name in getattr(package, "__all__", []) or []:
            full_module_name = f"{base_package}.{module_name}"

            try:
                # Import the module
                module = importlib.import_module(full_module_name)

                # Check if module implements connector interface
                if hasattr(module, "get_connector_config"):
                    connector_name = module_name.split(".")[
                        -1
                    ]  # Extract name from path
                    CONNECTORS[connector_name] = module.get_connector_config()
                    logger.debug(f"Registered connector: {connector_name}")
            except ImportError as e:
                logger.warning(f"Could not import connector module {module_name}: {e}")

    except ImportError as e:
        logger.error(f"Error discovering connectors: {e}")

    logger.info(
        f"Discovered {len(CONNECTORS)} connectors: {', '.join(CONNECTORS.keys())}",
    )
    return CONNECTORS


discover_connectors()


# === TRANSFORM REGISTRY ===
# This declarative approach maps node types to their implementations
TRANSFORM_REGISTRY = {
    "filter": {
        "deduplicate": lambda _ctx, _cfg: filter_duplicates(),
        "by_release_date": lambda _ctx, cfg: filter_by_date_range(
            cfg.get("min_age_days"),
            cfg.get("max_age_days"),
        ),
        "by_tracks": lambda ctx, cfg: exclude_tracks(
            ctx.data[cfg["exclusion_source"]]["tracklist"].tracks,
        ),  # Return transform function, don't apply immediately
        "by_artists": lambda ctx, cfg: exclude_artists(
            ctx.data[cfg["exclusion_source"]]["tracklist"].tracks,
            cfg.get("exclude_all_artists", False),
        ),  # Return transform function, don't apply immediately
    },
    "sorter": {
        "by_user_plays": lambda ctx, cfg: sort_by_attribute(
            key_fn=lambda track: (
                ctx.get(f"match_results.{track.id}.user_play_count", 0)
                if track.id
                else 0
            ),
            metric_name="user_play_count",
            reverse=cfg.get("reverse", True),
        ),
        "by_spotify_popularity": lambda _ctx, cfg: sort_by_attribute(
            key_fn=lambda track: track.get_connector_attribute(
                "spotify",
                "popularity",
                0,
            ),
            metric_name="spotify_popularity",
            reverse=cfg.get("reverse", True),
        ),
    },
    "selector": {
        "limit_tracks": lambda _ctx, cfg: select_by_method(
            cfg.get("count", 10),
            cfg.get("method", "first"),
        ),
    },
    "combiner": {
        "merge_playlists": lambda ctx, cfg: concatenate(
            ctx.collect_tracklists(cfg.get("sources", [])),
        ),
        "concatenate_playlists": lambda ctx, cfg: concatenate(
            ctx.collect_tracklists(cfg.get("order", [])),
        ),
        "interleave_playlists": lambda ctx, cfg: interleave(
            ctx.collect_tracklists(cfg.get("sources", [])),
        ),
    },
}


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

    # Create node implementation

    async def node_impl(context: dict, config: dict) -> dict:  # noqa: RUF029
        ctx = Context(context)

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

            # Create the appropriate transform
            transform = transform_factory(ctx, config)

            # Apply transformation using collected tracklists
            # Note: The transform expects a list of tracklists for combiners
            result = transform(
                TrackList(),
            )  # Empty tracklist as base, transform handles collection

            # Return result with operation metadata
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


# === DESTINATION FACTORY ===
# This should replace the current destination_factory function in node_factories.py


class DestinationHandler:
    """Strategic destination handler for workflow endpoints.

    Implements the Strategy pattern for destination operations, allowing for modular
    extension of destination types without modifying core factory code.
    """

    def __init__(self):
        self._strategies = {}
        self._register_default_strategies()

    def _register_default_strategies(self):
        """Register built-in destination strategies."""
        self.register_strategy("internal", self._handle_internal_destination)
        self.register_strategy("spotify", self._handle_spotify_destination)
        self.register_strategy(
            "update_spotify",
            self._handle_update_spotify_destination,
        )

    def register_strategy(self, destination_type: str, handler: Callable):
        """Register a new destination strategy.

        Args:
            destination_type: Unique identifier for the destination type
            handler: Async function handling the destination operation
        """
        self._strategies[destination_type] = handler

    async def handle_destination(
        self,
        destination_type: str,
        context: dict,
        config: dict,
    ) -> dict:
        """Process a destination based on registered strategies.

        Args:
            destination_type: Type of destination to handle
            context: Workflow execution context
            config: Node configuration params

        Returns:
            Operation result dictionary with tracklist and metadata

        Raises:
            ValueError: If destination_type has no registered strategy
        """
        if destination_type not in self._strategies:
            raise ValueError(f"Unsupported destination type: {destination_type}")

        ctx = Context(context)

        # Get the INPUT tracklist with all its metadata
        input_tracklist = ctx.extract_tracklist()

        logger = get_logger(__name__)
        # Log detailed metrics information at destination entry point
        logger.debug(
            "Destination received tracklist metrics",
            metrics_keys=list(input_tracklist.metadata.get("metrics", {}).keys()),
            spotify_popularity_count=len(
                input_tracklist.metadata.get("metrics", {}).get(
                    "spotify_popularity",
                    {},
                ),
            ),
        )

        # Invoke the appropriate strategy
        return await self._strategies[destination_type](
            input_tracklist,
            config,
            context,
        )

    async def _handle_internal_destination(
        self,
        tracklist: TrackList,
        config: dict,
        context: dict,  # noqa: ARG002
    ) -> dict:
        """Create a playlist in the internal database."""
        name = config.get("name", "Narada Playlist")
        description = config.get("description", "Created by Narada")

        # Common persistence function
        from narada.core.repositories import PlaylistRepository

        db_tracks, stats = await self._persist_tracks(tracklist)

        async with get_session(rollback=False) as session:
            playlist_repo = PlaylistRepository(session)

            playlist = Playlist(
                name=name,
                description=description,
                tracks=db_tracks,
            )

            playlist_id = await playlist_repo.save_playlist(playlist)

        # PRESERVE METADATA: Create new tracklist with db_tracks but KEEP the metadata
        result_tracklist = TrackList(
            tracks=db_tracks,
            metadata=tracklist.metadata,
        )

        logger = get_logger(__name__)
        logger.debug(
            "Result tracklist metrics after preservation",
            metrics_keys=result_tracklist.metadata.get("metrics", {}).keys(),
        )

        return {
            "playlist_id": playlist_id,
            "playlist_name": name,
            "track_count": len(db_tracks),
            "operation": "create_internal_playlist",
            "tracklist": result_tracklist,
            **stats,
        }

    async def _handle_spotify_destination(
        self,
        tracklist: TrackList,
        config: dict,
        context: dict,  # noqa: ARG002
    ) -> dict:
        """Create a new Spotify playlist."""
        from narada.integrations.spotify import SpotifyConnector

        name = config.get("name", "Narada Playlist")
        description = config.get("description", "Created by Narada")

        spotify = SpotifyConnector()
        spotify_id = await spotify.create_playlist(
            name,
            tracklist.tracks,
            description,
        )

        db_tracks, stats = await self._persist_tracks(tracklist)

        async with get_session(rollback=False) as session:
            playlist_repo = PlaylistRepository(session)

            playlist = Playlist(
                name=name,
                description=description,
                tracks=db_tracks,
                connector_track_ids={"spotify": spotify_id},
            )

            playlist_id = await playlist_repo.save_playlist(playlist)

        # PRESERVE METADATA: Create new tracklist with db_tracks but KEEP the metadata
        result_tracklist = TrackList(
            tracks=db_tracks,
            metadata=tracklist.metadata,
        )

        return {
            "playlist_id": playlist_id,
            "spotify_playlist_id": spotify_id,
            "playlist_name": name,
            "track_count": len(db_tracks),
            "operation": "create_spotify_playlist",
            "tracklist": result_tracklist,
            **stats,
        }

    async def _handle_update_spotify_destination(
        self,
        tracklist: TrackList,
        config: dict,
        context: dict,  # noqa: ARG002
    ) -> dict:
        """Update an existing Spotify playlist."""
        from narada.integrations.spotify import SpotifyConnector

        spotify_id = config.get("playlist_id")
        append = config.get("append", False)

        if not spotify_id:
            raise ValueError("Missing required playlist_id for update operation")

        db_tracks, stats = await self._persist_tracks(tracklist)

        async with get_session(rollback=False) as session:
            track_repo = TrackRepository(session)
            playlist_repo = PlaylistRepository(session)
            existing = await playlist_repo.get_playlist("spotify", spotify_id)

            if not existing:
                raise ValueError(f"Playlist with Spotify ID {spotify_id} not found")

            updated = existing.with_tracks(
                existing.tracks + db_tracks if append else db_tracks,
            )

            spotify = SpotifyConnector()
            await spotify.update_playlist(spotify_id, updated, replace=not append)

            await playlist_repo.update_playlist(
                str(existing.id),
                updated,
                track_repo,
            )

        # PRESERVE METADATA: Create new tracklist with db_tracks but KEEP the metadata
        result_tracklist = TrackList(
            tracks=db_tracks,
            metadata=tracklist.metadata,
        )

        return {
            "playlist_id": str(existing.id),
            "spotify_playlist_id": spotify_id,
            "track_count": len(updated.tracks),
            "original_count": len(existing.tracks),
            "operation": "update_spotify_playlist",
            "append_mode": append,
            "tracklist": result_tracklist,
            **stats,
        }

    async def _persist_tracks(self, tracklist: TrackList) -> tuple[list[Track], dict]:
        """Persist tracks to database and return stats.

        Args:
            tracklist: TrackList to persist

        Returns:
            Tuple of (persisted tracks list, stats dictionary)
        """
        stats = {"new_tracks": 0, "updated_tracks": 0}

        async with get_session(rollback=False) as session:
            track_repo = TrackRepository(session)
            db_tracks = []

            for track in tracklist.tracks:
                try:
                    original_id = track.id
                    saved_track = await track_repo.save_track(track)

                    if original_id != saved_track.id:
                        if original_id is None:
                            stats["new_tracks"] += 1
                        else:
                            stats["updated_tracks"] += 1

                    db_tracks.append(saved_track)
                except Exception as e:
                    logger = get_logger(__name__)
                    logger.error(f"Error persisting track {track.title}: {e}")
                    db_tracks.append(track)

            return db_tracks, stats


# Instantiate the handler - we use a singleton instance
_destination_handler = DestinationHandler()


# === ENRICHER FACTORY ===


def create_enricher_node(config: dict) -> NodeFn:
    # Load connectors once during factory creation
    connectors = discover_connectors()
    enricher_type = config.get("connector")

    if enricher_type not in connectors:
        raise ValueError(f"Unsupported connector: {enricher_type}")

    # Store configuration for this specific enricher
    enricher_config = connectors[enricher_type]

    async def node_impl(context: dict, node_config: dict) -> dict:
        ctx = Context(context)
        tracklist = ctx.extract_tracklist()

        # Create resolution engine
        engine = create_engine()

        # Initialize this enricher
        connector_instance = enricher_config["factory"](node_config)
        engine.register_connector(enricher_type, connector_instance)

        # Initialize dependencies
        for dep_name in enricher_config["dependencies"]:
            if dep_name in connectors:
                dep_config = connectors[dep_name]
                dep_instance = dep_config["factory"](node_config)
                engine.register_connector(dep_name, dep_instance)

        # Use enricher_type consistently
        async with get_session() as session:
            track_repo = TrackRepository(session)
            match_results = await batch_match_tracks(
                tracklist.tracks,
                enricher_type,  # Use the stored name consistently
                engine,
                track_repo,
            )
            # Extract and build metrics
            metrics = {}

            # Extract metrics from both tracks and match results
            for attr, extractor in enricher_config["extractors"].items():
                values = {}

                # Try to extract from tracks first
                for track in tracklist.tracks:
                    if track.id is not None:
                        try:
                            # Attempt extraction using our adaptive extractor
                            value = extractor(track)
                            if value is not None:  # Skip None values
                                values[str(track.id)] = value
                        except Exception as e:
                            logger.debug(f"Track extraction failed for {attr}: {e}")

                # Try to extract from match results for tracks that have matches
                for track in tracklist.tracks:
                    if track.id in match_results and match_results[track.id].success:
                        result = match_results[track.id]
                        try:
                            # Attempt extraction from the match result
                            value = extractor(result)
                            if value is not None:  # Skip None values
                                values[str(track.id)] = value
                        except Exception as e:
                            logger.debug(f"Result extraction failed for {attr}: {e}")

                # Store non-empty results in metrics
                if values:
                    metrics[attr] = values

            # Map connector-specific metrics to canonical names
            for connector_name, canonical_name in enricher_config["metrics"].items():
                if connector_name in metrics and canonical_name != connector_name:
                    metrics[canonical_name] = metrics[connector_name]
            # Add collected metrics to tracklist metadata
            enriched = tracklist
            if metrics:
                current = enriched.metadata.get("metrics", {})
                enriched = enriched.with_metadata("metrics", {**current, **metrics})

        return {
            "tracklist": enriched,
            "match_results": match_results,
            "operation": f"{connector_name}_enrichment",
        }

    return node_impl


# === NODE CREATION HELPERS ===
# These functions create specific node types using the factory system


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


def create_destination_node(destination_type: str) -> NodeFn:
    """Create a destination node of specified type."""

    async def node_impl(context: dict, config: dict) -> dict:
        return await _destination_handler.handle_destination(
            destination_type,
            context,
            config,
        )

    return node_impl


# === SOURCE NODE FACTORY ===
# Special case for source nodes which don't follow the transform pattern


async def spotify_playlist_source(_context: dict, config: dict) -> dict:
    """Source node for Spotify playlists with immediate track persistence.

    This node fetches a playlist from Spotify and immediately persists each track to the
    database, ensuring all tracks have database IDs before being processed by downstream nodes.
    This is essential for operations that depend on stable track identifiers, such as deduplication,
    sorting metrics, and cross-playlist filtering.

    Args:
        _context: Workflow execution context (unused in source nodes)
        config: Node configuration containing "playlist_id" for the Spotify playlist

    Returns:
        Dictionary with:
            - tracklist: TrackList with database-persisted tracks (with IDs)
            - source_id: Spotify playlist ID
            - source_name: Spotify playlist name
            - track_count: Number of tracks in the playlist
            - db_playlist_id: Internal database ID for the playlist
            - new_tracks: Count of newly added tracks
            - updated_tracks: Count of updated existing tracks

    Raises:
        ValueError: If playlist_id is missing from config
    """
    from narada.core.models import Playlist, TrackList
    from narada.integrations.spotify import SpotifyConnector

    if "playlist_id" not in config:
        raise ValueError("Missing required config parameter: playlist_id")

    playlist_id = config["playlist_id"]
    logger.info(f"Fetching Spotify playlist: {playlist_id}")

    # Fetch playlist from Spotify
    spotify = SpotifyConnector()
    spotify_playlist = await spotify.get_spotify_playlist(playlist_id)

    # Track persistence statistics
    stats = {"new_tracks": 0, "updated_tracks": 0}

    from narada.core.repositories import PlaylistRepository, TrackRepository
    from narada.data.database import get_session

    db_playlist_id = None
    db_tracks = []

    # CRITICAL: Persist tracks immediately to ensure database IDs
    async with get_session(rollback=False) as session:
        track_repo = TrackRepository(session)

        # Process each track, ensuring it has a database ID
        for track in spotify_playlist.tracks:
            # Save track to database and get updated version with ID
            updated_track = await track_repo.save_track(track)
            db_tracks.append(updated_track)

            # Update statistics
            if updated_track.id is not None and track.id is None:
                stats["new_tracks"] += 1
            else:
                stats["updated_tracks"] += 1

        logger.debug(
            f"Persisted {len(db_tracks)} tracks: {stats['new_tracks']} new, {stats['updated_tracks']} updated",
        )

        # Create internal playlist reference
        playlist_repo = PlaylistRepository(session)
        internal_playlist = Playlist(
            name=spotify_playlist.name,
            tracks=db_tracks,
            description=f"Source: Spotify playlist {playlist_id}",
            connector_track_ids={"spotify": playlist_id},
        )

        # Save playlist - this will handle track associations
        db_playlist_id = await playlist_repo.save_playlist(internal_playlist)

    # Create tracklist from persisted tracks (now with database IDs)
    tracklist = TrackList(tracks=db_tracks)
    tracklist = tracklist.with_metadata("source_playlist_name", spotify_playlist.name)
    tracklist = tracklist.with_metadata("spotify_playlist_id", playlist_id)
    tracklist = tracklist.with_metadata("db_playlist_id", db_playlist_id)

    # Log how many tracks have database IDs for debugging
    tracks_with_ids = sum(1 for t in db_tracks if t.id is not None)
    logger.info(
        f"Created tracklist with {len(db_tracks)} tracks, {tracks_with_ids} have database IDs",
    )

    return {
        "tracklist": tracklist,
        "source_id": playlist_id,
        "source_name": spotify_playlist.name,
        "track_count": len(tracklist.tracks),
        "db_playlist_id": db_playlist_id,
        **stats,
    }
