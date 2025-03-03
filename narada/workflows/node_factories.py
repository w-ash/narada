"""
Factory system for workflow nodes with unified patterns.

Provides a declarative, configuration-driven approach to node creation that
minimizes code surface area while maintaining maximum flexibility.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from narada.config import get_logger
from narada.core.models import Playlist, Track, TrackList
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

logger = get_logger(__name__)

# === TYPE DEFINITIONS ===
type NodeFn = Callable[[dict, dict], Awaitable[dict]]
type KeyFn = Callable[[Track], Any]
type PredicateFn = Callable[[Track], bool]


class Context:
    """Context extractor with path-based access."""

    def __init__(self, data: dict) -> None:
        self.data = data

    def get(self, path: str, default: Any = None) -> Any:
        """Get value from nested context using dot notation."""
        parts = path.split(".")
        current = self.data
        for part in parts:
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        return current

    def extract_tracklist(self) -> TrackList:
        """Extract tracklist from upstream node."""
        # Get the sole upstream task ID (assuming single input)
        if "upstream_task_id" in self.data:
            upstream_id = self.data["upstream_task_id"]
            if upstream_id in self.data and "tracklist" in self.data[upstream_id]:
                return self.data[upstream_id]["tracklist"]

        raise ValueError("Missing required tracklist from upstream node")

    def collect_tracklists(self, task_ids: list[str]) -> list[TrackList]:
        """Collect tracklists from multiple task results."""
        tracklists = []
        for task_id in task_ids:
            if task_id not in self.data:
                logger.warning(f"Task ID not found in context: {task_id}")
                continue

            task_result = self.data[task_id]
            if not isinstance(task_result, dict) or not isinstance(
                task_result.get("tracklist"),
                TrackList,
            ):
                logger.warning(
                    f"Missing or invalid tracklist in task result: {task_id}",
                )
                continue

            tracklists.append(task_result["tracklist"])

        if not tracklists:
            # This should raise an exception rather than just logging
            raise ValueError(f"No valid tracklists found in upstream tasks: {task_ids}")

        return tracklists


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
            lambda track: (
                ctx.get(f"match_results.{track.id}.user_play_count", 0)
                if track.id
                else 0
            ),
            cfg.get("reverse", True),
        ),
        "by_spotify_popularity": lambda _ctx, cfg: sort_by_attribute(
            lambda track: track.get_connector_attribute("spotify", "popularity", 0),
            cfg.get("reverse", True),
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
async def destination_factory(
    destination_type: str,
    context: dict,
    config: dict,
) -> dict:
    """Factory for destination nodes with persistence logic."""
    ctx = Context(context)
    tracklist = ctx.extract_tracklist()
    name = config.get("name", "Narada Playlist")
    description = config.get("description", "Created by Narada")

    # Common persistence function
    from narada.core.repositories import PlaylistRepository, TrackRepository
    from narada.data.database import get_session

    async def persist_tracks() -> tuple[list[Track], dict]:
        """Persist tracks and return stats."""
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
                    logger.error(f"Error persisting track {track.title}: {e}")
                    db_tracks.append(track)

            return db_tracks, stats

    # Handle different destination types
    match destination_type:
        case "internal":
            db_tracks, stats = await persist_tracks()

            async with get_session(rollback=False) as session:
                playlist_repo = PlaylistRepository(session)
                track_repo = TrackRepository(session)

                playlist = Playlist(
                    name=name,
                    description=description,
                    tracks=db_tracks,
                )

                playlist_id = await playlist_repo.save_playlist(playlist)

            return {
                "playlist_id": playlist_id,
                "playlist_name": name,
                "track_count": len(db_tracks),
                "operation": "create_internal_playlist",
                **stats,
            }

        case "spotify":
            from narada.integrations.spotify import SpotifyConnector

            spotify = SpotifyConnector()
            spotify_id = await spotify.create_playlist(
                name,
                tracklist.tracks,
                description,
            )

            db_tracks, stats = await persist_tracks()

            async with get_session(rollback=False) as session:
                playlist_repo = PlaylistRepository(session)
                track_repo = TrackRepository(session)

                playlist = Playlist(
                    name=name,
                    description=description,
                    tracks=db_tracks,
                    connector_track_ids={"spotify": spotify_id},
                )

                playlist_id = await playlist_repo.save_playlist(playlist)

            return {
                "playlist_id": playlist_id,
                "spotify_playlist_id": spotify_id,
                "playlist_name": name,
                "track_count": len(tracklist.tracks),
                "operation": "create_spotify_playlist",
                **stats,
            }

        case "update_spotify":
            spotify_id = config.get("playlist_id")
            append = config.get("append", False)

            if not spotify_id:
                raise ValueError("Missing required playlist_id for update operation")

            from narada.integrations.spotify import SpotifyConnector

            db_tracks, stats = await persist_tracks()

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

            return {
                "playlist_id": str(existing.id),
                "spotify_playlist_id": spotify_id,
                "track_count": len(updated.tracks),
                "original_count": len(existing.tracks),
                "operation": "update_spotify_playlist",
                "append_mode": append,
                **stats,
            }

        case _:
            raise ValueError(f"Unsupported destination type: {destination_type}")


# === ENRICHER FACTORY ===


async def lastfm_enricher(context: dict, config: dict) -> dict:
    """Enrich tracks with Last.fm metadata including play counts."""
    from narada.core.matcher import batch_match_tracks
    from narada.integrations.lastfm import LastFmConnector

    ctx = Context(context)
    tracklist = ctx.extract_tracklist()

    # Configuration parameters
    username = config.get("username")
    batch_size = config.get("batch_size", 50)
    concurrency = config.get("concurrency", 5)

    # Match tracks to Last.fm
    lastfm = LastFmConnector(username=username)
    match_results = await batch_match_tracks(
        tracklist.tracks,
        lastfm,
        username=username or lastfm.username,
        batch_size=batch_size,
        concurrency=concurrency,
    )

    successful_matches = sum(1 for r in match_results.values() if r.success)

    return {
        "tracklist": tracklist,
        "match_results": match_results,
        "match_success_rate": f"{successful_matches}/{len(tracklist.tracks)}",
        "operation": "lastfm_resolution",
    }


def create_enricher_node(enricher_type: str) -> NodeFn:
    """Create an enricher node of specified type."""
    enrichers = {
        "lastfm": lastfm_enricher,
    }

    if enricher_type not in enrichers:
        raise ValueError(f"Unknown enricher type: {enricher_type}")

    return enrichers[enricher_type]


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
        return await destination_factory(destination_type, context, config)

    return node_impl


# === SOURCE NODE FACTORY ===
# Special case for source nodes which don't follow the transform pattern


async def spotify_playlist_source(_context: dict, config: dict) -> dict:
    """Source node for Spotify playlists."""
    from narada.core.models import Playlist, TrackList
    from narada.integrations.spotify import SpotifyConnector

    if "playlist_id" not in config:
        raise ValueError("Missing required config parameter: playlist_id")

    playlist_id = config["playlist_id"]
    logger.info(f"Fetching Spotify playlist: {playlist_id}")

    # Fetch playlist
    spotify = SpotifyConnector()
    spotify_playlist = await spotify.get_spotify_playlist(playlist_id)

    # Persist tracks and create tracklist
    stats = {"new_tracks": 0, "updated_tracks": 0}

    from narada.core.repositories import PlaylistRepository, TrackRepository
    from narada.data.database import get_session

    db_playlist_id = None
    db_tracks = []

    async with get_session(rollback=False) as session:
        track_repo = TrackRepository(session)

        # Save tracks individually first to avoid bulk insert issues
        for track in spotify_playlist.tracks:
            try:
                saved_track = await track_repo.save_track(track)
                db_tracks.append(saved_track)

                if track.id is None:
                    stats["new_tracks"] += 1
                else:
                    stats["updated_tracks"] += 1
            except Exception as e:
                logger.error(f"Error saving track {track.title}: {e}")

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

    # Create tracklist from saved tracks
    tracklist = TrackList(tracks=db_tracks)
    tracklist = tracklist.with_metadata("source_playlist_name", spotify_playlist.name)
    tracklist = tracklist.with_metadata("spotify_playlist_id", playlist_id)
    tracklist = tracklist.with_metadata("db_playlist_id", db_playlist_id)

    return {
        "tracklist": tracklist,
        "source_id": playlist_id,
        "source_name": spotify_playlist.name,
        "track_count": len(tracklist.tracks),
        "db_playlist_id": db_playlist_id,
        **stats,
    }
