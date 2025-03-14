"""
Track matching system for cross-service music identification.

This module provides a simple, efficient API for matching tracks across
different music services with batching and proper logging.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from narada.config import get_logger
from narada.core.models import Track, TrackList
from narada.database.db_connection import get_session
from narada.integrations.lastfm import LastFmConnector
from narada.integrations.musicbrainz import MusicBrainzConnector
from narada.integrations.spotify import SpotifyConnector
from narada.repositories.track import TrackRepository

logger = get_logger(__name__)


@dataclass(frozen=True)
class MatchResult:
    """Result of attempting to match a track to an external service."""

    track: Track
    success: bool
    connector_id: str = ""  # ID in the target system
    confidence: int = 0
    match_method: str = ""  # "direct", "mbid", "isrc", "artist_title"
    metadata: dict = field(default_factory=dict)


async def batch_match_tracks(
    track_list: TrackList,
    connector: str,
    connector_instance: Any,
    batch_size: int = 50,
    concurrency_limit: int = 5,
) -> dict[int, MatchResult]:
    """
    Match a list of tracks against a specified connector with efficient batching.

    Args:
        track_list: List of tracks to match
        connector: Connector name ("spotify", "lastfm", "musicbrainz")
        connector_instance: Instance of the connector
        batch_size: Number of tracks per batch
        concurrency_limit: Maximum number of concurrent operations

    Returns:
        Dictionary mapping track IDs to match results
    """
    if not track_list.tracks:
        return {}

    # Filter tracks that have valid IDs for database lookup
    valid_tracks = []
    for track in track_list.tracks:
        if track.id is not None:
            valid_tracks.append(track)
        else:
            logger.warning("Track without internal ID cannot be matched or persisted")

    if not valid_tracks:
        return {}

    # Get all track IDs for database lookup
    track_ids = [t.id for t in valid_tracks]

    # Check for existing mappings in the database
    async with get_session() as session:
        track_repo = TrackRepository(session)

        # Get existing mappings from database for all tracks
        existing_mappings = await track_repo.get_connector_mappings(
            track_ids,
            connector,
        )

        # Process existing mappings
        db_mapped_tracks = {}
        tracks_to_match = []

        for track in valid_tracks:
            # Check if this track has a mapping in the database
            if (
                track.id in existing_mappings
                and connector in existing_mappings[track.id]
            ):
                connector_id = existing_mappings[track.id][connector]

                # Get detailed mapping information
                mapping_details = await track_repo.get_track_mapping_details(
                    track.id,
                    connector,
                )

                # Create a result with mapping data from the database
                db_mapped_tracks[track.id] = MatchResult(
                    track=track.with_connector_track_id(connector, connector_id),
                    success=True,
                    connector_id=connector_id,
                    confidence=mapping_details.confidence if mapping_details else 80,
                    match_method=mapping_details.match_method
                    if mapping_details
                    else "unknown",
                    metadata=mapping_details.connector_metadata
                    if mapping_details
                    else {},
                )
            else:
                # This track needs matching
                tracks_to_match.append(track)

    logger.info(
        f"Matching {len(tracks_to_match)} tracks to {connector}, "
        f"{len(db_mapped_tracks)} already in database",
    )

    # If no tracks need matching, return early
    if not tracks_to_match:
        return db_mapped_tracks

    # Process tracks in batches with concurrency limits
    semaphore = asyncio.Semaphore(concurrency_limit)
    new_matches = {}

    # Process in batches
    for i in range(0, len(tracks_to_match), batch_size):
        batch = tracks_to_match[i : i + batch_size]

        batch_tasks = [
            _process_track(track, connector, connector_instance, semaphore)
            for track in batch
        ]

        batch_results = await asyncio.gather(*batch_tasks)

        # Process results
        for result in batch_results:
            if result and result.track.id is not None and result.success:
                new_matches[result.track.id] = result

    # Save new matches to database
    if new_matches:
        async with get_session() as session:
            track_repo = TrackRepository(session)
            mappings_to_save = [
                (
                    result.track.id,
                    connector,
                    result.connector_id,
                    result.confidence,
                    result.match_method,
                    result.metadata,
                )
                for result in new_matches.values()
            ]

            await track_repo.save_connector_mappings(mappings_to_save)
            await session.commit()

    # Combine all results
    combined_results = {**db_mapped_tracks, **new_matches}

    logger.info(
        f"Matching complete: {len(combined_results)}/{len(track_list.tracks)} "
        f"tracks matched to {connector}",
    )

    return combined_results


async def _process_track(
    track: Track,
    connector: str,
    connector_instance: Any,
    semaphore: asyncio.Semaphore,
) -> MatchResult | None:
    """Process a single track with semaphore for concurrency control."""
    if track.id is None:
        return None

    async with semaphore:
        try:
            # Dispatch to appropriate connector matcher
            if connector == "spotify":
                return await _match_track_to_spotify(track, connector_instance)
            elif connector == "lastfm":
                return await _match_track_to_lastfm(track, connector_instance)
            elif connector == "musicbrainz":
                return await _match_track_to_musicbrainz(track, connector_instance)
            else:
                logger.warning(f"Unsupported connector: {connector}")
                return MatchResult(track=track, success=False)
        except Exception as e:
            logger.exception(f"Error matching track {track.id} to {connector}: {e}")
            return MatchResult(
                track=track,
                success=False,
                metadata={"error": str(e)},
            )


async def _match_track_to_spotify(
    track: Track,
    spotify: SpotifyConnector,
) -> MatchResult:
    """
    Match track to Spotify using the following resolution sequence:
    1. ISRC (if available)
    2. Artist + Title search
    """
    # Try ISRC first if available
    if track.isrc:
        try:
            spotify_track = await spotify.search_by_isrc(track.isrc)

            if spotify_track and spotify_track.get("id"):
                spotify_id = spotify_track["id"]
                logger.info(
                    f"Matched track {track.id} to Spotify by ISRC: {spotify_id}",
                )
                return MatchResult(
                    track=track.with_connector_track_id("spotify", spotify_id),
                    success=True,
                    connector_id=spotify_id,
                    confidence=90,
                    match_method="isrc",
                    metadata={"matched_at": datetime.now(tz=UTC).isoformat()},
                )
        except Exception as e:
            logger.warning(f"ISRC match failed for Spotify: {e}")

    # Fall back to artist + title search
    if track.artists and track.title:
        try:
            artist_name = track.artists[0].name
            spotify_track = await spotify.search_track(artist_name, track.title)

            if spotify_track and spotify_track.get("id"):
                spotify_id = spotify_track["id"]
                logger.info(
                    f"Matched track {track.id} to Spotify by artist/title: {spotify_id}",
                )
                return MatchResult(
                    track=track.with_connector_track_id("spotify", spotify_id),
                    success=True,
                    connector_id=spotify_id,
                    confidence=75,
                    match_method="artist_title",
                    metadata={"matched_at": datetime.now(tz=UTC).isoformat()},
                )
        except Exception as e:
            logger.warning(f"Artist/title match failed for Spotify: {e}")

    return MatchResult(track=track, success=False)


async def _match_track_to_lastfm(track: Track, lastfm: LastFmConnector) -> MatchResult:
    """
    Match track to LastFM using the following resolution sequence:
    1. MusicBrainz ID (if available)
    2. Artist + Title search
    """
    # Try MBID first if available
    mbid = track.connector_track_ids.get("musicbrainz")
    if mbid:
        try:
            play_count = await lastfm.get_mbid_play_count(mbid)
            if play_count and play_count.track_url:
                logger.info(
                    f"Matched track {track.id} to LastFM by MBID: {play_count.track_url}",
                )
                return MatchResult(
                    track=track.with_connector_track_id("lastfm", play_count.track_url),
                    success=True,
                    connector_id=play_count.track_url,
                    confidence=90,
                    match_method="mbid",
                    metadata={
                        "user_play_count": play_count.user_play_count,
                        "global_play_count": play_count.global_play_count,
                    },
                )
        except Exception as e:
            logger.warning(f"MBID match failed for LastFM: {e}")

    # Fall back to artist + title search
    if track.artists and track.title:
        try:
            artist_name = track.artists[0].name
            play_count = await lastfm.get_track_play_count(artist_name, track.title)

            if play_count and play_count.track_url:
                logger.info(
                    f"Matched track {track.id} to LastFM by artist/title: {play_count.track_url}",
                )
                return MatchResult(
                    track=track.with_connector_track_id("lastfm", play_count.track_url),
                    success=True,
                    connector_id=play_count.track_url,
                    confidence=75,
                    match_method="artist_title",
                    metadata={
                        "user_play_count": play_count.user_play_count,
                        "global_play_count": play_count.global_play_count,
                    },
                )
        except Exception as e:
            logger.warning(f"Artist/title match failed for LastFM: {e}")

    return MatchResult(track=track, success=False)


async def _match_track_to_musicbrainz(
    track: Track,
    musicbrainz: MusicBrainzConnector,
) -> MatchResult:
    """
    Match track to MusicBrainz using the following resolution sequence:
    1. ISRC (if available)
    2. Artist + Title search
    """
    # Try ISRC first if available
    if track.isrc:
        try:
            result = await musicbrainz.batch_isrc_lookup([track.isrc])
            if result and track.isrc in result and result[track.isrc]:
                mbid = result[track.isrc]
                logger.info(
                    f"Matched track {track.id} to MusicBrainz by ISRC: {mbid}",
                )
                return MatchResult(
                    track=track.with_connector_track_id("musicbrainz", mbid),
                    success=True,
                    connector_id=mbid,
                    confidence=90,
                    match_method="isrc",
                    metadata={"matched_at": datetime.now(tz=UTC).isoformat()},
                )
        except Exception as e:
            logger.warning(f"ISRC match failed for MusicBrainz: {e}")

    # Fall back to artist + title search
    if track.artists and track.title:
        try:
            artist_name = track.artists[0].name
            recording = await musicbrainz.search_recording(artist_name, track.title)

            if recording and "id" in recording:
                mbid = recording["id"]
                logger.info(
                    f"Matched track {track.id} to MusicBrainz by artist/title: {mbid}",
                )
                return MatchResult(
                    track=track.with_connector_track_id("musicbrainz", mbid),
                    success=True,
                    connector_id=mbid,
                    confidence=75,
                    match_method="artist_title",
                    metadata={
                        "title": recording.get("title"),
                        "matched_at": datetime.now(tz=UTC).isoformat(),
                    },
                )
        except Exception as e:
            logger.warning(f"Artist/title match failed for MusicBrainz: {e}")

    return MatchResult(track=track, success=False)
