"""Playlist repository implementation for database operations."""

from datetime import UTC, datetime
from typing import Any

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
from narada.repositories.base import BaseRepository, ModelMapper
from narada.repositories.repo_decorator import db_operation
from narada.repositories.track import UnifiedTrackRepository

logger = get_logger(__name__)


@define(frozen=True, slots=True)
class PlaylistMapper(ModelMapper[DBPlaylist, Playlist]):
    """Bidirectional mapper between domain and persistence models."""

    @staticmethod
    async def to_domain(db_model: DBPlaylist) -> Playlist:
        """Convert persistence model to domain entity."""
        if not db_model:
            return None

        # Process tracks - without using awaitable_attrs that can cause greenlet issues
        domain_tracks = []

        # We expect tracks to be eager loaded already via selectinload
        # SQLAlchemy 2.0 async pattern: rely on eager loading instead of lazy loading
        if hasattr(db_model, "tracks") and db_model.tracks is not None:
            # Filter and sort active tracks
            active_tracks = sorted(
                [pt for pt in db_model.tracks if not pt.is_deleted],
                key=lambda pt: pt.sort_key if hasattr(pt, "sort_key") else 0,
            )

            # Process each playlist track
            for pt in active_tracks:
                if not hasattr(pt, "track") or pt.track is None:
                    continue

                track = pt.track

                # Build connector_track_ids directly from track mappings
                # Again, rely on eager loading instead of triggering lazy loads
                connector_track_ids = {}
                if hasattr(track, "mappings") and track.mappings is not None:
                    for m in track.mappings:
                        if (
                            not m.is_deleted
                            and hasattr(m, "connector_track")
                            and m.connector_track is not None
                        ):
                            connector_track_ids[m.connector_track.connector_name] = (
                                m.connector_track.connector_track_id
                            )

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

        # Get mappings for the playlist itself - without using awaitable_attrs
        connector_playlist_ids = {}

        # Use eager loaded mappings when available
        if hasattr(db_model, "mappings") and db_model.mappings is not None:
            for m in db_model.mappings:
                if not m.is_deleted:
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

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with session and mapper."""
        super().__init__(
            session=session,
            model_class=DBPlaylist,
            mapper=PlaylistMapper(),
        )

    # -------------------------------------------------------------------------
    # HELPER METHODS (non-decorated)
    # -------------------------------------------------------------------------

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

    async def _save_new_tracks(
        self,
        tracks: list[Track],
        track_repo: UnifiedTrackRepository,
    ) -> list[Track]:
        """Save tracks that don't have IDs yet and return updated tracks."""
        if not tracks:
            return []

        updated_tracks = []
        for track in tracks:
            if not track.id:
                try:
                    saved_track = await track_repo.save_track(track)
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

    async def _create_playlist_impl(
        self,
        playlist: Playlist,
        track_repo: UnifiedTrackRepository,
    ) -> Playlist:
        """Implementation to create a new playlist with tracks."""
        # Save tracks first
        updated_tracks = await self._save_new_tracks(playlist.tracks, track_repo)

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

    async def _update_playlist_impl(
        self,
        playlist_id: int,
        playlist: Playlist,
        track_repo: UnifiedTrackRepository,
    ) -> Playlist:
        """Implementation for updating an existing playlist."""
        # Update basic properties using single update statement
        await self.session.execute(
            update(self.model_class)
            .where(
                self.model_class.id == playlist_id,
                self.model_class.is_deleted == False,  # noqa: E712
            )
            .values(
                name=playlist.name,
                description=playlist.description,
                track_count=len(playlist.tracks) if playlist.tracks else 0,
                updated_at=datetime.now(UTC),
            ),
        )

        # Process tracks and mappings in parallel
        if playlist.tracks:
            updated_tracks = await self._save_new_tracks(playlist.tracks, track_repo)
            await self._update_playlist_tracks(playlist_id, updated_tracks)

        # Update connector mappings
        await self._update_connector_mappings(
            playlist_id,
            playlist.connector_playlist_ids,
        )

        # Return the updated playlist with all relationships
        return await self.get_playlist_by_id(playlist_id)

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

        # Execute query directly
        result = await self.session.scalars(stmt)
        db_model = result.first()

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
        # Join and filter by mapping
        stmt = (
            self.select()
            .join(DBPlaylistMapping)
            .where(
                DBPlaylistMapping.connector_name == connector,
                DBPlaylistMapping.connector_playlist_id == connector_id,
                DBPlaylistMapping.is_deleted == False,  # noqa: E712
            )
        )

        # Add eager loading with our helper
        stmt = self.with_playlist_relationships(stmt)

        # Execute query
        result = await self.session.scalars(stmt)
        db_model = result.first()

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
        track_repo: UnifiedTrackRepository,
    ) -> Playlist:
        """Save playlist and all its tracks atomically."""
        if not playlist.name:
            raise ValueError("Playlist must have a name")

        # Execute in a transaction
        async with self.session.begin_nested():
            return await self._create_playlist_impl(playlist, track_repo)

    @db_operation("update_playlist")
    async def update_playlist(
        self,
        playlist_id: int,
        playlist: Playlist,
        track_repo: UnifiedTrackRepository,
    ) -> Playlist:
        """Update existing playlist."""
        if not playlist.name:
            raise ValueError("Playlist must have a name")

        # Execute in a transaction with explicit commit control
        async with self.session.begin_nested():
            # Perform the update implementation
            result = await self._update_playlist_impl(playlist_id, playlist, track_repo)

            # Explicitly flush to ensure all changes are visible
            await self.session.flush()

            return result

    @db_operation("get_or_create")
    async def get_or_create(
        self,
        lookup_attrs: dict[str, Any],
        create_attrs: dict[str, Any] | None = None,
    ) -> tuple[Playlist, bool]:
        """Find a playlist by attributes or create it."""
        # Execute the query directly with relationship loading
        stmt = self.select()
        for field, value in lookup_attrs.items():
            if hasattr(self.model_class, field):
                stmt = stmt.where(getattr(self.model_class, field) == value)

        # Add eager loading
        stmt = self.with_playlist_relationships(stmt)

        # Execute
        result = await self.session.scalars(stmt.limit(1))
        db_playlist = result.first()

        if db_playlist:
            # Found existing playlist, convert to domain model
            playlist = await self.mapper.to_domain(db_playlist)
            return playlist, False

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
        track_repo = all_attrs.get("track_repo")
        if playlist.tracks and track_repo:
            # Save with tracks
            created_playlist = await self.save_playlist(playlist, track_repo)
            return created_playlist, True
        else:
            # Save without tracks
            db_playlist = self.mapper.to_db(playlist)
            self.session.add(db_playlist)
            await self.session.flush()
            await self.session.refresh(db_playlist)

            # Add connector mappings if present
            if playlist.connector_playlist_ids:
                await self._create_playlist_mappings(
                    db_playlist.id,
                    playlist.connector_playlist_ids,
                )

            # Return with ID, create a domain model from DB
            created_playlist = await self.mapper.to_domain(db_playlist)
            return created_playlist, True
