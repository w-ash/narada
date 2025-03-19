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
from narada.repositories.base import BaseRepository, ModelMapper
from narada.repositories.repo_decorator import db_operation

logger = get_logger(__name__)


@define(frozen=True, slots=True)
class TrackMapper(ModelMapper[DBTrack, Track]):
    """Bidirectional mapper between DB and domain models."""

    @staticmethod
    async def to_domain(db_track: DBTrack) -> Track:
        """Convert database track to domain model."""
        if not db_track:
            return None

        # Load mappings and likes
        mappings = await TrackMapper._load_relationship(db_track, "mappings")
        active_mappings = [m for m in mappings if not m.is_deleted]

        likes = await TrackMapper._load_relationship(db_track, "likes")
        active_likes = [like for like in likes if not like.is_deleted]

        # Build connector IDs and metadata
        connector_track_ids = {}
        connector_metadata = {}

        # Add internal ID first
        if db_track.id:
            connector_track_ids["db"] = str(db_track.id)

        # Add direct IDs from the track model
        if db_track.spotify_id:
            connector_track_ids["spotify"] = db_track.spotify_id
        if db_track.mbid:
            connector_track_ids["musicbrainz"] = db_track.mbid

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
            id=db_track.id,
            title=db_track.title,
            artists=[Artist(name=name) for name in db_track.artists["names"]],
            album=db_track.album,
            duration_ms=db_track.duration_ms,
            release_date=ensure_utc(db_track.release_date),
            isrc=db_track.isrc,
            connector_track_ids=connector_track_ids,
            connector_metadata=connector_metadata,
        )

    @staticmethod
    async def _load_relationship(db_model: Any, rel_name: str) -> list[Any]:
        """Helper to safely load relationships with fallback to async loading."""
        try:
            items = getattr(db_model, rel_name, [])

            if (
                not items
                and hasattr(db_model, rel_name)
                and hasattr(db_model, "awaitable_attrs")
            ):
                items = await getattr(db_model.awaitable_attrs, rel_name)

            return items
        except (AttributeError, TypeError):
            if hasattr(db_model, "awaitable_attrs") and hasattr(
                db_model.awaitable_attrs,
                rel_name,
            ):
                return await getattr(db_model.awaitable_attrs, rel_name)
            return []

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
    def to_db(domain_model: Track) -> tuple[DBTrack, list[DBConnectorTrack]]:
        """Convert domain track to SQLAlchemy ORM database models.

        Returns the DBTrack and associated DBConnectorTrack models.
        """
        # Create the main track entity
        db_track = DBTrack(
            title=domain_model.title,
            artists={"names": [a.name for a in domain_model.artists]},
            album=domain_model.album,
            duration_ms=domain_model.duration_ms,
            release_date=domain_model.release_date,
            isrc=domain_model.isrc,
            spotify_id=domain_model.connector_track_ids.get("spotify"),
            mbid=domain_model.connector_track_ids.get("musicbrainz"),
        )

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
            # Update metadata if needed
            if track.connector_metadata.get(connector):
                conn_track.raw_metadata = track.connector_metadata[connector]
                conn_track.last_updated = datetime.now(UTC)
                self.session.add(conn_track)
            return conn_track

        # Create new connector track
        conn_track = DBConnectorTrack(
            connector_name=connector,
            connector_track_id=connector_id,
            title=track.title,
            artists={"names": [a.name for a in track.artists]},
            album=track.album,
            duration_ms=track.duration_ms,
            release_date=track.release_date,
            isrc=track.isrc,
            raw_metadata=track.connector_metadata.get(connector, {}),
            last_updated=datetime.now(UTC),
        )

        self.session.add(conn_track)
        await self.session.flush()
        return conn_track

    async def _update_track_mappings(self, db_track: DBTrack, track: Track) -> None:
        """Update track mappings with new connector data."""
        for connector in track.connector_track_ids:
            if connector in ("db", "internal"):
                continue

            # Save connector track first
            conn_track = await self._save_connector_track(track, connector)
            if not conn_track:
                continue

            # Find existing mapping
            stmt = select(DBTrackMapping).where(
                DBTrackMapping.track_id == db_track.id,
                DBTrackMapping.connector_track_id == conn_track.id,
                DBTrackMapping.is_deleted == False,  # noqa: E712
            )

            result = await self.session.scalars(stmt)
            mapping = result.first()

            if not mapping:
                # Create new mapping
                mapping = DBTrackMapping(
                    track_id=db_track.id,
                    connector_track_id=conn_track.id,
                    match_method="direct",
                    confidence=100,
                )
                self.session.add(mapping)

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
        """Save track and mappings efficiently."""
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
        await self._update_track_mappings(db_track, track)

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
                # Update existing track
                await self._update_track_mappings(db_track, track)
                return track.with_id(db_track.id).with_connector_track_id(
                    "db",
                    str(db_track.id),
                )

        # Create new if not found
        return await self._create_new_track(track)

    async def _create_new_track(self, track: Track) -> Track:
        """Create a new track with all connector records."""
        # Convert to DB models
        db_track, connector_tracks = cast("TrackMapper", self.mapper).to_db(track)

        # Save track
        self.session.add(db_track)
        await self.session.flush()
        await self.session.refresh(db_track)

        # Verify ID was generated
        if not db_track.id:
            raise ValueError("Failed to create track: No ID was generated")

        # Save connector tracks
        for conn_track in connector_tracks:
            self.session.add(conn_track)

        await self.session.flush()

        # Create mappings
        for conn_track in connector_tracks:
            mapping = DBTrackMapping(
                track_id=db_track.id,
                connector_track_id=conn_track.id,
                match_method="direct",
                confidence=100,
            )
            self.session.add(mapping)

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
