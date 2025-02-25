"""Repository layer for database operations."""

from collections.abc import Callable
from typing import Any, Generic, Type, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from narada.config import get_logger
from narada.core.models import Artist, Playlist, Track
from narada.data.database import (
    DBPlaylist,
    DBPlaylistMapping,
    DBPlaylistTrack,
    DBTrack,
    DBTrackMapping,
    NaradaDBBase,
)

T = TypeVar("T", bound=NaradaDBBase)

logger = get_logger(__name__)


class BaseRepository(Generic[T]):
    """Base repository with common database operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        logger.debug("Initialized repository with session {}", id(session))

    def _select_active(self, *entities: type[NaradaDBBase]) -> Select:
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
                self._relationship_option(next_entity, next_path)
            )

        return load_opt

    async def _execute_select(self, stmt: Select[Any], multi: bool = False) -> Any:
        """Execute SELECT statement with scalar result handling.

        Args:
            stmt: SELECT statement to execute
            multi: If True, returns list of results
        """
        try:
            result = await (
                self.session.scalars(stmt) if multi else self.session.scalar(stmt)
            )
            return list(result.unique()) if multi and result else result

        except SQLAlchemyError as e:
            logger.exception(f"Database error in {self.__class__.__name__}: {str(e)}")
            raise

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
            result = await operation()
            await self.session.flush()
            return result

        except SQLAlchemyError as e:
            logger.exception(f"Database error in {self.__class__.__name__}: {str(e)}")
            raise

    async def get_by_internal_id(
        self,
        model_class: Type[T],
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
                ]
            )

        return await self._execute_select(stmt)

    async def get_by_connector_id(
        self,
        model_class: Type[T],
        connector: str,
        connector_id: str,
        mapping_class: type[NaradaDBBase],
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
                # Use the class attributes properly
                getattr(mapping_class, "connector_name") == connector,
                getattr(mapping_class, "connector_id") == connector_id,
            )
        )

        # Add relationship loading if specified
        if relationships:
            stmt = stmt.options(
                *[selectinload(getattr(model_class, rel)) for rel in relationships]
            )

        return await self._execute_select(stmt)

    async def find_by_attribute(
        self,
        model_class: Type[T],
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
                *[selectinload(getattr(model_class, rel)) for rel in relationships]
            )
        return await self._execute_select(stmt)


class TrackRepository(BaseRepository):
    """Repository for track operations with efficient caching."""

    # ID type lookup definitions
    _TRACK_ID_TYPES = {
        "internal": lambda self, id_value: self._get_by_internal(id_value),
        "spotify": lambda self, id_value: self._get_by_connector("spotify", id_value),
        "isrc": lambda self, id_value: self._get_by_attribute("isrc", id_value),
    }

    @staticmethod
    def _db_track_to_domain(db_track: DBTrack | None) -> Track | None:
        """Convert database track to domain model."""
        if not db_track:
            return None

        return Track(
            id=db_track.id,
            title=db_track.title,
            artists=[Artist(name=name) for name in db_track.artists["names"]],
            album=db_track.album,
            duration_ms=db_track.duration_ms,
            connector_track_ids={
                m.connector_name: m.connector_id for m in db_track.mappings
            },
        )

    @staticmethod
    def domain_track_to_db(track: Track) -> DBTrack:
        """Create database track model from domain model."""
        return DBTrack(
            title=track.title,
            artists={"names": [a.name for a in track.artists]},
            album=track.album,
            duration_ms=track.duration_ms,
            isrc=track.isrc,
            spotify_id=track.connector_track_ids.get("spotify"),
            mappings=[
                DBTrackMapping(
                    connector_name=name,
                    connector_id=track_id,
                    match_method="direct",
                    confidence=100,
                    connector_metadata={},
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
            DBTrack, int(id_value), load_relationships=True
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

    async def save_track(self, track: Track) -> Track:
        """Save track and mappings efficiently.

        Args:
            track: Domain track model to save

        Returns:
            Track: Updated domain track with database ID

        Raises:
            ValueError: If track validation fails
        """
        if not track.title or not track.artists:
            raise ValueError("Track must have title and artists")

        # Try to find existing track
        stmt = (
            self._select_active(DBTrack)
            .options(selectinload(DBTrack.mappings))
            .where(
                DBTrack.isrc == track.isrc
                if track.isrc
                else DBTrack.spotify_id == track.connector_track_ids.get("spotify")
            )
        )

        if existing := await self._execute_select(stmt):
            # Return existing track with updated ID
            return track.with_connector_track_id("db", str(existing.id))

        # Create new track within transaction
        db_track = self.domain_track_to_db(track)

        async def save_transaction():
            self.session.add(db_track)
            await self.session.flush()
            return db_track

        saved_track = await self._execute_transaction(save_transaction)
        return track.with_connector_track_id("db", str(saved_track.id))

    async def get_playlists_for_track(self, track_id: int) -> list[Playlist]:
        """Get all playlists containing a track."""
        stmt = (
            self._select_active(DBPlaylist)
            .join(DBPlaylistTrack)
            .options(selectinload(DBPlaylist.mappings))
            .where(DBPlaylistTrack.track_id == track_id)
        )

        result = await self._execute_select(stmt, multi=True)
        return [
            Playlist(
                id=p.id,
                name=p.name,
                description=p.description,
                tracks=[],  # Skip loading tracks for efficiency
                connector_track_ids={
                    m.connector_name: m.connector_id for m in p.mappings
                },
            )
            for p in result
        ]


class PlaylistRepository(BaseRepository):
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

    async def save_playlist(
        self, playlist: Playlist, track_repo: TrackRepository
    ) -> str:
        """Save playlist with efficient batch operations.

        Args:
            playlist: Domain playlist to save
            track_repo: Repository for saving tracks

        Returns:
            str: Internal playlist ID
        """

        async def save_playlist_operation() -> str:
            # Create playlist record
            db_playlist = DBPlaylist(
                name=playlist.name,
                description=playlist.description,
                track_count=len(playlist.tracks),
            )
            self.session.add(db_playlist)
            await self.session.flush()

            # Add connector mappings
            for connector, connector_id in playlist.connector_track_ids.items():
                self.session.add(
                    DBPlaylistMapping(
                        playlist_id=db_playlist.id,
                        connector_name=connector,
                        connector_id=connector_id,
                    )
                )

            # Save tracks and create playlist associations
            for idx, track in enumerate(playlist.tracks):
                # Save track first to ensure it exists
                saved_track = await track_repo.save_track(track)
                track_id = int(saved_track.connector_track_ids["db"])

                # Create playlist track mapping with sort key
                self.session.add(
                    DBPlaylistTrack(
                        playlist_id=db_playlist.id,
                        track_id=track_id,
                        sort_key=self._generate_sort_key(idx),
                    )
                )

            await self.session.flush()
            return str(db_playlist.id)

        # Use base repository transaction management
        return await self._execute_transaction(save_playlist_operation)

    async def update_playlist(
        self, playlist_id: str, playlist: Playlist, track_repo: TrackRepository
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
