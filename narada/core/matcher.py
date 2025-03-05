"""
Entity resolution with a composable, connector-oriented architecture.

This module implements a flexible track matching system that can identify the same
track across different music services through a registry of resolution strategies.
"""

import asyncio
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
            if mapping_details and (
                datetime.now(UTC) - mapping_details.last_verified
                < timedelta(hours=ttl_hours)
            ):
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

    # Try each resolution path
    for path in config.get("resolution_paths", []):
        # Skip paths that require attributes track doesn't have
        if not _has_attributes_for_path(track, path):
            continue

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
    target: str,
    engine: ResolutionEngine,
    repo: TrackRepository | None = None,
    batch_size: int = 50,
    concurrency: int = 10,
    **kwargs,
) -> dict[int, MatchResult]:
    """Match multiple tracks to a target service with efficient batching."""
    if not tracks:
        return {}

    results: dict[int, MatchResult] = {}
    semaphore = asyncio.Semaphore(concurrency)

    async def process_track(track: Track) -> tuple[int | None, MatchResult]:
        """Process single track with concurrency control."""
        async with semaphore:
            try:
                result = await resolve_track(track, target, engine, repo, kwargs)
                return track.id, result
            except Exception as e:
                logger.exception(f"Error resolving track {track.id}: {e}")
                return track.id, MatchResult(track=track, success=False)

    # Process tracks in batches
    for i in range(0, len(tracks), batch_size):
        batch = tracks[i : i + batch_size]
        batch_results = await asyncio.gather(*[process_track(t) for t in batch])

        # Store results
        results.update({
            track_id: result
            for track_id, result in batch_results
            if track_id is not None
        })

        # Log progress
        success_count = sum(1 for _, r in batch_results if r.success)
        logger.debug(
            f"Batch {i // batch_size + 1}: {success_count}/{len(batch)} matched",
        )

    # Report stats
    success_count = sum(1 for r in results.values() if r.success)
    logger.info(
        f"Matching complete: {success_count}/{len(tracks)} tracks resolved to {target}",
    )

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
