"""Core track repository implementation for database operations.

This module implements the repository pattern for track entities,
leveraging SQLAlchemy 2.0 best practices and the base repository functionality.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, cast, override

from attrs import define
from sqlalchemy import Select, desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from narada.config import get_logger
from narada.core.models import Artist, Track, ensure_utc
from narada.database.db_models import (
    DBConnectorTrack,
    DBTrack,
    DBTrackMapping,
    DBTrackMetric,
)
from narada.repositories.base import BaseModelMapper, BaseRepository
from narada.repositories.repo_decorator import db_operation

logger = get_logger(__name__)


@define(frozen=True, slots=True)
class TrackMapper(BaseModelMapper[DBTrack, Track]):
    """Bidirectional mapper between DB and domain models."""

    @staticmethod
    @override
    async def to_domain(db_model: DBTrack) -> Track:
        """Convert database track to domain model."""
        if not db_model:
            return None

        # Load mappings and likes using shared utility function
        from narada.repositories.base import safe_fetch_relationship

        mappings = await safe_fetch_relationship(db_model, "mappings")
        active_mappings = [m for m in mappings if not m.is_deleted]

        likes = await safe_fetch_relationship(db_model, "likes")
        active_likes = [like for like in likes if not like.is_deleted]

        # Build connector IDs and metadata
        connector_track_ids = {}
        connector_metadata = {}

        # Add internal ID first
        if db_model.id:
            connector_track_ids["db"] = str(db_model.id)

        # Add direct IDs from the track model
        if db_model.spotify_id:
            connector_track_ids["spotify"] = db_model.spotify_id
        if db_model.mbid:
            connector_track_ids["musicbrainz"] = db_model.mbid

        # Process connector track mappings
        for mapping in active_mappings:
            conn_track = await TrackMapper._get_connector_track(mapping)
            if conn_track and not conn_track.is_deleted:
                connector_name = conn_track.connector_name
                connector_track_ids[connector_name] = conn_track.connector_track_id
                connector_metadata[connector_name] = conn_track.raw_metadata or {}

        # Process likes into connector metadata
        for like in active_likes:
            service = like.service
            if service not in connector_metadata:
                connector_metadata[service] = {}

            connector_metadata[service]["is_liked"] = like.is_liked
            if like.liked_at:
                connector_metadata[service]["liked_at"] = like.liked_at.isoformat()

        return Track(
            id=db_model.id,
            title=db_model.title,
            artists=[Artist(name=name) for name in db_model.artists["names"]],
            album=db_model.album,
            duration_ms=db_model.duration_ms,
            release_date=ensure_utc(db_model.release_date),
            isrc=db_model.isrc,
            connector_track_ids=connector_track_ids,
            connector_metadata=connector_metadata,
        )

    @staticmethod
    async def _get_connector_track(mapping: DBTrackMapping) -> DBConnectorTrack | None:
        """Safely get connector track from mapping."""
        try:
            conn_track = mapping.connector_track
            if not conn_track and hasattr(mapping, "awaitable_attrs"):
                conn_track = await mapping.awaitable_attrs.connector_track
            return conn_track
        except (AttributeError, TypeError):
            return None

    @staticmethod
    @override
    def to_db(domain_model: Track) -> DBTrack:
        """Convert domain track to SQLAlchemy ORM database model.

        Returns only the DBTrack model to comply with ModelMapper protocol.
        """
        # Create the main track entity
        return DBTrack(
            title=domain_model.title,
            artists={"names": [a.name for a in domain_model.artists]},
            album=domain_model.album,
            duration_ms=domain_model.duration_ms,
            release_date=domain_model.release_date,
            isrc=domain_model.isrc,
            spotify_id=domain_model.connector_track_ids.get("spotify"),
            mbid=domain_model.connector_track_ids.get("musicbrainz"),
        )

    @staticmethod
    def to_db_with_connectors(
        domain_model: Track,
    ) -> tuple[DBTrack, list[DBConnectorTrack]]:
        """Convert domain track to SQLAlchemy ORM database models with connector tracks.

        Returns both DBTrack and associated DBConnectorTrack models.
        """
        # Create the main track entity
        db_track = TrackMapper.to_db(domain_model)

        # Create connector tracks for external services
        connector_tracks = [
            DBConnectorTrack(
                connector_name=name,
                connector_track_id=track_id,
                title=domain_model.title,
                artists={"names": [a.name for a in domain_model.artists]},
                album=domain_model.album,
                duration_ms=domain_model.duration_ms,
                release_date=domain_model.release_date,
                isrc=domain_model.isrc,
                raw_metadata=domain_model.connector_metadata.get(name, {}),
                last_updated=datetime.now(UTC),
            )
            for name, track_id in domain_model.connector_track_ids.items()
            if name not in ("db", "internal")
        ]

        return db_track, connector_tracks


class TrackRepository(BaseRepository[DBTrack, Track]):
    """Repository for track operations with SQLAlchemy 2.0 patterns."""

    # ID type lookup definitions
    _TRACK_ID_TYPES: ClassVar[dict[str, str]] = {
        "internal": "id",
        "spotify": "spotify_id",
        "isrc": "isrc",
        "musicbrainz": "mbid",
    }

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with session and mapper."""
        super().__init__(
            session=session,
            model_class=DBTrack,
            mapper=TrackMapper(),
        )

    # -------------------------------------------------------------------------
    # ENHANCED QUERY METHODS
    # -------------------------------------------------------------------------

    def select_with_relations(self) -> Select:
        """Create select statement with standard relations loaded."""
        return self.select().options(
            selectinload(self.model_class.mappings).selectinload(
                DBTrackMapping.connector_track,
            ),
            selectinload(self.model_class.likes),
        )

    def select_by_id_type(self, id_type: str, id_value: str) -> Select:
        """Build a query to fetch tracks by a specific ID type."""
        # Direct attribute lookup for known ID types
        if id_type in self._TRACK_ID_TYPES:
            column_name = self._TRACK_ID_TYPES[id_type]
            return self.select_with_relations().where(
                getattr(self.model_class, column_name) == id_value,
            )

        # External connector lookup via ConnectorTrack
        connector_subq = (
            select(DBConnectorTrack.id)
            .where(
                DBConnectorTrack.connector_name == id_type,
                DBConnectorTrack.connector_track_id == id_value,
                DBConnectorTrack.is_deleted == False,  # noqa: E712
            )
            .scalar_subquery()
        )

        return (
            self.select()
            .join(DBTrackMapping)
            .where(
                DBTrackMapping.connector_track_id == connector_subq,
                DBTrackMapping.is_deleted == False,  # noqa: E712
            )
            .options(
                selectinload(self.model_class.mappings).selectinload(
                    DBTrackMapping.connector_track,
                ),
                selectinload(self.model_class.likes),
            )
        )

    def select_metrics(
        self,
        track_ids: list[int],
        metric_type: str = "play_count",
        connector: str = "lastfm",
        cutoff_time: datetime | None = None,
    ) -> Select:
        """Build query for track metrics with ordering for most recent."""
        stmt = select(DBTrackMetric.track_id, DBTrackMetric.value).where(
            DBTrackMetric.track_id.in_(track_ids),
            DBTrackMetric.connector_name == connector,
            DBTrackMetric.metric_type == metric_type,
            DBTrackMetric.is_deleted == False,  # noqa: E712
        )

        if cutoff_time:
            stmt = stmt.where(DBTrackMetric.collected_at >= cutoff_time)

        # Order to get most recent metrics first
        return stmt.order_by(
            DBTrackMetric.track_id,
            desc(DBTrackMetric.collected_at),
        )

    # -------------------------------------------------------------------------
    # HELPER METHODS
    # -------------------------------------------------------------------------

    async def _find_track_by_id_type(
        self,
        id_type: str,
        id_value: str,
    ) -> DBTrack | None:
        """Find track by ID type and value."""
        stmt = self.select_by_id_type(id_type, id_value)
        result = await self.session.scalars(stmt)
        track = result.first()

        if track:
            logger.debug(
                "Found track by ID",
                id_type=id_type,
                id_value=id_value,
                track_id=track.id,
            )
        else:
            logger.debug(
                "Track not found",
                id_type=id_type,
                id_value=id_value,
            )

        return track

    async def _find_connector_track(
        self,
        connector: str,
        connector_id: str,
    ) -> DBConnectorTrack | None:
        """Find a connector track by connector name and ID."""
        stmt = select(DBConnectorTrack).where(
            DBConnectorTrack.connector_name == connector,
            DBConnectorTrack.connector_track_id == connector_id,
            DBConnectorTrack.is_deleted == False,  # noqa: E712
        )

        result = await self.session.scalars(stmt)
        return result.first()

    async def _create_connector_track_from_domain(
        self,
        track: Track,
        connector: str,
        connector_id: str,
    ) -> DBConnectorTrack:
        """Create a new connector track from domain model.

        This creates a representation of the track as it exists on the external service,
        not a copy of our internal track. The connector_track should store data as it
        appears on the external service, not our normalized version.
        """
        # Get connector-specific metadata - this should only contain service-specific data
        connector_metadata = track.connector_metadata.get(connector, {})

        # For artists, handle both string list and object list formats
        artist_names = []
        if "artists" in connector_metadata:
            if isinstance(connector_metadata["artists"], list):
                if all(isinstance(a, str) for a in connector_metadata["artists"]):
                    # List of strings
                    artist_names = connector_metadata["artists"]
                elif all(isinstance(a, dict) for a in connector_metadata["artists"]):
                    # List of objects (common in Spotify)
                    artist_names = [
                        a.get("name", "") for a in connector_metadata["artists"]
                    ]

        # If no artists in metadata, fall back to our track's artists
        if not artist_names and track.artists:
            artist_names = [a.name for a in track.artists]

        # Create the connector track with service data (or fallback to our data)
        conn_track = DBConnectorTrack(
            connector_name=connector,
            connector_track_id=connector_id,
            title=connector_metadata.get("title", track.title),
            artists={"names": artist_names},
            album=connector_metadata.get("album", track.album),
            duration_ms=connector_metadata.get("duration_ms", track.duration_ms),
            release_date=connector_metadata.get("release_date", track.release_date),
            isrc=connector_metadata.get("isrc", track.isrc),
            # Store the raw metadata but ensure we don't include match info
            raw_metadata={
                k: v
                for k, v in connector_metadata.items()
                if k
                not in [
                    "confidence",
                    "match_method",
                    "confidence_evidence",
                    "matched_at",
                ]
            },
            last_updated=datetime.now(UTC),
        )

        self.session.add(conn_track)
        await self.session.flush()
        return conn_track

    async def _save_connector_track(
        self,
        track: Track,
        connector: str,
    ) -> DBConnectorTrack | None:
        """Save a connector track, updating if it exists."""
        # Skip internal identifiers
        if connector in ("db", "internal"):
            return None

        connector_id = track.connector_track_ids.get(connector)
        if not connector_id:
            return None

        # Check if exists
        conn_track = await self._find_connector_track(connector, connector_id)

        if conn_track:
            # Update metadata if needed, but exclude matching information
            if track.connector_metadata.get(connector):
                # Filter out match-related fields that should stay in track_mappings
                filtered_metadata = {
                    k: v
                    for k, v in track.connector_metadata[connector].items()
                    if k
                    not in [
                        "confidence",
                        "match_method",
                        "confidence_evidence",
                        "matched_at",
                    ]
                }

                if filtered_metadata:
                    conn_track.raw_metadata = filtered_metadata
                    conn_track.last_updated = datetime.now(UTC)
                    self.session.add(conn_track)
            return conn_track

        # Create new connector track using the helper method
        return await self._create_connector_track_from_domain(
            track, connector, connector_id
        )

    async def _update_track_mappings(
        self, db_track: DBTrack, track: Track, match_method: str, confidence: int
    ) -> None:
        """
        Create new track mappings with explicit match method and confidence.

        This method only creates new mappings - existing mappings are never modified.

        Args:
            db_track: Database track object
            track: Domain model track with connector IDs
            match_method: How the mapping was determined ("direct", "mbid", "isrc", "artist_title")
            confidence: Confidence score (0-100) representing mapping reliability
        """
        for connector in track.connector_track_ids:
            if connector in ("db", "internal"):
                continue

            # Save connector track first
            conn_track = await self._save_connector_track(track, connector)
            if not conn_track:
                continue

            # Use our helper method to create mapping if it doesn't exist
            await self._get_or_create_mapping(
                track_id=db_track.id,
                connector_track_id=conn_track.id,
                match_method=match_method,
                confidence=confidence,
            )

        await self.session.flush()

    # -------------------------------------------------------------------------
    # PUBLIC API METHODS
    # -------------------------------------------------------------------------

    @db_operation("get_track")
    async def get_track(self, id_type: str, id_value: str) -> Track:
        """Get track by any identifier type."""
        db_track = await self._find_track_by_id_type(id_type, id_value)

        if not db_track:
            raise ValueError(f"Track with {id_type}={id_value} not found")

        return await cast("TrackMapper", self.mapper).to_domain(db_track)

    @db_operation("find_track")
    async def find_track(self, id_type: str, id_value: str) -> Track | None:
        """Find track by identifier, returning None if not found."""
        db_track = await self._find_track_by_id_type(id_type, id_value)
        if not db_track:
            return None

        return await cast("TrackMapper", self.mapper).to_domain(db_track)

    @db_operation("save_track")
    async def save_track(self, track: Track) -> Track:
        """Save track and mappings efficiently.

        Note: This method handles track data only - it doesn't create mappings
        beyond the primary connector. For mapping tracks to other connectors,
        use the create_track_from_connector_data() or map_track_to_connector()
        methods which handle the different mapping scenarios properly.
        """
        if not track.title or not track.artists:
            raise ValueError("Track must have title and artists")

        # Find or create the track
        if track.id:
            # Update existing track by ID
            return await self._update_existing_track(track)
        elif track.isrc or "spotify" in track.connector_track_ids:
            # Try to find by ISRC or Spotify ID
            return await self._find_or_create_track(track)
        else:
            # Create new track
            return await self._create_new_track(track)

    @db_operation("create_track_from_connector_data")
    async def create_track_from_connector_data(
        self, track: Track, connector: str
    ) -> Track:
        """Create a track directly from connector data.

        This method is for the scenario where we import a track directly from
        an external service (e.g., creating a track from a Spotify playlist).
        In this case, the mapping is "direct" with 100% confidence because
        we're not matching - we're directly sourcing from this connector.

        Args:
            track: The track with connector data
            connector: The connector name that is the source of this track

        Returns:
            Saved track with ID and all mappings
        """
        if not track.title or not track.artists:
            raise ValueError("Track must have title and artists")

        if connector not in track.connector_track_ids:
            raise ValueError(f"Track doesn't have an ID for connector {connector}")

        # Save the track first (without mappings)
        saved_track = await self.save_track(track)

        # Ensure we have a database ID
        if saved_track.id is None:
            raise ValueError("Failed to generate ID for track")

        # Now explicitly create the connector track and mapping with "direct" method
        db_track = await self._find_track_by_id_type("internal", str(saved_track.id))
        if not db_track:
            raise ValueError(f"Track with ID {saved_track.id} not found after saving")

        # Create connector track and mapping with "direct" method and 100% confidence
        connector_id = saved_track.connector_track_ids.get(connector)
        if connector_id:
            # Get or create connector track
            conn_track = await self._save_connector_track(saved_track, connector)
            if conn_track:
                # Create mapping using our helper method - always direct with 100% confidence
                await self._get_or_create_mapping(
                    track_id=db_track.id,
                    connector_track_id=conn_track.id,
                    match_method="direct",  # Always "direct" for source data
                    confidence=100,  # Always 100% for source data
                )

        return saved_track

    async def _create_track_mapping(
        self,
        track_id: int,
        connector_track_id: int,
        match_method: str,
        confidence: int,
        confidence_evidence: dict | None = None,
    ) -> DBTrackMapping:
        """Create a track mapping with the specified attributes."""
        mapping = DBTrackMapping(
            track_id=track_id,
            connector_track_id=connector_track_id,
            match_method=match_method,
            confidence=confidence,
            confidence_evidence=confidence_evidence,
        )
        self.session.add(mapping)
        await self.session.flush()
        return mapping

    async def _get_or_create_mapping(
        self,
        track_id: int,
        connector_track_id: int,
        match_method: str,
        confidence: int,
        confidence_evidence: dict | None = None,
    ) -> DBTrackMapping:
        """Find an existing mapping or create a new one if it doesn't exist."""
        # Look for existing mapping
        mapping_stmt = select(DBTrackMapping).where(
            DBTrackMapping.track_id == track_id,
            DBTrackMapping.connector_track_id == connector_track_id,
            DBTrackMapping.is_deleted == False,  # noqa: E712
        )

        existing_mapping = await self.session.scalar(mapping_stmt)
        if existing_mapping:
            return existing_mapping

        # Create new mapping
        return await self._create_track_mapping(
            track_id=track_id,
            connector_track_id=connector_track_id,
            match_method=match_method,
            confidence=confidence,
            confidence_evidence=confidence_evidence,
        )

    @db_operation("map_track_to_connector")
    async def map_track_to_connector(
        self,
        track: Track,
        connector: str,
        connector_id: str,
        match_method: str,
        confidence: int,
        metadata: dict | None = None,
    ) -> Track:
        """Map an existing track to a connector with explicit match method and confidence.

        This method is for the scenario where we match an existing track to an
        external service (e.g., finding the Spotify equivalent of a LastFM track).
        In this case, the mapping method and confidence come from the matcher.

        Args:
            track: The existing track to map
            connector: The connector name (e.g., "spotify", "lastfm")
            connector_id: The ID in the external service
            match_method: How the match was made (e.g., "mbid", "artist_title")
            confidence: Confidence score (0-100)
            metadata: Additional metadata for the connector

        Returns:
            Updated track with new mapping
        """
        if track.id is None:
            raise ValueError("Cannot map track with no ID")

        # Find the track in the database
        db_track = await self._find_track_by_id_type("internal", str(track.id))
        if not db_track:
            raise ValueError(f"Track with ID {track.id} not found")

        # Update track object with the new connector ID
        updated_track = track.with_connector_track_id(connector, connector_id)

        # Store actual service data in the connector_metadata
        # Matching info will be stored separately in the track_mapping table
        if metadata:
            # Only include service data that describes the track on the external service
            # Explicitly exclude matching-related fields that belong in track_mappings
            exclude_fields = [
                "confidence",
                "match_method",
                "confidence_evidence",
                "matched_at",
            ]
            service_metadata = {
                k: v for k, v in metadata.items() if k not in exclude_fields
            }

            if service_metadata:
                updated_track = updated_track.with_connector_metadata(
                    connector, service_metadata
                )

        # Create or get the connector track
        connector_track = await self._find_connector_track(connector, connector_id)
        if not connector_track:
            # Create new connector track using our helper method
            connector_track = await self._create_connector_track_from_domain(
                track=updated_track, connector=connector, connector_id=connector_id
            )

        # Create or get the mapping with explicit match method and confidence
        # This is where all matching information belongs - in the track_mapping table
        await self._get_or_create_mapping(
            track_id=db_track.id,
            connector_track_id=connector_track.id,
            match_method=match_method,
            confidence=confidence,
            confidence_evidence=metadata.get("confidence_evidence")
            if metadata
            else None,
        )

        return updated_track

    async def _update_existing_track(self, track: Track) -> Track:
        """Update an existing track by ID."""
        if track.id is None:
            raise ValueError("Cannot update track with None ID")
        db_track = await self._execute_query_one(self.select_by_id(track.id))
        if not db_track:
            raise ValueError(f"Track with ID {track.id} not found")

        # Update fields if needed
        for field in ["release_date", "duration_ms"]:
            if getattr(track, field) and not getattr(db_track, field):
                setattr(db_track, field, getattr(track, field))
                db_track.updated_at = datetime.now(UTC)
                break

        self.session.add(db_track)

        # Return track with internal ID
        return track.with_id(db_track.id).with_connector_track_id(
            "db",
            str(db_track.id),
        )

    async def _find_or_create_track(self, track: Track) -> Track:
        """Find track by ISRC or Spotify ID, or create if not found."""
        stmt = None

        # Try ISRC first (preferred cross-platform identifier)
        if track.isrc:
            stmt = self.select_by_id_type("isrc", track.isrc)
        # Then try Spotify ID
        elif "spotify" in track.connector_track_ids:
            stmt = self.select_by_id_type(
                "spotify",
                track.connector_track_ids["spotify"],
            )

        if stmt is not None:
            db_track = await self._execute_query_one(stmt)
            if db_track:
                # Found the track, return with ID
                return track.with_id(db_track.id).with_connector_track_id(
                    "db",
                    str(db_track.id),
                )

        # Create new if not found
        return await self._create_new_track(track)

    async def _create_new_track(self, track: Track) -> Track:
        """Create a new track without connector mappings."""
        # Convert domain model to DB model
        db_track = self.mapper.to_db(track)

        # Save track
        self.session.add(db_track)
        await self.session.flush()
        await self.session.refresh(db_track)

        # Verify ID was generated
        if not db_track.id:
            raise ValueError("Failed to create track: No ID was generated")

        await self.session.flush()

        # Return with proper ID
        return track.with_id(db_track.id).with_connector_track_id(
            "db",
            str(db_track.id),
        )

    @db_operation("get_connector_mappings")
    async def get_connector_mappings(
        self,
        track_ids: list[int],
        connector: str | None = None,
    ) -> dict[int, dict[str, str]]:
        """Get mappings between tracks and external connectors."""
        if not track_ids:
            return {}

        # Build efficient join query
        stmt = (
            select(
                DBTrackMapping.track_id,
                DBConnectorTrack.connector_name,
                DBConnectorTrack.connector_track_id,
            )
            .join(
                DBConnectorTrack,
                DBTrackMapping.connector_track_id == DBConnectorTrack.id,
            )
            .where(
                DBTrackMapping.track_id.in_(track_ids),
                DBTrackMapping.is_deleted == False,  # noqa: E712
                DBConnectorTrack.is_deleted == False,  # noqa: E712
            )
        )

        if connector:
            stmt = stmt.where(DBConnectorTrack.connector_name == connector)

        # Execute and build response
        result = await self.session.execute(stmt)

        mappings_dict = {}
        for track_id, conn_name, conn_id in result:
            mappings_dict.setdefault(track_id, {})[conn_name] = conn_id

        return mappings_dict

    @db_operation("get_connector_metadata")
    async def get_connector_metadata(
        self,
        track_ids: list[int],
        connector: str,
        metadata_field: str | None = None,
    ) -> dict[int, dict[str, Any] | Any]:
        """Get connector metadata for tracks.

        Args:
            track_ids: List of track IDs to get metadata for
            connector: Connector name (e.g., "spotify", "lastfm")
            metadata_field: Optional specific field to extract from metadata

        Returns:
            If metadata_field is None: dict mapping track_id -> full metadata dict
            If metadata_field is specified: dict mapping track_id -> specific field value
        """
        if not track_ids:
            return {}

        # Use the base repository pattern to build and execute the query
        # This statement fetches track_id and raw_metadata pairs from connector tracks
        result = await self.session.execute(
            select(
                DBTrackMapping.track_id,
                DBConnectorTrack.raw_metadata,
            )
            .join(
                DBConnectorTrack,
                DBTrackMapping.connector_track_id == DBConnectorTrack.id,
            )
            .where(
                DBTrackMapping.track_id.in_(track_ids),
                DBConnectorTrack.connector_name == connector,
                DBTrackMapping.is_deleted == False,  # noqa: E712
                DBConnectorTrack.is_deleted == False,  # noqa: E712
            ),
        )

        # Return either the specific field or all metadata
        if metadata_field:
            return {
                track_id: metadata.get(metadata_field)
                for track_id, metadata in result
                if metadata and metadata_field in metadata
            }
        else:
            return {track_id: metadata for track_id, metadata in result if metadata}

    @db_operation("get_track_metrics")
    async def get_track_metrics(
        self,
        track_ids: list[int],
        metric_type: str = "play_count",
        connector: str = "lastfm",
        max_age_hours: int = 24,
    ) -> dict[int, int]:
        """Get cached metrics with TTL awareness."""
        if not track_ids:
            return {}

        # Calculate cutoff time
        cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)

        # Build and execute query
        stmt = self.select_metrics(track_ids, metric_type, connector, cutoff)
        result = await self.session.execute(stmt)

        # Process results - only keep most recent value per track
        metrics_dict = {}
        for track_id, value in result:
            if track_id not in metrics_dict:
                metrics_dict[track_id] = int(value)

        logger.debug(
            f"Retrieved {len(metrics_dict)}/{len(track_ids)} track metrics",
            metric_type=metric_type,
            connector=connector,
        )

        return metrics_dict

    @db_operation("save_track_metrics")
    async def save_track_metrics(
        self,
        metrics: list[tuple[int, str, str, float]],
    ) -> int:
        """Save metrics for multiple tracks efficiently.

        Args:
            metrics: List of (track_id, connector_name, metric_type, value) tuples
        """
        if not metrics:
            return 0

        # Bulk insert metrics
        now = datetime.now(UTC)
        metric_records = [
            DBTrackMetric(
                track_id=track_id,
                connector_name=connector_name,
                metric_type=metric_type,
                value=value,
                collected_at=now,
            )
            for track_id, connector_name, metric_type, value in metrics
        ]

        # Add all at once
        self.session.add_all(metric_records)
        await self.session.flush()

        return len(metric_records)

    @db_operation("get_or_create")
    async def get_or_create(
        self,
        lookup_attrs: dict[str, Any],
        create_attrs: dict[str, Any] | None = None,
    ) -> tuple[Track, bool]:
        """Find a track by attributes or create it if it doesn't exist."""
        # Build query using attributes
        stmt = self.select()
        for field, value in lookup_attrs.items():
            if hasattr(self.model_class, field):
                stmt = stmt.where(getattr(self.model_class, field) == value)

        # Execute query
        db_track = await self._execute_query_one(stmt.limit(1))

        if db_track:
            # Found existing track
            track = await cast("TrackMapper", self.mapper).to_domain(db_track)
            return track, False

        # Create new track from attrs
        all_attrs = {**lookup_attrs}
        if create_attrs:
            all_attrs.update(create_attrs)

        # Process artists data
        artists = []
        for artist_data in all_attrs.get("artists", []):
            if isinstance(artist_data, str):
                artists.append(Artist(name=artist_data))
            elif isinstance(artist_data, Artist):
                artists.append(artist_data)
            elif isinstance(artist_data, dict) and "name" in artist_data:
                artists.append(Artist(name=artist_data["name"]))

        # Create and save track
        track = Track(
            title=all_attrs.get("title", ""),
            artists=artists or [Artist(name="")] if all_attrs.get("title") else [],
            album=all_attrs.get("album"),
            duration_ms=all_attrs.get("duration_ms"),
            release_date=ensure_utc(all_attrs.get("release_date")),
            isrc=all_attrs.get("isrc"),
            connector_track_ids=all_attrs.get("connector_track_ids", {}),
            connector_metadata=all_attrs.get("connector_metadata", {}),
        )

        result_track = await self.save_track(track)
        return result_track, True

    @db_operation("save_mapping_confidence_evidence")
    async def save_mapping_confidence_evidence(
        self, track_id: int, connector: str, connector_id: str, evidence: dict
    ) -> bool:
        """Save confidence evidence to the track_mapping record.

        Args:
            track_id: Internal track ID
            connector: The connector name (spotify, lastfm, etc.)
            connector_id: The external track ID in the connector
            evidence: Dictionary of confidence scoring evidence

        Returns:
            True if mapping was found and updated, False otherwise
        """
        from sqlalchemy import select, update

        # Find the connector track ID first
        stmt = select(DBConnectorTrack.id).where(
            DBConnectorTrack.connector_name == connector,
            DBConnectorTrack.connector_track_id == connector_id,
            DBConnectorTrack.is_deleted == False,  # noqa: E712
        )

        connector_track_id = await self.session.scalar(stmt)
        if not connector_track_id:
            return False

        # Now update the mapping
        stmt = (
            update(DBTrackMapping)
            .where(
                DBTrackMapping.track_id == track_id,
                DBTrackMapping.connector_track_id == connector_track_id,
                DBTrackMapping.is_deleted == False,  # noqa: E712
            )
            .values(
                confidence_evidence=evidence,
                updated_at=datetime.now(UTC),
            )
        )

        result = await self.session.execute(stmt)
        return result.rowcount > 0

    @db_operation("get_mapping_confidence_evidence")
    async def get_mapping_confidence_evidence(
        self, track_id: int, connector: str, connector_id: str
    ) -> dict | None:
        """Get confidence evidence from a track_mapping record.

        Args:
            track_id: Internal track ID
            connector: The connector name (spotify, lastfm, etc.)
            connector_id: The external track ID in the connector

        Returns:
            Dictionary of confidence evidence or None if not found
        """
        from sqlalchemy import join, select

        # Join connector_tracks to find the connector_track_id
        stmt = (
            select(DBTrackMapping.confidence_evidence)
            .select_from(
                join(
                    DBTrackMapping,
                    DBConnectorTrack,
                    DBTrackMapping.connector_track_id == DBConnectorTrack.id,
                )
            )
            .where(
                DBTrackMapping.track_id == track_id,
                DBConnectorTrack.connector_name == connector,
                DBConnectorTrack.connector_track_id == connector_id,
                DBTrackMapping.is_deleted == False,  # noqa: E712
                DBConnectorTrack.is_deleted == False,  # noqa: E712
            )
        )

        return await self.session.scalar(stmt)
