"""MusicBrainz provider for track matching.

This provider handles communication with the MusicBrainz API and transforms
MusicBrainz track data into our domain MatchResult objects.
"""

from typing import Any

from src.application.utilities.simple_batching import process_in_batches
from src.domain.entities import Track
from src.domain.matching.types import MatchResult, MatchResultsById
from src.infrastructure.config import get_logger

logger = get_logger(__name__)


class MusicBrainzProvider:
    """MusicBrainz track matching provider."""

    def __init__(self, connector_instance: Any) -> None:
        """Initialize with MusicBrainz connector.

        Args:
            connector_instance: MusicBrainz service connector for API calls.
        """
        self.connector_instance = connector_instance

    @property
    def service_name(self) -> str:
        """Service identifier."""
        return "musicbrainz"

    async def find_potential_matches(
        self,
        tracks: list[Track],
        **additional_options: Any,
    ) -> MatchResultsById:
        """Find track matches in MusicBrainz using batch ISRC and search APIs.

        Prioritizes batch ISRC lookup for efficiency, then falls back to
        individual artist/title searches.

        Args:
            tracks: Tracks to match against MusicBrainz catalog.
            **additional_options: Additional options (unused).

        Returns:
            Track IDs mapped to MatchResult objects.
        """
        # Acknowledge additional options to satisfy linter
        _ = additional_options

        if not tracks:
            return {}

        with logger.contextualize(
            operation="match_musicbrainz", track_count=len(tracks)
        ):
            # Group tracks by matching method
            isrc_tracks = [t for t in tracks if t.isrc]
            other_tracks = [t for t in tracks if not t.isrc and t.artists and t.title]

            results = {}

            # Process ISRC tracks first (higher confidence)
            if isrc_tracks:
                logger.info(f"Processing {len(isrc_tracks)} tracks with ISRCs")

                # Extract ISRCs for batch lookup
                isrcs = [t.isrc for t in isrc_tracks if t.isrc is not None]

                # Use native batch lookup which is already optimized
                isrc_results = await self.connector_instance.batch_isrc_lookup(isrcs)

                # Map results back to tracks
                for track in isrc_tracks:
                    if track.id is None or track.isrc is None:
                        continue

                    if track.isrc in isrc_results:
                        mbid = isrc_results[track.isrc]
                        match_result = self._create_isrc_match_result(track, mbid)
                        if match_result:
                            results[track.id] = match_result

                logger.info(f"Found {len(isrc_results)} matches from ISRCs")

            # Process remaining tracks using artist/title search
            remaining_tracks = [t for t in other_tracks if t.id not in results]
            if remaining_tracks:
                logger.info(
                    f"Processing {len(remaining_tracks)} tracks with artist/title"
                )
                artist_title_results = await process_in_batches(
                    remaining_tracks,
                    self._process_artist_title_batch,
                    operation_name="match_musicbrainz_artist_title",
                    connector="musicbrainz",
                )
                results.update(artist_title_results)

            logger.info(f"Found {len(results)} matches from {len(tracks)} tracks")
            return results

    def _create_isrc_match_result(self, track: Track, mbid: str) -> MatchResult | None:
        """Create a MatchResult for an ISRC-based match.

        Args:
            track: Internal Track object
            mbid: MusicBrainz recording ID

        Returns:
            MatchResult or None if match creation fails
        """
        try:
            # Create minimal service data for ISRC matches
            service_data = {
                "title": track.title,
                "mbid": mbid,
                "isrc": track.isrc,
            }

            # Use domain layer to calculate confidence
            from src.domain.matching.algorithms import calculate_confidence

            # For ISRC matches, we use empty track_data since we trust the ISRC
            confidence, evidence = calculate_confidence(
                internal_track_data={},
                service_track_data={},
                match_method="isrc",
            )

            # Log successful match
            artist_name = track.artists[0].name if track.artists else "Unknown"

            logger.info(
                f"Matched: {track.title} by {artist_name} → MusicBrainz via ISRC ({confidence}%)",
                track_id=track.id,
                connector="musicbrainz",
                match_method="isrc",
                confidence=confidence,
            )

            return MatchResult(
                track=track.with_connector_track_id("musicbrainz", mbid),
                success=True,
                connector_id=mbid,
                confidence=confidence,
                match_method="isrc",
                service_data=service_data,
                evidence=evidence,
            )

        except Exception as e:
            logger.warning(
                f"Failed to create MusicBrainz ISRC match result: {e}",
                track_id=track.id,
            )
            return None

    async def _process_artist_title_batch(self, batch: list[Track]) -> MatchResultsById:
        """Process a batch of tracks using artist/title matching.

        Args:
            batch: List of Track objects with artist and title

        Returns:
            Dictionary mapping track IDs to MatchResult objects
        """
        batch_results = {}
        for track in batch:
            try:
                if not track.id or not track.artists or not track.title:
                    continue

                artist = track.artists[0].name if track.artists else ""
                recording = await self.connector_instance.search_recording(
                    artist, track.title
                )

                if recording and "id" in recording:
                    match_result = self._create_artist_title_match_result(
                        track=track,
                        recording=recording,
                        original_artist=artist,
                    )
                    if match_result:
                        batch_results[track.id] = match_result

            except Exception as e:
                logger.warning(f"Artist/title match failed: {e}", track_id=track.id)

        return batch_results

    def _create_artist_title_match_result(
        self, track: Track, recording: dict[str, Any], original_artist: str
    ) -> MatchResult | None:
        """Create a MatchResult from MusicBrainz recording data.

        Args:
            track: Internal Track object
            recording: MusicBrainz recording data
            original_artist: Original artist name used for searching

        Returns:
            MatchResult or None if match creation fails
        """
        try:
            mbid = recording["id"]

            # Extract service data
            service_data = {
                "title": recording.get("title", ""),
                "mbid": mbid,
            }

            # Add artists if available
            if "artist-credit" in recording:
                service_data["artists"] = [
                    credit["name"]
                    for credit in recording.get("artist-credit", [])
                    if isinstance(credit, dict) and "name" in credit
                ]

            # Use domain layer to calculate confidence
            from src.domain.matching.algorithms import calculate_confidence

            # Prepare track data for confidence calculation
            internal_track_data = {
                "title": track.title,
                "artists": [artist.name for artist in track.artists]
                if track.artists
                else [],
                "duration_ms": track.duration_ms,
            }

            track_data = {
                "title": recording.get("title", ""),
                "artist": original_artist,  # Use our original artist as proxy
            }

            confidence, evidence = calculate_confidence(
                internal_track_data=internal_track_data,
                service_track_data=track_data,
                match_method="artist_title",
            )

            # Log successful match
            artist_name = track.artists[0].name if track.artists else "Unknown"

            logger.info(
                f"Matched: {track.title} by {artist_name} → MusicBrainz via artist/title ({confidence}%)",
                track_id=track.id,
                connector="musicbrainz",
                match_method="artist_title",
                confidence=confidence,
            )

            return MatchResult(
                track=track.with_connector_track_id("musicbrainz", mbid),
                success=True,
                connector_id=mbid,
                confidence=confidence,
                match_method="artist_title",
                service_data=service_data,
                evidence=evidence,
            )

        except Exception as e:
            logger.warning(
                f"Failed to create MusicBrainz artist/title match result: {e}",
                track_id=track.id,
            )
            return None
