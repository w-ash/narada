"""Entity resolution with database-first strategy and efficient batch processing."""

import asyncio
from typing import TypeVar

from attrs import define

from narada.config import get_logger
from narada.core.models import ConnectorTrackMapping, Track
from narada.core.repositories import TrackRepository
from narada.integrations.lastfm import LastFmConnector, LastFmPlayCount
from narada.integrations.musicbrainz import MusicBrainzConnector

# Get logger
logger = get_logger(__name__)

# Type aliases
T = TypeVar("T", bound=Track)

# Resolution configuration
RESOLUTION_CONFIG = {
    "confidence": {
        "mbid": 95,  # MusicBrainz ID matching (high confidence)
        "artist_title": 85,  # Direct artist+title matching
        "cached": 98,  # Database-sourced previous matches (highest confidence)
        "duration_missing": 5,  # Penalty for incomplete metadata
    },
    "matching_methods": {  # Renamed from "methods" to "matching_methods"
        "isrc_mbid": "mbid",  # ISRC→MBID path maps to mbid
        "direct": "artist_title",  # Direct lookup maps to artist_title
        "database": "cached",  # Database lookup maps to cached
    },
}


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


async def batch_match_tracks(
    tracks: list[Track],
    lastfm_connector: LastFmConnector,
    track_repo: TrackRepository | None = None,
    musicbrainz_connector: MusicBrainzConnector | None = None,
    username: str | None = None,
    max_age_hours: int = 24,
    batch_size: int = 50,
    concurrency: int = 10,
) -> dict[int, MatchResult]:
    """Match tracks with adaptive database-first or API-only strategy."""
    if not tracks:
        return {}

    results: dict[int, MatchResult] = {}
    tracks_to_resolve = list(tracks)

    # Phase 1: Database resolution (if enabled)
    if track_repo is not None:
        # Extract tracks with IDs for database lookup
        valid_tracks = [
            (i, t) for i, t in enumerate(tracks_to_resolve) if t.id is not None
        ]

        if valid_tracks:
            db_tracks = [t for _, t in valid_tracks]
            track_ids = [t.id for t in db_tracks if t.id is not None]

            # Get mappings and metrics in parallel
            mappings, metrics = await asyncio.gather(
                track_repo.get_connector_mappings(track_ids, "lastfm"),
                track_repo.get_track_metrics(
                    track_ids,
                    metric_type="user_play_count",
                    max_age_hours=max_age_hours,
                ),
            )

            # Process tracks with database matches
            resolved_indices = []
            for i, track in valid_tracks:
                track_id = track.id
                if track_id in mappings and "lastfm" in mappings[track_id]:
                    lastfm_url = mappings[track_id]["lastfm"]
                    play_count = metrics.get(track_id, 0)

                    # Create result from database
                    results[track_id] = MatchResult(
                        track=track.with_connector_track_id("lastfm", lastfm_url),
                        play_count=LastFmPlayCount(
                            user_play_count=play_count,
                            global_play_count=0,
                            track_url=lastfm_url,
                        ),
                        mapping=ConnectorTrackMapping(
                            connector_name="lastfm",
                            connector_track_id=lastfm_url,
                            match_method=RESOLUTION_CONFIG["matching_methods"][
                                "database"
                            ],  # Updated to use matching_methods
                            confidence=RESOLUTION_CONFIG["confidence"][
                                "cached"
                            ],  # Updated confidence key
                            metadata={"user_play_count": play_count},
                        ),
                        success=True,
                    )
                    resolved_indices.append(i)

            # Remove resolved tracks from to-resolve list
            for i in sorted(resolved_indices, reverse=True):
                tracks_to_resolve.pop(i)

            logger.info(
                f"Database resolution: {len(resolved_indices)}/{len(valid_tracks)} tracks matched",
            )

    # Phase 2: API resolution for remaining tracks
    if tracks_to_resolve:
        logger.info(f"API resolution: processing {len(tracks_to_resolve)} tracks")

        # Phase 2.1: Batch MBID resolution for tracks with ISRCs
        track_mbid_map = {}
        if musicbrainz_connector:
            # Collect tracks with ISRCs but without MBIDs
            tracks_with_isrc = {
                t.id: t.isrc
                for t in tracks_to_resolve
                if t.isrc
                and t.id is not None
                and "musicbrainz" not in t.connector_track_ids
            }

            if tracks_with_isrc:
                # Execute batch ISRC lookup
                logger.info(f"Batch resolving {len(tracks_with_isrc)} ISRCs to MBIDs")
                isrcs = list(tracks_with_isrc.values())
                try:
                    isrc_to_mbid = await musicbrainz_connector.batch_isrc_lookup(isrcs)

                    # Map back to track IDs
                    for track_id, isrc in tracks_with_isrc.items():
                        if isrc in isrc_to_mbid:
                            mbid = isrc_to_mbid[isrc]
                            track_mbid_map[track_id] = mbid
                            logger.debug(
                                "MBID resolution successful",
                                track_id=track_id,
                                isrc=isrc,
                                mbid=mbid,
                            )
                        else:
                            logger.debug(
                                "Failed to resolve MBID for track",
                                track_id=track_id,
                                isrc=isrc,
                            )

                    logger.info(
                        f"Resolved {len(track_mbid_map)}/{len(tracks_with_isrc)} tracks via ISRC→MBID",
                    )
                except Exception as e:
                    logger.warning(f"Batch MBID resolution error: {e}")

        # Create semaphore for Last.fm API concurrency control
        semaphore = asyncio.Semaphore(concurrency)

        async def resolve_track(track: Track) -> tuple[int | None, MatchResult]:
            """Resolve a single track via API."""
            async with semaphore:
                await asyncio.sleep(0.1)  # Rate limiting

                if not track.title or not track.artists:
                    logger.warning(
                        "Cannot match track without title/artists",
                        track_id=track.id,
                    )
                    return track.id, MatchResult(track=track, success=False)

                artist_name = track.artists[0].name if track.artists else ""
                play_count = None
                confidence = 0
                match_method = None
                updated_track = track

                # Apply pre-resolved MBID if available
                mbid = None
                if track.id in track_mbid_map:
                    mbid = track_mbid_map[track.id]
                    updated_track = updated_track.with_connector_track_id(
                        "musicbrainz",
                        mbid,
                    )
                    logger.debug(
                        "Using pre-resolved MBID",
                        track_id=track.id,
                        mbid=mbid,
                    )
                elif "musicbrainz" in track.connector_track_ids:
                    mbid = track.connector_track_ids["musicbrainz"]

                # Strategy 1: MBID → Last.fm
                if mbid:
                    play_count = await lastfm_connector.get_mbid_play_count(
                        mbid,
                        username,
                    )
                    if play_count and play_count.track_url:
                        confidence = RESOLUTION_CONFIG["confidence"]["mbid"]
                        match_method = RESOLUTION_CONFIG["matching_methods"][
                            "isrc_mbid"
                        ]
                        logger.debug(
                            "Matched via MBID",
                            track_id=track.id,
                            mbid=mbid,
                            play_count=play_count.user_play_count,
                        )

                # Strategy 2: Direct artist/title matching
                if not play_count or not play_count.track_url:
                    play_count = await lastfm_connector.get_track_play_count(
                        artist_name,
                        track.title,
                        username,
                    )
                    if play_count and play_count.track_url:
                        confidence = RESOLUTION_CONFIG["confidence"]["artist_title"]
                        match_method = RESOLUTION_CONFIG["matching_methods"]["direct"]
                        logger.debug(
                            "Matched via artist/title",
                            track_id=track.id,
                            artist=artist_name,
                            title=track.title,
                            play_count=play_count.user_play_count,
                        )

                # Handle no match found
                if not play_count or not play_count.track_url:
                    logger.debug(
                        "No Last.fm match found",
                        track_id=track.id,
                        title=track.title,
                    )
                    return track.id, MatchResult(track=updated_track, success=False)

                # Adjust confidence for missing metadata
                if updated_track.duration_ms is None:
                    confidence -= RESOLUTION_CONFIG["confidence"]["duration_missing"]

                # Create mapping and result
                mapping = ConnectorTrackMapping(
                    connector_name="lastfm",
                    connector_track_id=play_count.track_url,
                    match_method=match_method or "unknown",
                    confidence=max(0, min(100, confidence)),
                    metadata={"user_play_count": play_count.user_play_count},
                )

                updated_track = updated_track.with_connector_track_id(
                    "lastfm",
                    play_count.track_url,
                )
                return track.id, MatchResult(
                    track=updated_track,
                    play_count=play_count,
                    mapping=mapping,
                    success=True,
                )

        # Process remaining tracks in batches for Last.fm resolution
        for batch_start in range(0, len(tracks_to_resolve), batch_size):
            batch = tracks_to_resolve[batch_start : batch_start + batch_size]
            batch_tasks = [resolve_track(track) for track in batch]
            batch_results = await asyncio.gather(*batch_tasks)

            # Update results
            batch_results_dict = {
                tid: result for tid, result in batch_results if tid is not None
            }
            results.update(batch_results_dict)

            # Log batch progress
            success_count = sum(1 for r in batch_results_dict.values() if r.success)
            logger.debug(
                f"Batch {batch_start // batch_size + 1}: {success_count}/{len(batch)} matched",
            )

    # Phase 3: Persist API results to database
    if track_repo is not None:
        # Prepare mappings and metrics for API results
        mappings_to_save = []
        metrics_to_save = []

        for track_id, result in results.items():
            if (
                not result.success
                or not result.mapping
                or result.mapping.match_method
                == RESOLUTION_CONFIG["matching_methods"]["database"]
            ):
                continue

            # Add connector mappings
            mappings_to_save.append((
                track_id,
                result.mapping.connector_name,
                result.mapping.connector_track_id,
                result.mapping.confidence,
                result.mapping.match_method,
                result.mapping.metadata,
            ))

            # Add MusicBrainz mapping if available
            if result.track.connector_track_ids.get("musicbrainz"):
                mappings_to_save.append((
                    track_id,
                    "musicbrainz",
                    result.track.connector_track_ids["musicbrainz"],
                    90,  # High confidence for MBID mappings
                    "isrc",
                    {},
                ))

            # Add metrics if available
            if result.play_count:
                metrics_to_save.append((
                    track_id,
                    username or "default",
                    "play_count",
                    result.play_count.global_play_count,
                    result.play_count.user_play_count,
                ))

        # Persist in parallel
        if mappings_to_save or metrics_to_save:
            persist_tasks = []
            if mappings_to_save:
                persist_tasks.append(
                    track_repo.save_connector_mappings(mappings_to_save),
                )
            if metrics_to_save:
                persist_tasks.append(track_repo.save_track_metrics(metrics_to_save))

            # Await all tasks at once for parallel execution
            if persist_tasks:
                await asyncio.gather(*persist_tasks)

            logger.info(
                f"Persisted {len(mappings_to_save)} mappings and {len(metrics_to_save)} metrics",
            )

    # Report statistics
    db_matched = sum(
        1
        for r in results.values()
        if r.success
        and r.mapping
        and r.mapping.match_method
        == RESOLUTION_CONFIG["matching_methods"][
            "database"
        ]  # Updated to use matching_methods
    )
    api_matched = sum(
        1
        for r in results.values()
        if r.success
        and r.mapping
        and r.mapping.match_method != RESOLUTION_CONFIG["matching_methods"]["database"]
    )

    logger.info(
        "Match resolution complete",
        total=len(tracks),
        db_matched=db_matched,
        api_matched=api_matched,
        success_rate=f"{(db_matched + api_matched) / max(1, len(tracks)) * 100:.1f}%",
    )

    return results
