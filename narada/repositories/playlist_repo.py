"""Playlist repository implementation for database operations."""

from datetime import UTC, datetime
from typing import Any, ClassVar

from attrs import define
from sqlalchemy import Select, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from narada.config import get_logger
from narada.core.models import Artist, Playlist, Track, ensure_utc
from narada.database.db_models import (
    DBPlaylist,
    DBPlaylistMapping,
    DBPlaylistTrack,
    DBTrack,
    DBTrackMapping,
)
from narada.repositories.base_repo import BaseModelMapper, BaseRepository
from narada.repositories.repo_decorator import db_operation
from narada.repositories.track import TrackRepositories

logger = get_logger(__name__)


@define(frozen=True, slots=True)
class PlaylistMapper(BaseModelMapper[DBPlaylist, Playlist]):
    """Bidirectional mapper between domain and persistence models."""

    @staticmethod
    def get_default_relationships() -> list[str]:
        """Get default relationships to load for this model."""
        return ["mappings", "tracks"]

    @staticmethod
    async def to_domain(db_model: DBPlaylist) -> Playlist:
        """Convert persistence model to domain entity using a consistent async-safe approach."""
        if not db_model:
            return None

        # Process tracks - consistently use awaitable_attrs pattern
        domain_tracks = []

        # Get playlist tracks using awaitable_attrs
        playlist_tracks = []
        try:
            if hasattr(db_model, "awaitable_attrs"):
                playlist_tracks = await db_model.awaitable_attrs.tracks
            elif hasattr(db_model, "tracks"):
                playlist_tracks = db_model.tracks or []
        except Exception as e:
            logger.debug(f"Error getting playlist tracks: {e}")
            playlist_tracks = []

        # Filter and sort active tracks
        active_tracks = sorted(
            [pt for pt in playlist_tracks if not pt.is_deleted],
            key=lambda pt: pt.sort_key if hasattr(pt, "sort_key") else 0,
        )

        # Process each playlist track
        for pt in active_tracks:
            # Get track consistently using awaitable_attrs
            track = None
            try:
                if hasattr(pt, "awaitable_attrs"):
                    track = await pt.awaitable_attrs.track
                elif hasattr(pt, "track"):
                    track = pt.track
            except Exception:
                track = None

            if not track:
                continue

            # Get track mappings using awaitable_attrs consistently
            track_mappings = []
            try:
                if hasattr(track, "awaitable_attrs"):
                    track_mappings = await track.awaitable_attrs.mappings
                elif hasattr(track, "mappings"):
                    track_mappings = track.mappings or []
            except Exception:
                track_mappings = []

            # Build connector_track_ids from mappings
            connector_track_ids = {}

            # Process non-deleted track mappings efficiently
            for m in [m for m in track_mappings if not m.is_deleted]:
                # Get connector_track using awaitable_attrs consistently
                connector_track = None
                try:
                    if hasattr(m, "awaitable_attrs"):
                        connector_track = await m.awaitable_attrs.connector_track
                    elif hasattr(m, "connector_track"):
                        connector_track = m.connector_track
                except Exception:
                    connector_track = None

                if connector_track and not connector_track.is_deleted:
                    connector_track_ids[connector_track.connector_name] = (
                        connector_track.connector_track_id
                    )

            # Create the track domain object
            domain_tracks.append(
                Track(
                    id=track.id,
                    title=track.title,
                    artists=[Artist(name=name) for name in track.artists["names"]],
                    album=track.album,
                    duration_ms=track.duration_ms,
                    release_date=ensure_utc(track.release_date),
                    isrc=track.isrc,
                    connector_track_ids=connector_track_ids,
                ),
            )

        # Get playlist mappings using awaitable_attrs consistently
        connector_playlist_ids = {}
        playlist_mappings = []

        try:
            if hasattr(db_model, "awaitable_attrs"):
                playlist_mappings = await db_model.awaitable_attrs.mappings
            elif hasattr(db_model, "mappings"):
                playlist_mappings = db_model.mappings or []
        except Exception:
            playlist_mappings = []

        # Process non-deleted playlist mappings efficiently
        for m in [m for m in playlist_mappings if not m.is_deleted]:
            connector_playlist_ids[m.connector_name] = m.connector_playlist_id

        return Playlist(
            id=db_model.id,
            name=db_model.name,
            description=db_model.description,
            tracks=domain_tracks,
            connector_playlist_ids=connector_playlist_ids,
        )

    @staticmethod
    def to_db(domain_model: Playlist) -> DBPlaylist:
        """Convert domain entity to persistence values."""
        playlist = DBPlaylist()
        playlist.name = domain_model.name
        playlist.description = domain_model.description
        playlist.track_count = len(domain_model.tracks) if domain_model.tracks else 0
        return playlist


class PlaylistRepository(BaseRepository[DBPlaylist, Playlist]):
    """Repository for playlist operations with SQLAlchemy 2.0 best practices."""

    # Extended relationship mapping for automatic loading
    _RELATIONSHIP_PATHS: ClassVar[dict[str, list[str]]] = {
        "full": [
            "mappings",
            "tracks.track.mappings.connector_track",
        ],
    }

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with session and mapper."""
        super().__init__(
            session=session,
            model_class=DBPlaylist,
            mapper=PlaylistMapper(),
        )
        # Initialize track repositories for reuse
        self.track_repos = TrackRepositories(session)

    # -------------------------------------------------------------------------
    # ENHANCED QUERY METHODS
    # -------------------------------------------------------------------------

    def select_with_relations(self) -> Select:
        """Create select statement with standard relations loaded."""
        return self.with_playlist_relationships(self.select())

    def select_by_connector(self, connector: str, connector_id: str) -> Select:
        """Build a query to fetch playlist by connector ID."""
        return (
            self.select()
            .join(DBPlaylistMapping)
            .where(
                DBPlaylistMapping.connector_name == connector,
                DBPlaylistMapping.connector_playlist_id == connector_id,
                DBPlaylistMapping.is_deleted == False,  # noqa: E712
            )
        )

    def with_playlist_relationships(
        self,
        stmt: Select[tuple[DBPlaylist]],
    ) -> Select[tuple[DBPlaylist]]:
        """Add standard playlist relationship loading."""
        return stmt.options(
            selectinload(self.model_class.mappings),
            selectinload(self.model_class.tracks)
            .selectinload(DBPlaylistTrack.track)
            .selectinload(DBTrack.mappings)
            .selectinload(DBTrackMapping.connector_track),
        )

    # -------------------------------------------------------------------------
    # HELPER METHODS (non-decorated)
    # -------------------------------------------------------------------------

    async def _save_new_tracks(
        self,
        tracks: list[Track],
        connector: str | None = None,
    ) -> list[Track]:
        """Save tracks that don't have IDs yet and return updated tracks."""
        if not tracks:
            return []

        updated_tracks = []
        for track in tracks:
            if not track.id:
                try:
                    if connector and connector in track.connector_track_ids:
                        # Use connector-first approach for tracks with connector data
                        connector_id = track.connector_track_ids[connector]
                        metadata = (
                            track.connector_metadata.get(connector, {})
                            if hasattr(track, "connector_metadata")
                            else {}
                        )

                        # Use the new ingest method that handles all aspects of track creation
                        saved_track = (
                            await self.track_repos.connector.ingest_external_track(
                                connector=connector,
                                connector_id=connector_id,
                                metadata=metadata,
                                title=track.title,
                                artists=[a.name for a in track.artists]
                                if track.artists
                                else [],
                                album=track.album,
                                duration_ms=track.duration_ms,
                                release_date=track.release_date,
                                isrc=track.isrc,
                            )
                        )
                        updated_tracks.append(saved_track)
                    else:
                        # For tracks without connector data, just save directly
                        saved_track = await self.track_repos.core.save_track(track)
                        updated_tracks.append(saved_track)
                except Exception as e:
                    # Use proper exception chaining
                    raise ValueError(f"Failed to save track: {e}") from e
            else:
                updated_tracks.append(track)

        return updated_tracks

    async def _create_playlist_tracks(
        self,
        playlist_id: int,
        tracks: list[Track],
    ) -> None:
        """Create playlist track associations."""
        if not tracks:
            return

        # Bulk insert tracks with sort keys
        values = [
            {
                "playlist_id": playlist_id,
                "track_id": track.id,
                "sort_key": self._generate_sort_key(idx),
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
            for idx, track in enumerate(tracks)
            if track.id is not None
        ]

        if values:
            await self.session.execute(insert(DBPlaylistTrack).values(values))
            await self.session.flush()

    async def _create_playlist_mappings(
        self,
        playlist_id: int,
        connector_ids: dict[str, str],
    ) -> None:
        """Create playlist connector mappings in batch."""
        if not connector_ids:
            return

        values = [
            {
                "playlist_id": playlist_id,
                "connector_name": connector,
                "connector_playlist_id": external_id,
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
            for connector, external_id in connector_ids.items()
        ]

        if values:
            await self.session.execute(insert(DBPlaylistMapping).values(values))
            await self.session.flush()

    async def _update_playlist_tracks(
        self,
        playlist_id: int,
        tracks: list[Track],
    ) -> None:
        """Update playlist tracks with optimized database operations."""
        if not tracks:
            return

        # Step 1: Get existing playlist tracks
        stmt = select(DBPlaylistTrack).where(
            DBPlaylistTrack.playlist_id == playlist_id,
            DBPlaylistTrack.is_deleted == False,  # noqa: E712
        )
        result = await self.session.scalars(stmt)
        existing_tracks = {pt.track_id: pt for pt in result.all()}

        # Step 2: Process current track list
        current_track_ids = set()
        now = datetime.now(UTC)
        updates = []
        new_tracks = []

        for idx, track in enumerate(tracks):
            if not track.id:
                continue

            current_track_ids.add(track.id)
            sort_key = self._generate_sort_key(idx)

            if track.id in existing_tracks:
                # Update existing track's position
                pt = existing_tracks[track.id]
                # Safe attribute access to avoid lazy loading
                current_sort_key = getattr(pt, "sort_key", None)
                if current_sort_key != sort_key:
                    updates.append((pt.id, sort_key))
            else:
                # Add new track to playlist
                new_tracks.append({
                    "playlist_id": playlist_id,
                    "track_id": track.id,
                    "sort_key": sort_key,
                    "created_at": now,
                    "updated_at": now,
                })

        # Step 3: Execute database operations in batch

        # Handle updates
        if updates:
            for pt_id, sort_key in updates:
                await self.session.execute(
                    update(DBPlaylistTrack)
                    .where(DBPlaylistTrack.id == pt_id)
                    .values(sort_key=sort_key, updated_at=now),
                )

        # Handle inserts
        if new_tracks:
            await self.session.execute(insert(DBPlaylistTrack).values(new_tracks))

        # Handle removals - soft delete tracks no longer in the playlist
        tracks_to_remove = set(existing_tracks.keys()) - current_track_ids
        if tracks_to_remove:
            await self.session.execute(
                update(DBPlaylistTrack)
                .where(
                    DBPlaylistTrack.playlist_id == playlist_id,
                    DBPlaylistTrack.track_id.in_(tracks_to_remove),
                    DBPlaylistTrack.is_deleted == False,  # noqa: E712
                )
                .values(is_deleted=True, deleted_at=now),
            )

        await self.session.flush()

    async def _update_connector_mappings(
        self,
        playlist_id: int,
        connector_ids: dict[str, str],
    ) -> None:
        """Update connector mappings with minimal database operations."""
        if not connector_ids:
            return

        # Get existing mappings
        stmt = select(DBPlaylistMapping).where(
            DBPlaylistMapping.playlist_id == playlist_id,
            DBPlaylistMapping.is_deleted == False,  # noqa: E712
        )
        result = await self.session.scalars(stmt)
        existing = {m.connector_name: m for m in result.all()}

        now = datetime.now(UTC)

        # Process batch of mappings
        new_mappings = []
        update_mappings = []

        # Identify new and updated mappings
        for connector, connector_id in connector_ids.items():
            if connector in existing:
                # Track updates
                mapping = existing[connector]
                if mapping.connector_playlist_id != connector_id:
                    mapping.connector_playlist_id = connector_id
                    mapping.updated_at = now
                    update_mappings.append(mapping)
            else:
                # Track new mappings for bulk insert
                new_mappings.append({
                    "playlist_id": playlist_id,
                    "connector_name": connector,
                    "connector_playlist_id": connector_id,
                    "created_at": now,
                    "updated_at": now,
                })

        # Bulk add updates
        if update_mappings:
            self.session.add_all(update_mappings)

        # Bulk add new mappings
        if new_mappings:
            await self.session.execute(insert(DBPlaylistMapping).values(new_mappings))

        await self.session.flush()

    # -------------------------------------------------------------------------
    # UTILITY METHODS
    # -------------------------------------------------------------------------

    @staticmethod
    def _generate_sort_key(position: int) -> str:
        """Generate lexicographically sortable key."""
        return f"a{position:08d}"

    # -------------------------------------------------------------------------
    # PUBLIC API METHODS (decorated)
    # -------------------------------------------------------------------------

    @db_operation("get_playlist_by_id")
    async def get_playlist_by_id(
        self,
        playlist_id: int,
    ) -> Playlist:
        """Get playlist by internal ID with all relationships."""
        stmt = self.select_by_id(playlist_id)
        stmt = self.with_playlist_relationships(stmt)

        # Execute query using the base repository method
        db_model = await self.execute_select_one(stmt)

        if not db_model:
            raise ValueError(f"Playlist with ID {playlist_id} not found")

        # Convert to domain model
        return await self.mapper.to_domain(db_model)

    @db_operation("get_playlist_by_connector")
    async def get_playlist_by_connector(
        self,
        connector: str,
        connector_id: str,
        raise_if_not_found: bool = True,
    ) -> Playlist | None:
        """Get a playlist by its connector ID."""
        # Use the enhanced select method
        stmt = self.select_by_connector(connector, connector_id)

        # Add eager loading with our helper
        stmt = self.with_playlist_relationships(stmt)

        # Execute query using base repository method
        db_model = await self.execute_select_one(stmt)

        if not db_model:
            if raise_if_not_found:
                raise ValueError(f"Playlist for {connector}:{connector_id} not found")
            return None

        # Convert to domain model
        return await self.mapper.to_domain(db_model)

    @db_operation("save_playlist")
    async def save_playlist(
        self,
        playlist: Playlist,
    ) -> Playlist:
        """Save playlist and all its tracks atomically."""
        if not playlist.name:
            raise ValueError("Playlist must have a name")

        # Execute in a transaction using base repository's helper
        return await self.execute_transaction(
            lambda: self._save_playlist_impl(playlist)
        )

    async def _save_playlist_impl(self, playlist: Playlist) -> Playlist:
        """Implementation to create a new playlist with tracks."""
        # Determine source connector if available
        source_connector = None
        for possible_connector in ["spotify", "lastfm", "musicbrainz"]:
            if possible_connector in playlist.connector_playlist_ids:
                source_connector = possible_connector
                break

        # Save tracks first with source connector for proper mappings
        updated_tracks = await self._save_new_tracks(
            playlist.tracks,
            connector=source_connector,
        )

        # Create the playlist DB entity
        db_playlist = self.mapper.to_db(playlist)
        self.session.add(db_playlist)
        await self.session.flush()
        await self.session.refresh(db_playlist)

        # Ensure we got an ID
        if db_playlist.id is None:
            raise ValueError("Failed to create playlist: no ID was generated")

        # Add mappings and tracks with batch operations
        await self._create_playlist_mappings(
            db_playlist.id,
            playlist.connector_playlist_ids,
        )
        await self._create_playlist_tracks(db_playlist.id, updated_tracks)

        # Return a fresh copy with all relationships eager-loaded
        return await self.get_playlist_by_id(db_playlist.id)

    @db_operation("update_playlist")
    async def update_playlist(
        self,
        playlist_id: int,
        playlist: Playlist,
    ) -> Playlist:
        """Update existing playlist."""
        if not playlist.name:
            raise ValueError("Playlist must have a name")

        # Execute in a transaction using base repository method
        return await self.execute_transaction(
            lambda: self._update_playlist_impl(playlist_id, playlist)
        )

    async def _update_playlist_impl(
        self,
        playlist_id: int,
        playlist: Playlist,
    ) -> Playlist:
        """Implementation for updating an existing playlist."""
        # Update basic properties using base repository's update method
        updates = {
            "name": playlist.name,
            "description": playlist.description,
            "track_count": len(playlist.tracks) if playlist.tracks else 0,
            "updated_at": datetime.now(UTC),
        }

        # Update core properties
        await self.session.execute(
            update(self.model_class)
            .where(
                self.model_class.id == playlist_id,
                self.model_class.is_deleted == False,  # noqa: E712
            )
            .values(**updates),
        )

        # Determine source connector if available
        source_connector = None
        for possible_connector in ["spotify", "lastfm", "musicbrainz"]:
            if possible_connector in playlist.connector_playlist_ids:
                source_connector = possible_connector
                break

        # Process tracks and mappings in parallel
        if playlist.tracks:
            updated_tracks = await self._save_new_tracks(
                playlist.tracks,
                connector=source_connector,
            )
            await self._update_playlist_tracks(playlist_id, updated_tracks)

        # Update connector mappings
        await self._update_connector_mappings(
            playlist_id,
            playlist.connector_playlist_ids,
        )

        # Return the updated playlist with all relationships
        return await self.get_playlist_by_id(playlist_id)

    @db_operation("get_or_create")
    async def get_or_create(
        self,
        lookup_attrs: dict[str, Any],
        create_attrs: dict[str, Any] | None = None,
    ) -> tuple[Playlist, bool]:
        """Find a playlist by attributes or create it."""
        # Leverage base repository's find_one_by method
        conditions = {
            k: v for k, v in lookup_attrs.items() if hasattr(self.model_class, k)
        }

        existing = await self.find_one_by(conditions)
        if existing:
            return existing, False

        # Create new playlist
        all_attrs = {**lookup_attrs}
        if create_attrs:
            all_attrs.update(create_attrs)

        # Validate name
        if "name" not in all_attrs or not all_attrs["name"]:
            raise ValueError("Playlist requires a name")

        # Create the playlist domain object
        playlist = Playlist(
            name=all_attrs["name"],
            description=all_attrs.get("description"),
            tracks=all_attrs.get("tracks", []),
            connector_playlist_ids=all_attrs.get("connector_playlist_ids", {}),
        )

        # Check if we need to save tracks too
        if playlist.tracks:
            # Save with tracks
            created_playlist = await self.save_playlist(playlist)
            return created_playlist, True
        else:
            # Save without tracks using base repository's create method
            created_playlist = await self.create(playlist)

            # Add connector mappings if present
            if playlist.connector_playlist_ids and created_playlist.id is not None:
                await self._create_playlist_mappings(
                    created_playlist.id,
                    playlist.connector_playlist_ids,
                )
                # Refresh to include mappings
                return await self.get_playlist_by_id(created_playlist.id), True

            return created_playlist, True
