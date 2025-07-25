"""Spotify play resolution service using existing matcher infrastructure."""

from attrs import define

from src.config import get_logger
from src.domain.entities import Artist, ConnectorTrack, Track
from src.domain.matching.algorithms import calculate_confidence
from src.domain.matching.types import ConfidenceEvidence
from src.infrastructure.connectors.spotify import SpotifyConnector
from src.infrastructure.connectors.spotify_personal_data import SpotifyPlayRecord
from src.infrastructure.persistence.repositories.track import TrackRepositories

logger = get_logger(__name__)


def extract_spotify_track_id(spotify_uri: str) -> str:
    """Extract track ID from Spotify URI."""
    # spotify:track:01AbB47Hm60LTIStyzMb2g -> 01AbB47Hm60LTIStyzMb2g
    return spotify_uri.split(":")[-1]


@define(frozen=True, slots=True)
class PlayResolution:
    """Result of resolving a Spotify play record to internal track ID."""

    spotify_uri: str
    track_id: int | None
    resolution_method: (
        str  # "direct_id", "relinked_id", "search_match", "preserved_metadata"
    )
    confidence: int | None
    evidence: ConfidenceEvidence | None = None
    metadata: dict | None = None  # Original JSON metadata for unresolved tracks


@define(frozen=True, slots=True)
class SpotifyPlayResolver:
    """Resolves Spotify play records to internal track IDs using existing matcher."""

    spotify_connector: SpotifyConnector
    track_repos: TrackRepositories

    async def resolve_play_records(
        self, play_records: list[SpotifyPlayRecord]
    ) -> dict[str, int]:
        """
        Resolve Spotify play records to internal track IDs.

        Args:
            play_records: List of parsed Spotify play records

        Returns:
            Dictionary mapping Spotify URIs to internal track IDs
        """
        if not play_records:
            return {}

        # Extract unique Spotify track IDs
        unique_uris = list({record.track_uri for record in play_records})
        unique_track_ids = [extract_spotify_track_id(uri) for uri in unique_uris]

        logger.info(f"Resolving {len(unique_track_ids)} unique Spotify tracks")

        # Fetch track metadata from Spotify API
        spotify_tracks = await self.spotify_connector.get_tracks_by_ids(
            unique_track_ids
        )

        # Create Track objects from Spotify data for matching
        tracks_for_matching = []
        uri_to_track_map = {}

        for record in play_records:
            track_id = extract_spotify_track_id(record.track_uri)

            # Skip if we couldn't get track data from Spotify
            if track_id not in spotify_tracks:
                logger.warning(f"No Spotify data for track {track_id}")
                continue

            spotify_data = spotify_tracks[track_id]

            # Create Track object with Spotify metadata
            artists = [
                Artist(name=artist["name"])
                for artist in spotify_data.get("artists", [])
            ]

            track = Track(
                title=spotify_data["name"],
                artists=artists,
                album=spotify_data.get("album", {}).get("name"),
                duration_ms=spotify_data.get("duration_ms"),
                isrc=spotify_data.get("external_ids", {}).get("isrc"),
            ).with_connector_track_id("spotify", track_id)

            tracks_for_matching.append(track)
            uri_to_track_map[record.track_uri] = track

        if not tracks_for_matching:
            logger.warning("No valid tracks to match")
            return {}

        # Simple approach: check if we have existing connector tracks for these Spotify IDs
        # Spotify URI -> ConnectorTrack -> TrackMapping -> Track ID

        track_ids = [
            extract_spotify_track_id(record.track_uri) for record in play_records
        ]
        connections = [("spotify", track_id) for track_id in track_ids]

        # Find tracks that have existing mappings to these Spotify connector tracks
        existing_tracks = await self.track_repos.connector.find_tracks_by_connectors(
            connections
        )

        # Build mapping: Spotify URI -> internal track ID (if mapping exists)
        uri_to_id_map = {}
        for record in play_records:
            spotify_id = extract_spotify_track_id(record.track_uri)
            connection_key = ("spotify", spotify_id)

            if connection_key in existing_tracks:
                internal_track = existing_tracks[connection_key]
                uri_to_id_map[record.track_uri] = internal_track.id

        logger.info(
            f"Resolved {len(uri_to_id_map)} out of {len(play_records)} tracks from existing connector mappings"
        )
        return uri_to_id_map

    async def resolve_play_records_with_creation(
        self, play_records: list[SpotifyPlayRecord]
    ) -> dict[str, int]:
        """
        Resolve Spotify play records to internal track IDs, creating missing tracks.

        This enhanced version first checks for existing mappings, then creates any
        missing tracks using the existing infrastructure.

        Args:
            play_records: List of parsed Spotify play records

        Returns:
            Dictionary mapping Spotify URIs to internal track IDs
        """
        if not play_records:
            return {}

        # Step 1: Check existing mappings (use existing method)
        uri_to_id_map = await self.resolve_play_records(play_records)

        # Step 2: Identify unresolved tracks
        unresolved_records = [
            record for record in play_records if record.track_uri not in uri_to_id_map
        ]

        if not unresolved_records:
            logger.info("All tracks already resolved from existing mappings")
            return uri_to_id_map

        logger.info(
            f"Creating {len(unresolved_records)} missing tracks from Spotify API"
        )

        # Step 3: Get track data from Spotify API (already fetched in resolve_play_records)
        unique_track_ids = [
            extract_spotify_track_id(record.track_uri) for record in unresolved_records
        ]
        spotify_tracks = await self.spotify_connector.get_tracks_by_ids(
            unique_track_ids
        )

        # Step 4: Create ConnectorTrack objects from Spotify API data
        connector_tracks = []
        uri_to_connector_track = {}

        for record in unresolved_records:
            spotify_id = extract_spotify_track_id(record.track_uri)

            if spotify_id not in spotify_tracks:
                logger.warning(f"No Spotify data for track {spotify_id}")
                continue

            spotify_data = spotify_tracks[spotify_id]

            # Create ConnectorTrack from Spotify API data
            artists = [
                Artist(name=artist["name"])
                for artist in spotify_data.get("artists", [])
            ]

            connector_track = ConnectorTrack(
                connector_name="spotify",
                connector_track_id=spotify_id,
                title=spotify_data["name"],
                artists=artists,
                album=spotify_data.get("album", {}).get("name"),
                duration_ms=spotify_data.get("duration_ms"),
                isrc=spotify_data.get("external_ids", {}).get("isrc"),
                raw_metadata=spotify_data,
            )

            connector_tracks.append(connector_track)
            uri_to_connector_track[record.track_uri] = connector_track

        if not connector_tracks:
            logger.warning("No valid connector tracks to create")
            return uri_to_id_map

        # Step 5: Use existing infrastructure to create tracks
        logger.info(
            f"Creating {len(connector_tracks)} tracks using existing infrastructure"
        )
        created_tracks = await self.track_repos.connector.ingest_external_tracks_bulk(
            "spotify", connector_tracks
        )

        # Step 6: Map URIs to newly created track IDs
        for record, created_track in zip(
            unresolved_records, created_tracks, strict=True
        ):
            if created_track and created_track.id is not None:
                uri_to_id_map[record.track_uri] = created_track.id
                logger.debug(
                    f"Created track {created_track.id} for URI {record.track_uri}"
                )

        logger.info(
            f"Enhanced resolution: {len(uri_to_id_map)} total tracks resolved ({len(created_tracks)} newly created)"
        )
        return uri_to_id_map

    async def resolve_with_fallback(
        self, play_records: list[SpotifyPlayRecord]
    ) -> dict[str, PlayResolution]:
        """
        Comprehensive track resolution with 100% processing rate.

        Multi-stage resolution pipeline:
        1. Direct API lookup (leverages Spotify's native relinking)
        2. Search fallback for failed lookups
        3. Metadata preservation for unresolvable tracks

        Args:
            play_records: List of parsed Spotify play records

        Returns:
            Dictionary mapping Spotify URIs to PlayResolution results
        """
        if not play_records:
            return {}

        logger.info(
            f"Starting comprehensive resolution for {len(play_records)} play records"
        )

        # Extract unique URIs for processing
        unique_uris = list({record.track_uri for record in play_records})
        resolution_results = {}

        # Stage 1: Direct Spotify API lookup with relinking support
        logger.info(f"Stage 1: Direct API lookup for {len(unique_uris)} unique URIs")

        direct_results = await self._resolve_direct_with_relinking(play_records)
        resolution_results.update(direct_results)

        # Stage 2: Search fallback for failed direct lookups
        failed_uris = [uri for uri in unique_uris if uri not in resolution_results]
        if failed_uris:
            logger.info(f"Stage 2: Search fallback for {len(failed_uris)} failed URIs")

            # Get records for failed URIs
            failed_records = [r for r in play_records if r.track_uri in failed_uris]
            search_results = await self._resolve_via_search(failed_records)
            resolution_results.update(search_results)

        # Stage 3: Metadata preservation for remaining unresolved
        unresolved_uris = [uri for uri in unique_uris if uri not in resolution_results]
        if unresolved_uris:
            logger.info(
                f"Stage 3: Preserving metadata for {len(unresolved_uris)} unresolved URIs"
            )

            unresolved_records = [
                r for r in play_records if r.track_uri in unresolved_uris
            ]
            preserved_results = self._preserve_metadata(unresolved_records)
            resolution_results.update(preserved_results)

        # Statistics
        stats = self._calculate_resolution_stats(resolution_results)
        logger.info(f"Resolution complete: {stats}")

        return resolution_results

    async def _resolve_direct_with_relinking(
        self, play_records: list[SpotifyPlayRecord]
    ) -> dict[str, PlayResolution]:
        """Stage 1: Direct API lookup with error isolation and relinking detection."""

        unique_uris = list({record.track_uri for record in play_records})
        unique_track_ids = []
        uri_to_id_map = {}

        # Extract track IDs and validate format
        for uri in unique_uris:
            try:
                track_id = extract_spotify_track_id(uri)
                # Basic validation - Spotify track IDs are 22-character base62
                if len(track_id) == 22 and track_id.isalnum():
                    unique_track_ids.append(track_id)
                    uri_to_id_map[uri] = track_id
                else:
                    logger.warning(
                        f"Invalid track ID format: {track_id} from URI: {uri}"
                    )
            except Exception as e:
                logger.warning(f"Failed to extract track ID from URI {uri}: {e}")

        if not unique_track_ids:
            logger.warning("No valid track IDs to lookup")
            return {}

        resolution_results = {}

        try:
            # Batch API lookup
            spotify_tracks = await self.spotify_connector.get_tracks_by_ids(
                unique_track_ids
            )

            # Check for existing mappings to internal tracks
            connections = [("spotify", track_id) for track_id in unique_track_ids]
            existing_tracks = (
                await self.track_repos.connector.find_tracks_by_connectors(connections)
            )

            # Process results
            for uri in unique_uris:
                if uri not in uri_to_id_map:
                    continue  # Skip invalid URIs

                track_id = uri_to_id_map[uri]

                if track_id in spotify_tracks:
                    spotify_data = spotify_tracks[track_id]

                    # Check for relinking
                    linked_from = spotify_data.get("linked_from")
                    resolution_method = "relinked_id" if linked_from else "direct_id"

                    # Check for existing internal track mapping
                    connection_key = ("spotify", track_id)
                    internal_track_id = None

                    if connection_key in existing_tracks:
                        internal_track = existing_tracks[connection_key]
                        internal_track_id = internal_track.id
                    else:
                        # Create track from Spotify data if not exists
                        internal_track_id = await self._create_track_from_spotify_data(
                            track_id, spotify_data
                        )

                    resolution_results[uri] = PlayResolution(
                        spotify_uri=uri,
                        track_id=internal_track_id,
                        resolution_method=resolution_method,
                        confidence=100,  # Full confidence for Spotify API data
                        metadata={
                            "spotify_data": spotify_data,
                            "linked_from": linked_from,
                        },
                    )

        except Exception as e:
            logger.error(f"Direct API lookup failed: {e}")
            # Continue to search fallback for all tracks

        logger.info(
            f"Direct lookup resolved {len(resolution_results)}/{len(unique_uris)} URIs"
        )
        return resolution_results

    async def _resolve_via_search(
        self, failed_records: list[SpotifyPlayRecord]
    ) -> dict[str, PlayResolution]:
        """Stage 2: Search-based resolution with confidence scoring."""

        resolution_results = {}

        for record in failed_records:
            try:
                # Search using metadata from original JSON
                search_result = await self.spotify_connector.search_track(
                    record.artist_name, record.track_name
                )

                if search_result and search_result.get("id"):
                    # Create Track object for confidence calculation
                    from src.domain.entities import Artist, Track

                    original_track = Track(
                        title=record.track_name,
                        artists=[Artist(name=record.artist_name)],
                        album=record.album_name,
                    )

                    # Calculate confidence using existing system
                    search_track_data = {
                        "title": search_result.get("name"),
                        "artist": search_result.get("artists", [{}])[0].get("name", ""),
                        "album": search_result.get("album", {}).get("name"),
                        "duration_ms": search_result.get("duration_ms"),
                    }

                    # Convert track to dict format for domain function
                    internal_track_data = {
                        "title": original_track.title,
                        "artists": [artist.name for artist in original_track.artists]
                        if original_track.artists
                        else [],
                        "duration_ms": original_track.duration_ms,
                    }

                    confidence, evidence = calculate_confidence(
                        internal_track_data=internal_track_data,
                        service_track_data=search_track_data,
                        match_method="artist_title",
                    )

                    # Only accept high-confidence matches
                    if confidence >= 70:
                        # Check for existing internal track mapping
                        spotify_id = search_result["id"]
                        connection_key = ("spotify", spotify_id)
                        existing_tracks = (
                            await self.track_repos.connector.find_tracks_by_connectors([
                                connection_key
                            ])
                        )

                        internal_track_id = None
                        if connection_key in existing_tracks:
                            internal_track = existing_tracks[connection_key]
                            internal_track_id = internal_track.id
                        else:
                            # Create track from search result if not exists
                            internal_track_id = (
                                await self._create_track_from_spotify_data(
                                    spotify_id, search_result
                                )
                            )

                        resolution_results[record.track_uri] = PlayResolution(
                            spotify_uri=record.track_uri,
                            track_id=internal_track_id,
                            resolution_method="search_match",
                            confidence=confidence,
                            evidence=evidence,
                            metadata={
                                "search_result": search_result,
                                "original_metadata": {
                                    "track_name": record.track_name,
                                    "artist_name": record.artist_name,
                                    "album_name": record.album_name,
                                },
                            },
                        )

                        logger.debug(
                            f"Search match found for {record.track_uri}: confidence {confidence}%"
                        )
                    else:
                        logger.debug(
                            f"Low confidence search result for {record.track_uri}: {confidence}%"
                        )

            except Exception as e:
                logger.warning(f"Search failed for {record.track_uri}: {e}")

        logger.info(
            f"Search fallback resolved {len(resolution_results)}/{len(failed_records)} records"
        )
        return resolution_results

    def _preserve_metadata(
        self, unresolved_records: list[SpotifyPlayRecord]
    ) -> dict[str, PlayResolution]:
        """Stage 3: Preserve metadata for unresolvable tracks."""

        resolution_results = {}

        for record in unresolved_records:
            resolution_results[record.track_uri] = PlayResolution(
                spotify_uri=record.track_uri,
                track_id=None,  # No internal track ID
                resolution_method="preserved_metadata",
                confidence=None,
                metadata={
                    "track_name": record.track_name,
                    "artist_name": record.artist_name,
                    "album_name": record.album_name,
                    "original_spotify_uri": record.track_uri,
                    "preservable": True,  # Flag for future re-resolution
                },
            )

        logger.info(
            f"Preserved metadata for {len(resolution_results)} unresolved records"
        )
        return resolution_results

    def _calculate_resolution_stats(
        self, resolution_results: dict[str, PlayResolution]
    ) -> dict[str, int]:
        """Calculate resolution statistics for reporting."""

        stats = {
            "total": len(resolution_results),
            "direct_id": 0,
            "relinked_id": 0,
            "search_match": 0,
            "preserved_metadata": 0,
            "with_track_id": 0,
        }

        for result in resolution_results.values():
            stats[result.resolution_method] += 1
            if result.track_id is not None:
                stats["with_track_id"] += 1

        return stats

    async def _create_track_from_spotify_data(
        self, spotify_id: str, spotify_data: dict
    ) -> int | None:
        """Create internal track from Spotify API data."""
        try:
            # Create ConnectorTrack from Spotify data (reuse existing pattern)
            artists = [
                Artist(name=artist["name"])
                for artist in spotify_data.get("artists", [])
            ]

            connector_track = ConnectorTrack(
                connector_name="spotify",
                connector_track_id=spotify_id,
                title=spotify_data["name"],
                artists=artists,
                album=spotify_data.get("album", {}).get("name"),
                duration_ms=spotify_data.get("duration_ms"),
                isrc=spotify_data.get("external_ids", {}).get("isrc"),
                raw_metadata=spotify_data,
            )

            # Use existing infrastructure to create track
            created_tracks = (
                await self.track_repos.connector.ingest_external_tracks_bulk(
                    "spotify", [connector_track]
                )
            )

            if (
                created_tracks
                and len(created_tracks) > 0
                and created_tracks[0].id is not None
            ):
                logger.debug(
                    f"Created internal track {created_tracks[0].id} for Spotify ID {spotify_id}"
                )
                return created_tracks[0].id
            else:
                logger.warning(
                    f"Failed to create internal track for Spotify ID {spotify_id}"
                )
                return None

        except Exception as e:
            logger.error(f"Error creating track from Spotify data {spotify_id}: {e}")
            return None
