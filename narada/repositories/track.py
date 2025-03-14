"""Track repository implementation for database operations."""

from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, override

from attrs import define
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from narada.config import get_logger
from narada.core.models import Artist, Track, ensure_utc
from narada.database.db_models import DBPlayCount, DBTrack, DBTrackMapping
from narada.repositories.base import BaseRepository, ModelMapper
from narada.repositories.repo_decorator import db_operation

logger = get_logger(__name__)


@define(frozen=True, slots=True)
class TrackMapper(ModelMapper[DBTrack, Track]):
    """Bidirectional mapper between DB and domain models."""

    @staticmethod
    async def to_domain(db_model: DBTrack) -> Track:
        """Convert database track to domain model."""
        if not db_model:
            return None

        # Get mappings - try direct access first (for eagerly loaded relationships)
        # Fall back to awaitable_attrs only if necessary
        try:
            mappings = db_model.mappings
            # If mappings is empty but the relationship exists, it might need to be loaded
            if (
                hasattr(db_model, "mappings")
                and not mappings
                and hasattr(db_model, "awaitable_attrs")
            ):
                mappings = await db_model.awaitable_attrs.mappings
        except (AttributeError, TypeError):
            # If direct access fails but the relationship exists, try the async way
            if hasattr(db_model, "awaitable_attrs") and hasattr(
                db_model.awaitable_attrs,
                "mappings",
            ):
                mappings = await db_model.awaitable_attrs.mappings
            else:
                mappings = []

        active_mappings = [m for m in mappings if not m.is_deleted]

        # Log the mappings to help with debugging
        logger.debug(
            "Converting track to domain model",
            track_id=db_model.id,
            title=db_model.title,
            mapping_count=len(active_mappings),
            mappings={m.connector_name: m.connector_track_id for m in active_mappings},
        )

        return Track(
            id=db_model.id,
            title=db_model.title,
            artists=[Artist(name=name) for name in db_model.artists["names"]],
            album=db_model.album,
            duration_ms=db_model.duration_ms,
            release_date=ensure_utc(db_model.release_date),
            isrc=db_model.isrc,
            connector_track_ids={
                m.connector_name: m.connector_track_id for m in active_mappings
            },
            connector_metadata={
                m.connector_name: m.connector_metadata
                for m in active_mappings
                if m.connector_metadata
            },
        )

    @staticmethod
    @override
    def to_db(domain_model: Track) -> DBTrack:
        """Convert domain track to SQLAlchemy ORM database model."""
        # Create mappings for external connectors
        mappings = []
        for name, track_id in domain_model.connector_track_ids.items():
            if name in ("db", "internal"):
                continue

            mappings.append(
                DBTrackMapping(
                    connector_name=name,
                    connector_track_id=track_id,
                    match_method="source",
                    confidence=100,
                    connector_metadata=domain_model.connector_metadata.get(name, {}),
                ),
            )

        # Return a complete DBTrack ORM object
        return DBTrack(
            title=domain_model.title,
            artists={"names": [a.name for a in domain_model.artists]},
            album=domain_model.album,
            duration_ms=domain_model.duration_ms,
            release_date=domain_model.release_date,
            isrc=domain_model.isrc,
            spotify_id=domain_model.connector_track_ids.get("spotify"),
            musicbrainz_id=domain_model.connector_track_ids.get("musicbrainz"),
            mappings=mappings,
        )


class TrackRepository(BaseRepository[DBTrack, Track]):
    """Repository for track operations with SQLAlchemy 2.0 patterns."""

    # ID type lookup definitions
    _TRACK_ID_TYPES: ClassVar[dict[str, str]] = {
        "internal": "id",
        "spotify": "spotify_id",
        "isrc": "isrc",
        "musicbrainz": "musicbrainz_id",
    }

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with session and mapper."""
        super().__init__(
            session=session,
            model_class=DBTrack,
            mapper=TrackMapper(),
        )

    # -------------------------------------------------------------------------
    # HELPER METHODS (non-decorated)
    # -------------------------------------------------------------------------

    async def _find_track_by_id_type(
        self,
        id_type: str,
        id_value: str,
    ) -> DBTrack | None:
        """Find track by ID type and value."""
        # Use correct column based on ID type
        if id_type in self._TRACK_ID_TYPES:
            # Direct attribute lookup
            column_name = self._TRACK_ID_TYPES[id_type]
            stmt = (
                self.select()
                .where(getattr(self.model_class, column_name) == id_value)
                .options(
                    selectinload(self.model_class.mappings),
                    selectinload(self.model_class.play_counts),
                )
            )
        else:
            # External connector lookup
            stmt = (
                self.select()
                .join(DBTrackMapping)
                .where(
                    DBTrackMapping.connector_name == id_type,
                    DBTrackMapping.connector_track_id == id_value,
                    DBTrackMapping.is_deleted == False,  # noqa: E712
                )
                .options(
                    selectinload(self.model_class.mappings),
                    selectinload(self.model_class.play_counts),
                )
            )

        # Execute query
        result = await self.session.scalars(stmt)
        track = result.first()

        # Log what we found to help with debugging
        if track:
            logger.debug(
                "Found track by ID",
                id_type=id_type,
                id_value=id_value,
                track_id=track.id,
                title=track.title,
                mapping_count=len(track.mappings)
                if hasattr(track, "mappings")
                else "unknown",
            )
        else:
            logger.debug(
                "Track not found",
                id_type=id_type,
                id_value=id_value,
            )

        return track

    async def _update_track_mappings(self, db_track: DBTrack, track: Track) -> None:
        """Update track mappings with new connector data."""
        now = datetime.now(UTC)

        # Process each connector in the track
        for connector, connector_id in track.connector_track_ids.items():
            if connector in ("db", "internal"):
                continue

            metadata = track.connector_metadata.get(connector, {})
            existing = next(
                (
                    m
                    for m in db_track.mappings
                    if m.connector_name == connector and not m.is_deleted
                ),
                None,
            )

            # Update or create mapping
            if existing:
                if existing.connector_metadata != metadata:
                    existing.connector_metadata = metadata
                    existing.last_verified = now
                    existing.updated_at = now
                    flag_modified(existing, "connector_metadata")
                    self.session.add(existing)
            else:
                self.session.add(
                    DBTrackMapping(
                        track_id=db_track.id,
                        connector_name=connector,
                        connector_track_id=connector_id,
                        confidence=100,
                        match_method="source",
                        connector_metadata=metadata,
                        last_verified=now,
                    ),
                )

        await self.session.flush()

    # -------------------------------------------------------------------------
    # PUBLIC API METHODS (decorated)
    # -------------------------------------------------------------------------

    @db_operation("get_track")
    async def get_track(self, id_type: str, id_value: str) -> Track:
        """Get track by any identifier type."""
        # Find DB entity
        db_track = await self._find_track_by_id_type(id_type, id_value)

        if not db_track:
            raise ValueError(f"Track with {id_type}={id_value} not found")

        # Convert to domain model
        return await self.mapper.to_domain(db_track)

    @db_operation("save_track")
    async def save_track(self, track: Track) -> Track:
        """Save track and mappings efficiently."""
        if not track.title or not track.artists:
            raise ValueError("Track must have title and artists")

        # Try identifiers in priority order
        stmt = None

        # Try ID first
        if track.id:
            stmt = (
                self.select()
                .where(self.model_class.id == track.id)
                .options(selectinload(self.model_class.mappings))
            )
        # Try ISRC
        elif track.isrc:
            stmt = (
                self.select()
                .where(self.model_class.isrc == track.isrc)
                .options(selectinload(self.model_class.mappings))
            )
        # Try Spotify ID
        elif "spotify" in track.connector_track_ids:
            stmt = (
                self.select()
                .where(
                    self.model_class.spotify_id == track.connector_track_ids["spotify"],
                )
                .options(selectinload(self.model_class.mappings))
            )

        # Execute query if we built one
        db_track = None
        if stmt is not None:
            result = await self.session.scalars(stmt)
            db_track = result.first()

        # Handle existing track
        if db_track:
            # Update with new track data
            updated_track = track.with_id(db_track.id).with_connector_track_id(
                "db",
                str(db_track.id),
            )

            # Update missing fields
            for field, value in {
                "release_date": track.release_date,
                "duration_ms": track.duration_ms,
            }.items():
                if value and not getattr(db_track, field):
                    setattr(db_track, field, value)
                    db_track.updated_at = datetime.now(UTC)
                    self.session.add(db_track)
                    break

            # Update mappings
            await self._update_track_mappings(db_track, track)

            return updated_track
        else:
            # Create new track
            db_track = self.mapper.to_db(track)
            self.session.add(db_track)

            # Flush and refresh to get ID
            await self.session.flush()
            await self.session.refresh(db_track)

            # Verify ID existence
            if db_track.id is None:
                raise ValueError("Failed to create track: No ID was generated")

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

        # Build and execute query
        stmt = select(
            DBTrackMapping.track_id,
            DBTrackMapping.connector_name,
            DBTrackMapping.connector_track_id,
        ).where(
            DBTrackMapping.track_id.in_(track_ids),
            DBTrackMapping.is_deleted == False,  # noqa: E712
        )

        if connector:
            stmt = stmt.where(DBTrackMapping.connector_name == connector)

        result = await self.session.execute(stmt)

        # Process results efficiently
        mappings = {}
        for track_id, conn_name, conn_id in result:
            mappings.setdefault(track_id, {})[conn_name] = conn_id

        return mappings

    @db_operation("get_track_mapping_details")
    async def get_track_mapping_details(
        self,
        track_id: int,
        connector_name: str,
    ) -> DBTrackMapping | None:
        """Get mapping details for a track by connector name with timestamp info."""
        stmt = select(DBTrackMapping).where(
            DBTrackMapping.track_id == track_id,
            DBTrackMapping.connector_name == connector_name,
            DBTrackMapping.is_deleted == False,  # noqa: E712
        )

        result = await self.session.scalars(stmt)
        return result.first()

    @db_operation("get_track_metrics")
    async def get_track_metrics(
        self,
        track_ids: list[int],
        metric_type: str = "play_count",
        max_age_hours: int = 24,
    ) -> dict[int, int]:
        """Get cached metrics with TTL awareness."""
        if not track_ids:
            return {}

        # Calculate cutoff timestamp for TTL
        cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)

        # Build query
        stmt = select(DBPlayCount.track_id, DBPlayCount.play_count).where(
            DBPlayCount.track_id.in_(track_ids),
            DBPlayCount.last_updated >= cutoff,
            DBPlayCount.is_deleted == False,  # noqa: E712
        )

        # Execute the query
        result = await self.session.execute(stmt)

        # Process results
        metrics_dict = {track_id: play_count for track_id, play_count in result}  # noqa: C416

        logger.debug(
            f"Retrieved {len(metrics_dict)}/{len(track_ids)} track metrics",
            extra={"metric_type": metric_type, "max_age_hours": max_age_hours},
        )

        return metrics_dict

    @db_operation("save_track_metrics")
    async def save_track_metrics(
        self,
        metrics: list[tuple[int, str, str, int, int]],
    ) -> int:
        """Save metrics for multiple tracks efficiently."""
        if not metrics:
            return 0

        now = datetime.now(UTC)
        updated_count = 0

        # Process each metric
        for track_id, user_id, _, play_count, user_play_count in metrics:
            # Look for existing metric
            stmt = select(DBPlayCount).where(
                DBPlayCount.track_id == track_id,
                DBPlayCount.user_id == user_id,
                DBPlayCount.is_deleted == False,  # noqa: E712
            )

            result = await self.session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                # Update existing metric
                existing.play_count = play_count
                existing.user_play_count = user_play_count
                existing.last_updated = now
                self.session.add(existing)
            else:
                # Create new metric
                new_metric = DBPlayCount(
                    track_id=track_id,
                    user_id=user_id,
                    play_count=play_count,
                    user_play_count=user_play_count,
                    last_updated=now,
                )
                self.session.add(new_metric)

            updated_count += 1

        await self.session.flush()
        return updated_count

    @db_operation("save_connector_mappings")
    async def save_connector_mappings(
        self,
        mappings: list[tuple[int, str, str, int, str, dict]],
    ) -> int:
        """Save mappings for multiple tracks efficiently."""
        if not mappings:
            return 0

        now = datetime.now(UTC)
        updated_count = 0

        # Process each mapping
        for (
            track_id,
            connector_name,
            connector_track_id,
            confidence,
            match_method,
            metadata,
        ) in mappings:
            # Look for existing mapping
            stmt = select(DBTrackMapping).where(
                DBTrackMapping.track_id == track_id,
                DBTrackMapping.connector_name == connector_name,
                DBTrackMapping.is_deleted == False,  # noqa: E712
            )

            result = await self.session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                # Update existing mapping but PRESERVE match_method
                existing.connector_track_id = connector_track_id
                existing.confidence = confidence
                # DO NOT CHANGE match_method - preserve original value
                existing.connector_metadata = metadata
                existing.last_verified = now
                self.session.add(existing)

                # Flag as modified for SQLAlchemy to detect JSON changes
                flag_modified(existing, "connector_metadata")
            else:
                # Create new mapping with provided match_method
                new_mapping = DBTrackMapping(
                    track_id=track_id,
                    connector_name=connector_name,
                    connector_track_id=connector_track_id,
                    confidence=confidence,
                    match_method=match_method,
                    connector_metadata=metadata,
                    last_verified=now,
                )
                self.session.add(new_mapping)

            updated_count += 1

        await self.session.flush()
        return updated_count

    @db_operation("get_or_create")
    async def get_or_create(
        self,
        lookup_attrs: dict[str, Any],
        create_attrs: dict[str, Any] | None = None,
    ) -> tuple[Track, bool]:
        """Find a track by attributes or create it if it doesn't exist."""
        # Build query directly
        stmt = self.select()

        # Apply lookup conditions
        for field, value in lookup_attrs.items():
            if hasattr(self.model_class, field):
                stmt = stmt.where(getattr(self.model_class, field) == value)

        stmt = stmt.limit(1)

        # Execute query
        result = await self.session.scalars(stmt)
        db_track = result.first()

        if db_track:
            track = await self.mapper.to_domain(db_track)
            return track, False

        # Create a new track
        all_attrs = {**lookup_attrs}
        if create_attrs:
            all_attrs.update(create_attrs)

        # Process artist data
        artists = []
        for artist_data in all_attrs.get("artists", []):
            if isinstance(artist_data, str):
                artists.append(Artist(name=artist_data))
            elif isinstance(artist_data, Artist):
                artists.append(artist_data)
            elif isinstance(artist_data, dict) and "name" in artist_data:
                artists.append(Artist(name=artist_data["name"]))

        # Create track object
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

        # Create the DB track object
        db_track = self.mapper.to_db(track)

        # Add to session
        self.session.add(db_track)
        await self.session.flush()
        await self.session.refresh(db_track)

        created_track = track.with_id(db_track.id).with_connector_track_id(
            "db",
            str(db_track.id),
        )
        return created_track, True
