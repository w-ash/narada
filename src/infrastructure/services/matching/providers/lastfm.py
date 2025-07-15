"""LastFM provider for track matching.

This provider handles communication with the LastFM API and transforms
LastFM track data into our domain MatchResult objects.
"""

from typing import Any

from src.domain.entities import Track
from src.domain.matching.types import MatchResult, MatchResultsById
from src.infrastructure.config import get_logger

logger = get_logger(__name__)


class LastFMProvider:
    """LastFM track matching provider."""

    def __init__(self, connector_instance: Any) -> None:
        """Initialize with LastFM connector.

        Args:
            connector_instance: LastFM service connector for API calls.
        """
        self.connector_instance = connector_instance

    @property
    def service_name(self) -> str:
        """Service identifier."""
        return "lastfm"

    async def find_potential_matches(
        self,
        tracks: list[Track],
        **additional_options: Any,
    ) -> MatchResultsById:
        """Find track matches in LastFM.

        Args:
            tracks: Tracks to match against LastFM catalog.
            **additional_options: Additional options (unused).

        Returns:
            Track IDs mapped to MatchResult objects.
        """
        # Acknowledge additional options to satisfy linter
        _ = additional_options

        if not tracks:
            return {}

        with logger.contextualize(operation="match_lastfm", tracks_count=len(tracks)):
            logger.info(f"Matching {len(tracks)} tracks to LastFM")

            # Get batch track info from LastFM
            track_infos = await self.connector_instance.batch_get_track_info(
                tracks=tracks,
                lastfm_username=self.connector_instance.lastfm_username,
            )

            # Convert to match results
            results = {}
            for track_id, track_info in track_infos.items():
                if track_info and track_info.lastfm_url:
                    # Find the original track
                    track = next((t for t in tracks if t.id == track_id), None)
                    if not track:
                        continue

                    # Create match result
                    match_result = self._create_match_result(track, track_info)
                    if match_result:
                        results[track_id] = match_result

            logger.info(f"Found {len(results)} matches from {len(tracks)} tracks")
            return results

    def _create_match_result(self, track: Track, track_info: Any) -> MatchResult | None:
        """Create MatchResult from LastFM track data.

        Args:
            track: Internal Track object.
            track_info: LastFM track info response.

        Returns:
            MatchResult with confidence scoring, or None if creation fails.
        """
        try:
            # Determine match method
            match_method = (
                "mbid"
                if track.connector_track_ids.get("musicbrainz")
                else "artist_title"
            )

            # Extract service data
            service_data = {
                "title": track_info.lastfm_title,
                "artist": track_info.lastfm_artist_name,
                "artists": [track_info.lastfm_artist_name]
                if track_info.lastfm_artist_name
                else [],
                "duration_ms": track_info.lastfm_duration,
                # LastFM specific data
                "lastfm_user_playcount": track_info.lastfm_user_playcount,
                "lastfm_global_playcount": track_info.lastfm_global_playcount,
                "lastfm_listeners": track_info.lastfm_listeners,
                "lastfm_user_loved": track_info.lastfm_user_loved,
            }

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

            confidence, evidence = calculate_confidence(
                internal_track_data=internal_track_data,
                service_track_data=service_data,
                match_method=match_method,
            )

            # Log successful match
            artist_name = track.artists[0].name if track.artists else "Unknown"
            method_display = "MBID" if match_method == "mbid" else "artist/title"

            logger.info(
                f"Matched: {track.title} by {artist_name} → LastFM via {method_display} ({confidence}%)",
                track_id=track.id,
                connector="lastfm",
                match_method=match_method,
                confidence=confidence,
            )

            return MatchResult(
                track=track.with_connector_track_id("lastfm", track_info.lastfm_url),
                success=True,
                connector_id=track_info.lastfm_url,
                confidence=confidence,
                match_method=match_method,
                service_data=service_data,
                evidence=evidence,
            )

        except Exception as e:
            logger.warning(
                f"Failed to create LastFM match result: {e}",
                track_id=track.id,
            )
            return None
