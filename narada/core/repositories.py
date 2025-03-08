"""Repository layer for database operations."""

from collections.abc import Callable
import datetime
from datetime import timedelta
from typing import Any, ClassVar, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from narada.config import get_logger
from narada.core.models import Artist, Playlist, Track
from narada.core.protocols import MappingTable, ModelClass
from narada.database.dbmodels import (
    DBPlayCount,
    DBPlaylist,
    DBPlaylistMapping,
    DBPlaylistTrack,
    DBTrack,
    DBTrackMapping,
    NaradaDBBase,
)

logger = get_logger(__name__)

T = TypeVar("T", bound=NaradaDBBase)
M = TypeVar("M", bound=MappingTable)


class BaseRepository[T]:
    """Base repository with common database operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        logger.debug("Initialized repository with session {}", id(session))

    def _select_active(self, *entities: type) -> Select:
        """Create select statement with active filters.

        Args:
            *entities: Database model classes to include in select

        Returns:
            Select statement with is_deleted=False filters
        """
        stmt = select(*entities)
        for entity in entities:
            stmt = stmt.where(entity.is_deleted == False)  # noqa: E712
        return stmt

    def _relationship_option(self, entity, relationship_path: str):
        """Create selectinload option for a relationship path with active filtering.

        Args:
            entity: The model class
            relationship_path: Dot-notation relationship path (e.g. "tracks.track")

        Returns:
            Properly configured selectinload option with active filters
        """
        parts = relationship_path.split(".")
        current_attr = getattr(entity, parts[0])

        # Create relationship loading option
        # Use selectinload and filter the underlying relationship in the query
        load_opt = selectinload(current_attr)

        # For nested relationships, apply recursively
        if len(parts) > 1:
            next_entity = current_attr.prop.entity.class_
            next_path = ".".join(parts[1:])
            load_opt = load_opt.options(
                self._relationship_option(next_entity, next_path),
            )

        return load_opt

    async def _execute_select(self, stmt: Select[Any], multi: bool = False) -> Any:
        """Execute SELECT statement with scalar result handling.

        Args:
            stmt: SELECT statement to execute
            multi: If True, returns list of results
        """
        try:
            # Execute the statement directly
            result = await self.session.execute(stmt)

            if multi:
                return result.scalars().all()
            else:
                return result.scalars().first()
        except SQLAlchemyError as e:
            logger.error(f"Database error in {self.__class__.__name__}: {e}")
            return [] if multi else None

    async def _execute_transaction(self, operation: Callable[[], Any]) -> Any:
        """Execute database transaction operation.

        Args:
            operation: Async callable that performs database operations

        Returns:
            Result of the operation

        Raises:
            SQLAlchemyError: If database operations fail
        """
        try:
            async with (
                self.session.begin_nested()
            ):  # Use savepoint for nested transactions
                result = await operation()
                # No need for explicit flush as commit will handle it
                return result
        except SQLAlchemyError as e:
            logger.exception(f"Database error in {self.__class__.__name__}: {e!s}")
            raise  # Let caller handle or propagate

    async def get_by_internal_id(
        self,
        model_class: type[ModelClass],
        id_: int,
        load_relationships: bool = False,
    ) -> T | None:
        """Get active record by ID with efficient loading.

        Args:
            model_class: Database model class to query
            id_: Primary key to look up
            load_relationships: If True, loads all relationships in one query

        Returns:
            Database model instance or None if not found
        """
        stmt = self._select_active(model_class).where(model_class.id == id_)

        if load_relationships:
            stmt = stmt.options(
                *[
                    selectinload(getattr(model_class, rel.key))
                    for rel in model_class.__mapper__.relationships
                ],
            )

        return await self._execute_select(stmt)

    async def get_by_connector_id(
        self,
        model_class: type[T],
        connector: str,
        connector_id: str,
        mapping_class: type[M],  # Use the more specific type variable
        relationships: list[str] | None = None,
    ) -> T | None:
        """Get record by connector ID using SQLAlchemy 2.0 patterns.

        Args:
            model_class: Main entity class (e.g., DBTrack)
            connector: Connector name (e.g., "spotify")
            connector_id: External ID to look up
            mapping_class: Mapping table class (e.g., DBTrackMapping)
            relationships: Optional relationships to eager load
        """
        # Build base query with join
        stmt = (
            self._select_active(model_class)
            .join(mapping_class)
            .where(
                mapping_class.connector_name == connector,
                mapping_class.connector_id == connector_id,
            )
        )

        # Add relationship loading if specified
        if relationships:
            stmt = stmt.options(
                *[selectinload(getattr(model_class, rel)) for rel in relationships],
            )

    async def find_by_attribute(
        self,
        model_class: type[ModelClass],  # Change from type[T] to type[ModelClass]
        attribute: str,
        value: Any,
        columns: list[str] | None = None,
        relationships: list[str] | None = None,
    ) -> T | None:
        """Find a record by a direct model attribute with selective loading.

        Use this method for simple, single-attribute queries on model properties.
        For complex queries with joins or multiple conditions, use get_by_connector_id.
        For primary key lookups, use get_by_internal_id.

        Args:
            model_class: Database model class to query
            attribute: Model attribute name to filter on
            value: Value to match against
            columns: Optional list of specific columns to load
            relationships: Optional list of relationships to eager load

        Returns:
            Database model instance or None if not found

        Example:
            # Find track by title
            track = await repo.find_by_attribute(
                DBTrack,
                "title",
                "My Song",
                relationships=["mappings"]
            )
        """
        if columns:
            stmt = select(*[getattr(model_class, col) for col in columns])
        else:
            stmt = select(model_class)

        stmt = stmt.where(
            getattr(model_class, attribute) == value,
            model_class.is_deleted == False,  # noqa: E712
        )

        if relationships:
            stmt = stmt.options(
                *[selectinload(getattr(model_class, rel)) for rel in relationships],
            )
        return await self._execute_select(stmt)


class TrackRepository(BaseRepository[DBTrack]):
    """Repository for track operations with efficient caching."""

    # ID type lookup definitions
    _TRACK_ID_TYPES: ClassVar[dict[str, Callable]] = {
        "internal": lambda self, id_value: self._get_by_internal(id_value),
        "spotify": lambda self, id_value: self._get_by_connector("spotify", id_value),
        "isrc": lambda self, id_value: self._get_by_attribute("isrc", id_value),
    }

    @staticmethod
    def _db_track_to_domain(db_track: DBTrack | None) -> Track | None:
        """Convert database track to domain model."""
        if not db_track:
            return None

        track = Track(
            id=db_track.id,
            title=db_track.title,
            artists=[Artist(name=name) for name in db_track.artists["names"]],
            album=db_track.album,
            duration_ms=db_track.duration_ms,
            release_date=db_track.release_date,
            isrc=db_track.isrc,
            connector_track_ids={
                m.connector_name: m.connector_id for m in db_track.mappings
            },
        )

        # Add connector metadata from mappings
        for mapping in db_track.mappings:
            if mapping.connector_metadata:
                track = track.with_connector_metadata(
                    mapping.connector_name,
                    mapping.connector_metadata,
                )

        return track

    @staticmethod
    def domain_track_to_db(track: Track) -> DBTrack:
        """Create database track model from domain model."""
        return DBTrack(
            title=track.title,
            artists={"names": [a.name for a in track.artists]},
            album=track.album,
            duration_ms=track.duration_ms,
            release_date=track.release_date,
            isrc=track.isrc,
            spotify_id=track.connector_track_ids.get("spotify"),
            musicbrainz_id=track.connector_track_ids.get("musicbrainz"),
            mappings=[
                DBTrackMapping(
                    connector_name=name,
                    connector_id=track_id,
                    match_method="source",
                    confidence=100,
                    connector_metadata=track.connector_metadata.get(name, {}),
                )
                for name, track_id in track.connector_track_ids.items()
            ],
        )

    async def get_track(self, id_type: str, id_value: str) -> Track | None:
        """Get track by any identifier type.

        Args:
            id_type: Identifier type ("internal", "spotify", "isrc", etc)
            id_value: Identifier value

        Returns:
            Track domain model if found, None otherwise

        Raises:
            ValueError: If unsupported ID type provided
        """
        # Look up the appropriate query method
        query_method = self._TRACK_ID_TYPES.get(id_type)
        if not query_method:
            raise ValueError(f"Unsupported track identifier type: {id_type}")

        # Execute the appropriate query method
        db_track = await query_method(self, id_value)
        return self._db_track_to_domain(db_track) if db_track else None

    async def _get_by_internal(self, id_value: str) -> DBTrack | None:
        """Get track by internal ID."""
        result = await self.get_by_internal_id(
            DBTrack,
            int(id_value),
            load_relationships=True,
        )
        return result if isinstance(result, DBTrack) else None

    async def _get_by_connector(self, connector: str, id_value: str) -> DBTrack | None:
        """Get track by connector ID."""
        return await self.get_by_connector_id(
            model_class=DBTrack,
            connector=connector,
            connector_id=id_value,
            mapping_class=DBTrackMapping,
            relationships=["mappings"],
        )

    async def _get_by_attribute(self, attribute: str, value: str) -> DBTrack | None:
        """Get track by direct attribute."""
        return await self.find_by_attribute(
            model_class=DBTrack,
            attribute=attribute,
            value=value,
            relationships=["mappings"],
        )

    async def get_connector_mappings(
        self,
        track_ids: list[int],
        connector: str | None = None,
    ) -> dict[int, dict[str, str]]:
        """Get mappings between tracks and external connectors.

        Args:
            track_ids: List of track IDs to fetch mappings for
            connector: Optional connector name to filter results

        Returns:
            Dictionary mapping {track_id: {connector_name: connector_id}}
        """
        if not track_ids:
            return {}

        try:
            from narada.database.database import get_session

            # Use a fresh session to avoid transaction issues
            async with get_session() as session:
                # Build the base query within the session's transaction
                stmt = select(
                    DBTrackMapping.track_id,
                    DBTrackMapping.connector_name,
                    DBTrackMapping.connector_id,
                ).where(
                    DBTrackMapping.track_id.in_(track_ids),
                    DBTrackMapping.is_deleted == False,  # noqa: E712
                )

                # Add connector filter if specified
                if connector:
                    stmt = stmt.where(DBTrackMapping.connector_name == connector)

                # Execute the query
                results = await session.execute(stmt)

                # Process the results while still in the transaction
                mappings = {}
                for track_id, connector_name, connector_id in results:
                    if track_id not in mappings:
                        mappings[track_id] = {}
                    mappings[track_id][connector_name] = connector_id

                return mappings

        except Exception as e:
            logger.error(f"Error fetching connector mappings: {e}")
            return {}

    async def get_track_metrics(
        self,
        track_ids: list[int],
        metric_type: str = "play_count",
        max_age_hours: int = 24,
    ) -> dict[int, int]:
        """Get cached metrics with TTL awareness.

        Args:
            track_ids: List of track IDs to fetch metrics for
            metric_type: Type of metric to fetch (default: play_count)
            max_age_hours: Maximum age of metrics in hours

        Returns:
            Dictionary mapping {track_id: metric_value}
        """
        if not track_ids:
            return {}

        try:
            # Calculate cutoff timestamp for TTL
            cutoff = func.now() - timedelta(hours=max_age_hours)

            # Build query directly - no need for separate transaction
            stmt = select(DBPlayCount.track_id, DBPlayCount.play_count).where(
                DBPlayCount.track_id.in_(track_ids),
                DBPlayCount.last_updated >= cutoff,
                DBPlayCount.is_deleted == False,  # noqa: E712
            )

            # Execute the query directly in the current transaction
            results = await self.session.execute(stmt)

            # Process results within the current transaction context
            metrics_dict = {track_id: play_count for track_id, play_count in results}  # noqa: C416

            logger.debug(
                f"Retrieved {len(metrics_dict)}/{len(track_ids)} track metrics",
                metric_type=metric_type,
                max_age_hours=max_age_hours,
            )

            return metrics_dict

        except Exception as e:
            logger.error(f"Error fetching track metrics: {e}")
            return {}

    async def get_track_mapping_details(
        self,
        track_id: int,
        connector_name: str,
    ) -> DBTrackMapping | None:
        """Get detailed mapping information between a track and connector."""
        if not track_id:
            logger.warning("Cannot get mapping details: No track ID provided")
            return None

        try:
            # Create a new session for this operation to avoid concurrent session issues
            from narada.database.database import get_session

            # Use a dedicated session instead of self.session
            async with get_session() as session:
                stmt = select(DBTrackMapping).where(
                    DBTrackMapping.track_id == track_id,
                    DBTrackMapping.connector_name == connector_name,
                    DBTrackMapping.is_deleted == False,  # noqa: E712
                )

                result = await session.execute(stmt)
                return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error retrieving mapping details: {e}")
            return None

    async def save_connector_mappings(
        self,
        mappings: list[tuple[int, str, str, int, str, dict]],
    ) -> None:
        """Save mappings for multiple tracks efficiently.

        Args:
            mappings: List of tuples with mapping data:
                (track_id, connector_name, connector_id, confidence, match_method, metadata)
        """
        if not mappings:
            return

        try:
            # Process each mapping within the existing transaction
            for (
                track_id,
                connector_name,
                connector_id,
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

                # Execute directly in the current transaction
                result = await self.session.execute(stmt)
                existing = result.scalar_one_or_none()

                if existing:
                    # Update existing mapping but PRESERVE match_method
                    existing.connector_id = connector_id
                    existing.confidence = confidence
                    # DO NOT CHANGE match_method - preserve original value
                    existing.connector_metadata = metadata
                    existing.last_verified = func.now()
                else:
                    # Create new mapping with provided match_method
                    new_mapping = DBTrackMapping(
                        track_id=track_id,
                        connector_name=connector_name,
                        connector_id=connector_id,
                        confidence=confidence,
                        match_method=match_method,
                        connector_metadata=metadata,
                        last_verified=func.now(),
                    )
                    self.session.add(new_mapping)

                # Flush changes without committing
                await self.session.flush()

            logger.debug(f"Saved {len(mappings)} connector mappings")

        except Exception as e:
            logger.error(f"Error saving connector mappings: {e}")
            raise

    async def save_track_metrics(
        self,
        metrics: list[tuple[int, str, str, int, int]],
    ) -> None:
        """Save metrics for multiple tracks efficiently.

        Args:
            metrics: List of tuples with metric data:
                (track_id, user_id, metric_type, play_count, user_play_count)
        """
        if not metrics:
            return

        try:
            # Process each metric
            for track_id, user_id, _, play_count, user_play_count in metrics:
                # Look for existing metric
                stmt = select(DBPlayCount).where(
                    DBPlayCount.track_id == track_id,
                    DBPlayCount.user_id == user_id,
                    DBPlayCount.is_deleted == False,  # noqa: E712
                )

                # Execute within existing transaction
                result = await self.session.execute(stmt)
                existing = result.scalar_one_or_none()

                if existing:
                    # Update existing metric
                    existing.play_count = play_count
                    existing.user_play_count = user_play_count
                    existing.last_updated = func.now()
                else:
                    # Create new metric
                    new_metric = DBPlayCount(
                        track_id=track_id,
                        user_id=user_id,
                        play_count=play_count,
                        user_play_count=user_play_count,
                        last_updated=func.now(),
                    )
                    self.session.add(new_metric)

            # Flush changes to database but don't commit (let outer transaction handle it)
            await self.session.flush()

        except Exception as e:
            logger.error(f"Error saving track metrics: {e}")
            raise

    async def save_track(self, track: Track) -> Track:
        """Save track and mappings efficiently."""
        if not track.title or not track.artists:
            raise ValueError("Track must have title and artists")

        # Try to find existing track
        stmt = (
            self._select_active(DBTrack)
            .options(selectinload(DBTrack.mappings))
            .where(
                DBTrack.isrc == track.isrc
                if track.isrc
                else DBTrack.spotify_id == track.connector_track_ids.get("spotify"),
            )
        )

        if existing := await self._execute_select(stmt):
            # We found an existing track - merge connector metadata
            updated_track = Track(
                id=existing.id,  # Set the actual ID field here
                title=track.title,
                artists=track.artists,
                album=track.album,
                duration_ms=track.duration_ms,
                release_date=track.release_date,
                isrc=track.isrc,
                play_count=track.play_count,
                connector_track_ids={
                    **track.connector_track_ids,
                    "db": str(existing.id),
                },
                connector_metadata=track.connector_metadata.copy(),
            )

            # Check if we need to update core track attributes
            track_updated = False

            # Update release_date if the existing record is missing it but new data has it
            if not existing.release_date and track.release_date:
                existing.release_date = track.release_date
                track_updated = True
                logger.debug(f"Added missing release_date for track {existing.id}")

            # Add additional core attributes updates here if needed
            # For example, if duration_ms is missing...
            if existing.duration_ms is None and track.duration_ms:
                existing.duration_ms = track.duration_ms
                track_updated = True

            # If any core attributes were updated, save the track
            if track_updated:
                self.session.add(existing)
                await self.session.flush()

            # Update mappings for all connectors
            now = datetime.datetime.now(datetime.UTC)
            for mapping in existing.mappings:
                connector = mapping.connector_name

                # Check if new metadata is available for this connector
                if connector in track.connector_metadata:
                    should_update = False
                    incoming_metadata = track.connector_metadata[connector]

                    # Always update if mapping data is missing
                    if not mapping.connector_metadata:
                        should_update = True
                    # For all connectors, check if metadata is different
                    else:
                        # Detect if any values in the incoming metadata differ from what we have stored
                        for key, value in incoming_metadata.items():
                            existing_value = mapping.connector_metadata.get(key)

                            # Simple consistent comparison for all field types
                            if existing_value != value:
                                logger.debug(
                                    f"Updating {connector} metadata for track {existing.id}, value changed for {key} "
                                    f"(was: {type(existing_value).__name__}:{existing_value}, "
                                    f"now: {type(value).__name__}:{value})",
                                )
                                should_update = True
                                break

                    # If we should update, do it
                    if should_update:
                        # Ensure mapping has connector_metadata
                        if mapping.connector_metadata is None:
                            mapping.connector_metadata = {}

                        # Create a new dictionary instead of updating in-place
                        mapping.connector_metadata = {
                            **mapping.connector_metadata,
                            **incoming_metadata,
                        }

                        # Update verification timestamp
                        mapping.last_verified = now
                        self.session.add(mapping)

                        # Explicitly flag the attribute as modified for SQLAlchemy
                        from sqlalchemy.orm.attributes import flag_modified

                        flag_modified(mapping, "connector_metadata")

                        await self.session.flush()

            return updated_track

        # Create new track within transaction
        db_track = self.domain_track_to_db(track)

        async def save_transaction():
            self.session.add(db_track)
            await self.session.flush()
            return db_track

        saved_track = await self._execute_transaction(save_transaction)
        return track.with_connector_track_id("db", str(saved_track.id))


class PlaylistRepository(BaseRepository[DBPlaylist]):
    """Repository for playlist operations with efficient caching."""

    async def get_playlist(self, id_type: str, id_value: str) -> Playlist | None:
        """Get playlist by any identifier type.

        Args:
            id_type: Type of identifier ("internal", "spotify", etc)
            id_value: Identifier value

        Returns:
            Domain Playlist model or None if not found
        """
        # Internal IDs use direct lookup
        if id_type == "internal":
            stmt = self._select_active(DBPlaylist).where(DBPlaylist.id == int(id_value))
        # All other IDs use connector mapping
        else:
            stmt = (
                self._select_active(DBPlaylist)
                .join(DBPlaylistMapping)
                .where(
                    DBPlaylistMapping.connector_name == id_type,
                    DBPlaylistMapping.connector_id == id_value,
                )
            )

        # Load relationships with active filters applied
        relationship_paths = ["mappings", "tracks.track", "tracks.track.mappings"]

        # Add options for each relationship path
        for path in relationship_paths:
            stmt = stmt.options(self._relationship_option(DBPlaylist, path))

        db_playlist = await self._execute_select(stmt)
        return self._convert_db_playlist(db_playlist) if db_playlist else None

    async def save_playlist(self, playlist: Playlist) -> str:
        """Save playlist and all its tracks to the database.

        This method ensures all tracks have database IDs before creating the playlist
        relationships. Tracks without IDs are automatically saved to the database first,
        preserving the original playlist order.

        Args:
            playlist: The Playlist domain model to save

        Returns:
            String ID of the saved playlist

        Raises:
            SQLAlchemyError: If database operations fail
        """

        async def save_playlist_operation() -> str:
            # First ensure all tracks have IDs by saving any that don't
            track_repo = TrackRepository(self.session)
            updated_tracks = []

            for track in playlist.tracks:
                if not track.id:
                    # Save track to get an ID assigned
                    saved_track = await track_repo.save_track(track)
                    updated_tracks.append(saved_track)
                else:
                    # Keep existing track as is
                    updated_tracks.append(track)

            # Create DB playlist with updated tracks list (all tracks now have IDs)
            db_playlist = DBPlaylist(
                name=playlist.name,
                description=playlist.description,
            )

            # Add mappings for external IDs
            for connector, external_id in playlist.connector_track_ids.items():
                db_playlist.mappings.append(
                    DBPlaylistMapping(
                        connector_name=connector,
                        connector_id=external_id,
                    ),
                )

            # Add to session to get ID
            self.session.add(db_playlist)
            await self.session.flush()

            # Create playlist tracks with current timestamp
            current_time = datetime.datetime.now(datetime.UTC)
            playlist_tracks = []

            for i, track in enumerate(updated_tracks):
                playlist_tracks.append(
                    DBPlaylistTrack(
                        playlist_id=db_playlist.id,
                        track_id=track.id,
                        sort_key=self._generate_sort_key(i),
                        created_at=current_time,
                        updated_at=current_time,
                    ),
                )

            # Add all playlist tracks at once
            if playlist_tracks:
                self.session.add_all(playlist_tracks)

            # Update track count
            db_playlist.track_count = len(playlist_tracks)

            return str(db_playlist.id)

        # Use base repository transaction management
        return await self._execute_transaction(save_playlist_operation)

    async def update_playlist(
        self,
        playlist_id: str,
        playlist: Playlist,
        track_repo: TrackRepository,
    ) -> None:
        """Update existing playlist with new tracks and order."""

        async def update_playlist_operation() -> None:
            # Find existing playlist and eagerly load tracks
            stmt = (
                select(DBPlaylist)
                .options(selectinload(DBPlaylist.tracks))
                .where(DBPlaylist.id == int(playlist_id))
            )
            result = await self.session.execute(stmt)
            db_playlist = result.scalars().first()

            if not db_playlist:
                raise ValueError(f"Playlist with ID {playlist_id} not found")

            # Update playlist metadata
            db_playlist.track_count = len(playlist.tracks)

            # Important: Convert lazy-loadable relationship to a list to avoid
            # lazy loading issues when we iterate through it
            existing_tracks = list(db_playlist.tracks)

            # Soft delete existing tracks
            for pt in existing_tracks:
                pt.is_deleted = True
                pt.deleted_at = func.now()

            # Save new tracks and create new playlist-track relationships
            for idx, track in enumerate(playlist.tracks):
                # Save track if it doesn't exist yet
                saved_track = await track_repo.save_track(track)
                track_id = int(saved_track.connector_track_ids["db"])

                # Create new playlist-track relationship with proper sort key
                playlist_track = DBPlaylistTrack(
                    playlist_id=db_playlist.id,
                    track_id=track_id,
                    sort_key=self._generate_sort_key(idx),
                )
                self.session.add(playlist_track)

        # Use base repository transaction management
        await self._execute_transaction(update_playlist_operation)

    def _convert_db_playlist(self, db_playlist: DBPlaylist) -> Playlist:
        """Convert database playlist to domain model."""
        active_tracks = [pt for pt in db_playlist.tracks if not pt.is_deleted]
        sorted_tracks = sorted(active_tracks, key=lambda pt: pt.sort_key)
        domain_tracks = [
            Track(
                id=pt.track.id,
                title=pt.track.title,
                artists=[Artist(name=name) for name in pt.track.artists["names"]],
                album=pt.track.album,
                duration_ms=pt.track.duration_ms,
                connector_track_ids={
                    m.connector_name: m.connector_id for m in pt.track.mappings
                },
            )
            for pt in sorted_tracks
        ]

        return Playlist(
            id=db_playlist.id,
            name=db_playlist.name,
            description=db_playlist.description,
            tracks=domain_tracks,
            connector_track_ids={
                m.connector_name: m.connector_id for m in db_playlist.mappings
            },
        )

    @staticmethod
    def _generate_sort_key(position: int) -> str:
        """Generate lexicographically sortable key."""
        return f"a{position:08d}"
