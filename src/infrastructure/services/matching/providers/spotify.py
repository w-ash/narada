"""Spotify provider for track matching.

This provider handles communication with the Spotify API and transforms
Spotify track data into our domain MatchResult objects.
"""

from typing import Any

from src.application.utilities.simple_batching import process_in_batches
from src.domain.entities import Track
from src.domain.matching.types import MatchResult, MatchResultsById
from src.infrastructure.config import get_logger

logger = get_logger(__name__)


class SpotifyProvider:
    """Spotify track matching provider."""
    
    def __init__(self, connector_instance: Any) -> None:
        """Initialize with Spotify connector.
        
        Args:
            connector_instance: Spotify service connector for API calls.
        """
        self.connector_instance = connector_instance
        
    @property
    def service_name(self) -> str:
        """Service identifier."""
        return "spotify"
    
    async def find_potential_matches(
        self,
        tracks: list[Track],
        **additional_options: Any,
    ) -> MatchResultsById:
        """Find track matches in Spotify using ISRC and search APIs.
        
        Prioritizes ISRC matches for higher confidence, then falls back to
        artist/title search for remaining tracks.
        
        Args:
            tracks: Tracks to match against Spotify catalog.
            **additional_options: Additional options (unused).
            
        Returns:
            Track IDs mapped to MatchResult objects.
        """
        # Acknowledge additional options to satisfy linter
        _ = additional_options
        
        if not tracks:
            return {}

        with logger.contextualize(operation="match_spotify", track_count=len(tracks)):
            # Group tracks by matching method for processing efficiency
            isrc_tracks = [t for t in tracks if t.isrc]
            other_tracks = [t for t in tracks if not t.isrc and t.artists and t.title]

            results = {}

            # Process ISRC tracks first (higher confidence)
            if isrc_tracks:
                logger.info(f"Processing {len(isrc_tracks)} tracks with ISRCs")
                isrc_results = await process_in_batches(
                    isrc_tracks,
                    self._process_isrc_batch,
                    operation_name="match_spotify_isrc",
                    connector="spotify",
                )
                results.update(isrc_results)

            # Process remaining tracks using artist/title search
            remaining_tracks = [t for t in other_tracks if t.id not in results]
            if remaining_tracks:
                logger.info(f"Processing {len(remaining_tracks)} tracks with artist/title")
                artist_title_results = await process_in_batches(
                    remaining_tracks,
                    self._process_artist_title_batch,
                    operation_name="match_spotify_artist_title",
                    connector="spotify",
                )
                results.update(artist_title_results)

            logger.info(f"Found {len(results)} matches from {len(tracks)} tracks")
            return results

    async def _process_isrc_batch(self, batch: list[Track]) -> MatchResultsById:
        """Process tracks using ISRC lookup.
        
        Args:
            batch: Tracks with ISRC codes.
            
        Returns:
            Track IDs mapped to MatchResult objects.
        """
        batch_results = {}
        for track in batch:
            try:
                if not track.id or not track.isrc:
                    continue

                spotify_track = await self.connector_instance.search_by_isrc(track.isrc)
                if spotify_track and spotify_track.get("id"):
                    match_result = self._create_match_result(
                        track=track,
                        spotify_track=spotify_track,
                        match_method="isrc",
                    )
                    if match_result:
                        batch_results[track.id] = match_result
                        
            except Exception as e:
                logger.warning(f"ISRC match failed: {e}", track_id=track.id)

        return batch_results

    async def _process_artist_title_batch(self, batch: list[Track]) -> MatchResultsById:
        """Process tracks using artist/title search.
        
        Args:
            batch: Tracks with artist and title data.
            
        Returns:
            Track IDs mapped to MatchResult objects.
        """
        batch_results = {}
        for track in batch:
            try:
                if not track.id or not track.artists or not track.title:
                    continue

                artist = track.artists[0].name if track.artists else ""
                spotify_track = await self.connector_instance.search_track(
                    artist, track.title
                )

                if spotify_track and spotify_track.get("id"):
                    match_result = self._create_match_result(
                        track=track,
                        spotify_track=spotify_track,
                        match_method="artist_title",
                    )
                    if match_result:
                        batch_results[track.id] = match_result
                        
            except Exception as e:
                logger.warning(
                    f"Artist/title match failed: {e}", track_id=track.id
                )

        return batch_results

    def _create_match_result(
        self, track: Track, spotify_track: dict[str, Any], match_method: str
    ) -> MatchResult | None:
        """Create MatchResult from Spotify track data.
        
        Args:
            track: Internal Track object.
            spotify_track: Spotify API response.
            match_method: Match method used ("isrc" or "artist_title").
            
        Returns:
            MatchResult with confidence scoring, or None if creation fails.
        """
        try:
            spotify_id = spotify_track["id"]

            # Extract service data
            service_data = {
                "title": spotify_track.get("name"),
                "album": spotify_track.get("album", {}).get("name"),
                "artists": [
                    artist.get("name", "")
                    for artist in spotify_track.get("artists", [])
                ],
                "duration_ms": spotify_track.get("duration_ms"),
                "release_date": spotify_track.get("album", {}).get("release_date"),
                "popularity": spotify_track.get("popularity"),
                "isrc": spotify_track.get("external_ids", {}).get("isrc"),
            }

            # Use domain layer to calculate confidence
            from src.domain.matching.algorithms import calculate_confidence
            
            # Prepare track data for confidence calculation
            internal_track_data = {
                "title": track.title,
                "artists": [artist.name for artist in track.artists] if track.artists else [],
                "duration_ms": track.duration_ms,
            }
            
            confidence, evidence = calculate_confidence(
                internal_track_data=internal_track_data,
                service_track_data=service_data,
                match_method=match_method,
            )

            # Log successful match
            artist_name = track.artists[0].name if track.artists else "Unknown"
            method_display = "ISRC" if match_method == "isrc" else "artist/title"

            logger.info(
                f"Matched: {track.title} by {artist_name} → Spotify via {method_display} ({confidence}%)",
                track_id=track.id,
                connector="spotify",
                match_method=match_method,
                confidence=confidence,
            )

            return MatchResult(
                track=track.with_connector_track_id("spotify", spotify_id),
                success=True,
                connector_id=spotify_id,
                confidence=confidence,
                match_method=match_method,
                service_data=service_data,
                evidence=evidence,
            )
            
        except Exception as e:
            logger.warning(
                f"Failed to create Spotify match result: {e}",
                track_id=track.id,
            )
            return None