"""
Entity resolution with a composable, connector-oriented architecture.

This module implements a flexible track matching system that can identify the same
track across different music services through a registry of resolution strategies.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, TypedDict, cast

from attrs import define

from narada.config import get_logger
from narada.core.models import ConnectorTrackMapping, Track
from narada.core.repositories import TrackRepository
from narada.integrations.lastfm import LastFmConnector, LastFmPlayCount
from narada.integrations.musicbrainz import MusicBrainzConnector

logger = get_logger(__name__)


# Type definitions
class ResolutionResult(TypedDict):
    """Result of a resolution attempt."""

    success: bool
    confidence: int
    external_id: str
    metadata: dict[str, Any]
    method: str


# Update this type to use ResolutionResult explicitly
ResolutionStrategy = Callable[[Track, dict], Awaitable[ResolutionResult]]
ConnectorType = Literal["spotify", "lastfm", "musicbrainz"]


@define(frozen=True, slots=True)
class MatchResult:
    """Immutable result of track resolution across services."""

    track: Track
    play_count: LastFmPlayCount | None = None
    mapping: ConnectorTrackMapping | None = None
    success: bool = False

    @property
    def confidence(self) -> int:
        """Get match confidence score."""
        return self.mapping.confidence if self.mapping else 0

    @property
    def user_play_count(self) -> int:
        """Get user play count or 0 if unavailable."""
        return self.play_count.user_play_count if self.play_count else 0


# Connector registry with resolution preferences and configuration
CONNECTOR_REGISTRY = {
    "lastfm": {
        "resolution_paths": [
            ["mbid"],  # Direct MBID
            ["musicbrainz:mbid"],  # Via MusicBrainz
            ["isrc", "musicbrainz:mbid"],  # ISRC → MusicBrainz → MBID
            ["artist_title"],  # Fallback
        ],
        "ttl_hours": 168,  # 1 week freshness
        "min_confidence": 60,
    },
    "musicbrainz": {
        "resolution_paths": [
            ["mbid"],  # Direct MBID
            ["isrc"],  # ISRC lookup
            ["artist_title"],  # Fallback
        ],
        "ttl_hours": 720,  # 30 days freshness
        "min_confidence": 70,
    },
}

# Confidence scores for different resolution methods
CONFIDENCE_SCORES = {
    "direct": 100,  # Original source track
    "mbid": 95,  # Native MusicBrainz ID
    "musicbrainz:mbid": 90,  # Via MusicBrainz
    "isrc": 85,  # ISRC-based lookup
    "artist_title": 65,  # Artist/title search (least confident)
}


class ResolutionEngine:
    """Orchestrates track resolution using pluggable strategies."""

    def __init__(self):
        """Initialize the resolution engine."""
        self.resolvers: dict[str, ResolutionStrategy] = {}
        self.connectors: dict[str, object] = {}

    def register_resolver(self, method: str, resolver: ResolutionStrategy) -> None:
        """Register a resolver for a specific method."""
        self.resolvers[method] = resolver

    def register_connector(self, name: str, connector: object) -> None:
        """Register a connector instance."""
        self.connectors[name] = connector

    def get_connector(self, name: str) -> object | None:
        """Get a registered connector by name."""
        return self.connectors.get(name)

    async def resolve(
        self,
        track: Track,
        path: list[str],
        context: dict,
    ) -> ResolutionResult:
        """Resolve a track using a specific resolution path."""
        if not path:
            return cast(
                "ResolutionResult",
                {
                    "success": False,
                    "confidence": 0,
                    "external_id": "",
                    "metadata": {},
                    "method": "",
                },
            )

        # Parse the first step in the path
        step = path[0]
        method = step
        target_connector = None

        # Check if step includes a connector ("connector:method")
        if ":" in step:
            connector_name, method = step.split(":", 1)
            target_connector = self.connectors.get(connector_name)
            if not target_connector:
                return cast(
                    "ResolutionResult",
                    {
                        "success": False,
                        "confidence": 0,
                        "external_id": "",
                        "metadata": {"error": f"connector_{connector_name}_not_found"},
                        "method": method,
                    },
                )

        # Get resolver for this method
        resolver = self.resolvers.get(method)
        if not resolver:
            return cast(
                "ResolutionResult",
                {
                    "success": False,
                    "confidence": 0,
                    "external_id": "",
                    "metadata": {"error": "resolver_not_found"},
                    "method": method,
                },
            )

        # Execute the resolver
        try:
            result = cast(
                "ResolutionResult",
                await resolver(
                    track,
                    {
                        **context,
                        "method": method,
                        "connector": target_connector,
                    },
                ),
            )

            # If successful and more steps in path, continue resolution
            if result["success"] and len(path) > 1:
                # Update track with this step's result
                updated_track = self._update_track_with_result(
                    track,
                    result,
                    method,
                    step,
                )

                # Continue resolution with updated track and remaining path
                return await self.resolve(updated_track, path[1:], context)

            return result
        except Exception as e:
            logger.exception(f"Resolution error in {method}: {e}")
            return cast(
                "ResolutionResult",
                {
                    "success": False,
                    "confidence": 0,
                    "external_id": "",
                    "metadata": {"error": str(e)},
                    "method": method,
                },
            )

    def _update_track_with_result(
        self,
        track: Track,
        result: ResolutionResult,
        method: str,
        step: str,
    ) -> Track:
        """Update track with intermediate resolution results."""
        if not result["success"] or not result["external_id"]:
            return track

        if method == "mbid":
            return track.with_connector_track_id("musicbrainz", result["external_id"])
        elif ":" in step:
            connector_name = step.split(":", 1)[0]
            return track.with_connector_track_id(connector_name, result["external_id"])

        return track


# Resolver implementations
async def mbid_resolver(track: Track, context: dict) -> ResolutionResult:
    """Resolve using MusicBrainz ID."""
    mbid = track.connector_track_ids.get("musicbrainz")
    if not mbid:
        return {
            "success": False,
            "confidence": 0,
            "external_id": "",
            "metadata": {},
            "method": "mbid",
        }

    target = context.get("target")

    # Resolve to Last.fm
    if target == "lastfm":
        lastfm = context.get("connector") or context.get("lastfm")
        if not lastfm:
            return {
                "success": False,
                "confidence": 0,
                "external_id": "",
                "metadata": {"error": "lastfm_missing"},
                "method": "mbid",
            }

        play_count = await lastfm.get_mbid_play_count(mbid, context.get("username"))
        if play_count and play_count.track_url:
            return {
                "success": True,
                "confidence": CONFIDENCE_SCORES["mbid"],
                "external_id": play_count.track_url,
                "metadata": {
                    "user_play_count": play_count.user_play_count,
                    "global_play_count": play_count.global_play_count,
                },
                "method": "mbid",
            }

    return {
        "success": False,
        "confidence": 0,
        "external_id": "",
        "metadata": {},
        "method": "mbid",
    }


async def isrc_resolver(track: Track, context: dict) -> ResolutionResult:
    """Resolve using ISRC."""
    isrc = track.isrc
    if not isrc:
        return {
            "success": False,
            "confidence": 0,
            "external_id": "",
            "metadata": {},
            "method": "isrc",
        }

    target = context.get("target")

    # Resolve to MusicBrainz
    if target == "musicbrainz" or context.get("connector"):
        musicbrainz = context.get("connector") or context.get("musicbrainz")
        if not musicbrainz:
            return {
                "success": False,
                "confidence": 0,
                "external_id": "",
                "metadata": {"error": "musicbrainz_missing"},
                "method": "isrc",
            }

        recording = await musicbrainz.get_recording_by_isrc(isrc)
        if recording and "id" in recording:
            return {
                "success": True,
                "confidence": CONFIDENCE_SCORES["isrc"],
                "external_id": recording["id"],
                "metadata": {"title": recording.get("title")},
                "method": "isrc",
            }

    return {
        "success": False,
        "confidence": 0,
        "external_id": "",
        "metadata": {},
        "method": "isrc",
    }


async def artist_title_resolver(track: Track, context: dict) -> ResolutionResult:
    """Resolve using artist and title search."""
    if not track.title or not track.artists:
        return {
            "success": False,
            "confidence": 0,
            "external_id": "",
            "metadata": {},
            "method": "artist_title",
        }

    artist = track.artists[0].name if track.artists else ""
    target = context.get("target")

    # Resolve to Last.fm
    if target == "lastfm":
        lastfm = context.get("connector") or context.get("lastfm")
        if not lastfm:
            return {
                "success": False,
                "confidence": 0,
                "external_id": "",
                "metadata": {"error": "lastfm_missing"},
                "method": "artist_title",
            }

        play_count = await lastfm.get_track_play_count(
            artist,
            track.title,
            context.get("username"),
        )
        if play_count and play_count.track_url:
            return {
                "success": True,
                "confidence": CONFIDENCE_SCORES["artist_title"],
                "external_id": play_count.track_url,
                "metadata": {
                    "user_play_count": play_count.user_play_count,
                    "global_play_count": play_count.global_play_count,
                },
                "method": "artist_title",
            }

    # Resolve to MusicBrainz
    elif target == "musicbrainz":
        musicbrainz = context.get("connector") or context.get("musicbrainz")
        if not musicbrainz:
            return {
                "success": False,
                "confidence": 0,
                "external_id": "",
                "metadata": {"error": "musicbrainz_missing"},
                "method": "artist_title",
            }

        recording = await musicbrainz.search_recording(artist, track.title)
        if recording and "id" in recording:
            return {
                "success": True,
                "confidence": CONFIDENCE_SCORES["artist_title"],
                "external_id": recording["id"],
                "metadata": {"title": recording.get("title")},
                "method": "artist_title",
            }

    return {
        "success": False,
        "confidence": 0,
        "external_id": "",
        "metadata": {},
        "method": "artist_title",
    }


async def resolve_track(
    track: Track,
    target: str,
    engine: ResolutionEngine,
    repo: TrackRepository | None = None,
    context: dict | None = None,
) -> MatchResult:
    """Resolve a track to a target service using the resolution engine."""
    context = context or {}

    # Check registry configuration
    if target not in CONNECTOR_REGISTRY:
        return MatchResult(track=track, success=False)

    config = CONNECTOR_REGISTRY[target]
    ttl_hours = config.get("ttl_hours", 168)  # Default 1 week

    # Check for existing fresh mapping
    if repo and track.id is not None:
        # Get track mappings
        mappings = await repo.get_connector_mappings([track.id], target)

        if mappings and track.id in mappings and target in mappings[track.id]:
            connector_id = mappings[track.id][target]

            # Get mapping details to check freshness
            mapping_details = await repo.get_track_mapping_details(track.id, target)

            # Check if mapping is fresh
            if mapping_details:
                # Handle timezone-naive last_verified by making it timezone-aware
                last_verified = mapping_details.last_verified
                if last_verified and last_verified.tzinfo is None:
                    # Treat naive datetime as UTC
                    last_verified = last_verified.replace(tzinfo=UTC)

                # Now compare with timezone-aware datetimes
                if datetime.now(UTC) - last_verified < timedelta(hours=ttl_hours):
                    mapping = ConnectorTrackMapping(
                        connector_name=target,
                        connector_track_id=connector_id,
                        match_method=mapping_details.match_method,
                        confidence=mapping_details.confidence,
                        metadata=mapping_details.connector_metadata,
                    )

                    # For Last.fm, include play count
                    play_count = None
                    if target == "lastfm" and mapping_details.connector_metadata:
                        play_count = LastFmPlayCount(
                            user_play_count=mapping_details.connector_metadata.get(
                                "user_play_count",
                                0,
                            ),
                            global_play_count=mapping_details.connector_metadata.get(
                                "global_play_count",
                                0,
                            ),
                            track_url=connector_id,
                        )

                    return MatchResult(
                        track=track.with_connector_track_id(target, connector_id),
                        mapping=mapping,
                        play_count=play_count,
                        success=True,
                    )

    # Try each resolution path with context
    for path in config.get("resolution_paths", []):
        # Use structured logging
        logger.debug("Attempting resolution path", path=path)

        # Check attributes with more detailed log info
        if not _has_attributes_for_path(track, path):
            missing = []
            for step in path:
                method = step.split(":", 1)[1] if ":" in step else step
                if method == "mbid" and "musicbrainz" not in track.connector_track_ids:
                    missing.append("mbid")
                elif method == "isrc" and not track.isrc:
                    missing.append("isrc")
                elif method == "artist_title" and (
                    not track.title or not track.artists
                ):
                    missing.append("artist_title")

            logger.debug(
                "Skipping resolution path",
                path=path,
                missing_attributes=missing,
            )
            continue

        # Log available engine components
        logger.debug(
            "Attempting resolution",
            path=path,
            available_connectors=list(engine.connectors.keys()),
            available_resolvers=list(engine.resolvers.keys()),
        )

        # Attempt resolution
        result = await engine.resolve(track, path, context)

        if result["success"] and result["confidence"] >= config.get(
            "min_confidence",
            0,
        ):
            # Create mapping
            mapping = ConnectorTrackMapping(
                connector_name=target,
                connector_track_id=result["external_id"],
                match_method="_".join(path),
                confidence=result["confidence"],
                metadata=result["metadata"],
            )

            # For Last.fm, create play count
            play_count = None
            if target == "lastfm" and "user_play_count" in result["metadata"]:
                play_count = LastFmPlayCount(
                    user_play_count=result["metadata"].get("user_play_count", 0),
                    global_play_count=result["metadata"].get("global_play_count", 0),
                    track_url=result["external_id"],
                )

            # Save mapping if repository is available
            updated_track = track.with_connector_track_id(target, result["external_id"])

            if repo and track.id is not None:
                # Save the new mapping
                await repo.save_connector_mappings([
                    (
                        track.id,
                        target,
                        result["external_id"],
                        result["confidence"],
                        "_".join(path),
                        result["metadata"],
                    ),
                ])

            return MatchResult(
                track=updated_track,
                mapping=mapping,
                play_count=play_count,
                success=True,
            )

    return MatchResult(track=track, success=False)


def _has_attributes_for_path(track: Track, path: list[str]) -> bool:
    """Check if track has necessary attributes for a resolution path."""
    for step in path:
        method = step.split(":", 1)[1] if ":" in step else step

        match method:
            case "mbid" if "musicbrainz" not in track.connector_track_ids:
                return False
            case "isrc" if not track.isrc:
                return False
            case "artist_title" if not track.title or not track.artists:
                return False

    return True


async def batch_match_tracks(
    tracks: list[Track],
    connector_type: ConnectorType,
    engine: ResolutionEngine,
    track_repo: TrackRepository,
) -> dict[int, MatchResult]:
    """Match a batch of tracks to the specified connector."""
    results: dict[int, MatchResult] = {}

    # Use structured logging by passing keyword arguments instead of f-strings
    logger.debug(
        "Starting batch match",
        connector=connector_type,
        track_count=len(tracks),
    )

    # Get connector configuration
    connector_config = CONNECTOR_REGISTRY.get(connector_type)
    if not connector_config:
        # Use log level appropriately with structured data
        logger.error("Missing connector configuration", connector=connector_type)
        return results

    # Log structured data rather than stringifying
    logger.debug("Using connector configuration", config=connector_config)

    # Use contextualize for all logs within the batch operation
    with logger.contextualize(operation="batch_match", connector=connector_type):
        # Match each track
        for i, track in enumerate(tracks):
            track_info = {
                "index": i,
                "total": len(tracks),
                "title": track.title,
                "artists": [a.name for a in track.artists],
                "track_id": track.id,
            }

            if i < 5 or i % 50 == 0:  # Log first few and every 50th track
                logger.debug("Processing track", **track_info)

            # More efficient context handling with a sub-block
            with logger.contextualize(track_id=track.id, track_title=track.title):
                # Check if we already have a match in the database
                db_match = None
                if track.id is not None:
                    try:
                        db_match = await track_repo.get_track_mapping_details(
                            track.id,
                            connector_type,
                        )
                        if db_match:
                            logger.debug(
                                "Found existing database mapping",
                                connector_id=db_match.connector_id,
                            )
                        else:
                            logger.debug("No existing database mapping")
                    except Exception:
                        # Exception already captures stack trace
                        logger.exception("Failed to retrieve mapping")

                # ... rest of the function with structured logging
        result = None
        try:
            if db_match:
                # Use existing database match
                connector_id = db_match.connector_id
                logger.debug(f"Using existing connector ID: {connector_id}")

                # Create base mapping object
                mapping = ConnectorTrackMapping(
                    connector_name=connector_type,
                    connector_track_id=connector_id,
                    match_method=db_match.match_method or "database",
                    confidence=db_match.confidence or 100,
                    metadata=db_match.connector_metadata or {},
                )

                # Set track with connector ID
                updated_track = track.with_connector_track_id(
                    connector_type,
                    connector_id,
                )

                # Fetch additional information based on connector type
                play_count = None
                if connector_type == "lastfm":
                    # For Last.fm, we need to fetch play count information
                    logger.debug("Fetching Last.fm play count data")
                    connector = engine.get_connector(connector_type)
                    if connector and isinstance(connector, LastFmConnector):
                        try:
                            play_count = await connector.get_mbid_play_count(
                                connector_id,
                                None,
                            )
                            logger.debug(f"Retrieved play count: {play_count}")
                        except Exception as e:
                            logger.exception(f"Error fetching play count: {e}")

                result = MatchResult(
                    track=updated_track,
                    mapping=mapping,
                    play_count=play_count,
                    success=True,
                )
            else:
                # No database match, resolve using engine
                logger.debug("No DB match, resolving track using engine")

                # Log available connectors in the engine to check if they're properly registered
                logger.debug(
                    f"Available engine connectors: {list(engine.connectors.keys())}",
                )

                # Log track attributes that might be needed for resolution
                logger.debug("Track attributes for resolution:")
                logger.debug(f"  ISRC: {track.isrc}")
                logger.debug(
                    f"  MusicBrainz ID: {track.connector_track_ids.get('musicbrainz')}",
                )
                logger.debug(f"  Title: {track.title}")
                logger.debug(f"  Artists: {[a.name for a in track.artists]}")

                # Use the higher-level track resolution function
                result = await resolve_track(
                    track,
                    connector_type,
                    engine,
                    track_repo,
                    {"target": connector_type},
                )

                # Log resolution results
                if result.success and result.mapping:
                    logger.debug(
                        f"Engine resolution success: ID {result.mapping.connector_track_id}, "
                        f"confidence {result.mapping.confidence}",
                    )
                else:
                    # Improved error message with more context
                    logger.debug(
                        f"Engine resolution failed for '{track.title}'. Possible causes: "
                        f"Missing connectors, insufficient track metadata, or no matching resolution paths",
                    )

        except Exception as e:
            logger.exception(f"Error during track matching: {e}")
            result = MatchResult(
                track=track,
                success=False,
            )

        if track.id is not None and result is not None:
            results[track.id] = result

    # Log summary statistics
    success_count = sum(1 for r in results.values() if r.success)
    play_count_present = sum(
        1 for r in results.values() if r.success and r.play_count is not None
    )

    logger.debug("=== MATCHER DEBUG: Completed batch match ===")
    logger.debug(f"Results summary: {success_count}/{len(results)} successful matches")
    logger.debug(f"Play count data available: {play_count_present}/{len(results)}")

    return results


def create_engine(
    lastfm: LastFmConnector | None = None,
    musicbrainz: MusicBrainzConnector | None = None,
) -> ResolutionEngine:
    """Create and configure a resolution engine."""
    engine = ResolutionEngine()

    # Register resolvers
    engine.register_resolver("mbid", mbid_resolver)
    engine.register_resolver("isrc", isrc_resolver)
    engine.register_resolver("artist_title", artist_title_resolver)

    # Register connectors
    if lastfm:
        engine.register_connector("lastfm", lastfm)
    if musicbrainz:
        engine.register_connector("musicbrainz", musicbrainz)

    return engine
