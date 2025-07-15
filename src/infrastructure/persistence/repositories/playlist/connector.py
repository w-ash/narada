"""Connector playlist repository implementation."""

from datetime import UTC, datetime

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities import ConnectorPlaylist, Playlist, Track
from src.infrastructure.config import get_logger
from src.infrastructure.persistence.database.db_models import DBConnectorPlaylist
from src.infrastructure.persistence.repositories.base_repo import BaseRepository
from src.infrastructure.persistence.repositories.playlist.mapper import (
    ConnectorPlaylistMapper,
    PlaylistMappingRepository,
)
from src.infrastructure.persistence.repositories.repo_decorator import db_operation

# Create module logger
logger = get_logger(__name__)


class ConnectorPlaylistRepository(
    BaseRepository[DBConnectorPlaylist, ConnectorPlaylist]
):
    """Repository for connector playlist operations."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with session and mapper."""
        super().__init__(
            session=session,
            model_class=DBConnectorPlaylist,
            mapper=ConnectorPlaylistMapper(),
        )

    def select_by_connector_id(self, connector: str, connector_id: str) -> Select:
        """Create a select statement for a connector playlist by its external ID."""
        return self.select().where(
            self.model_class.connector_name == connector,
            self.model_class.connector_playlist_id == connector_id,
        )

    @db_operation("get_by_connector_id")
    async def get_by_connector_id(
        self, connector: str, connector_id: str
    ) -> ConnectorPlaylist | None:
        """Get a connector playlist by its connector name and external ID."""
        stmt = self.select_by_connector_id(connector, connector_id)
        db_entity = await self.execute_select_one(stmt)

        if not db_entity:
            return None

        return await self.mapper.to_domain(db_entity)

    @db_operation("upsert_model")
    async def upsert_model(
        self, connector_playlist: ConnectorPlaylist
    ) -> ConnectorPlaylist:
        """Upsert a connector playlist directly from a domain model.

        This method preserves all properties of the domain model, including items.

        Args:
            connector_playlist: Complete domain model to persist

        Returns:
            Persisted connector playlist with ID
        """
        # Use lookup by connector name and ID
        lookup_attrs = {
            "connector_name": connector_playlist.connector_name,
            "connector_playlist_id": connector_playlist.connector_playlist_id,
        }

        # Convert domain model to dict for database
        db_model = self.mapper.to_db(connector_playlist)

        # Extract create attributes from the DB model
        create_attrs = {
            attr: getattr(db_model, attr)
            for attr in [
                "name",
                "description",
                "owner",
                "owner_id",
                "is_public",
                "collaborative",
                "follower_count",
                "items",
                "raw_metadata",
                "last_updated",
            ]
        }

        # Perform the upsert operation
        result = await self.upsert(
            lookup_attrs=lookup_attrs,
            create_attrs=create_attrs,
        )

        # Return the domain model with ID
        return result


class PlaylistConnectorRepository:
    """Repository for playlist connector operations."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with session."""
        self.session = session
        self.connector_repo = ConnectorPlaylistRepository(session)
        self.mapping_repo = PlaylistMappingRepository(session)

        # Import these locally to avoid circular imports
        from src.infrastructure.persistence.repositories.playlist.core import (
            PlaylistMapper,
            PlaylistRepository,
        )

        self.playlist_mapper = PlaylistMapper()
        self.playlist_repo = PlaylistRepository(session)

    @db_operation("find_playlist_by_connector")
    async def find_playlist_by_connector(
        self, connector: str, connector_id: str
    ) -> Playlist | None:
        """Find a playlist by connector name and ID."""
        # Check if mapping exists first (most efficient query)
        mapping = await self.mapping_repo.get_by_connector(connector, connector_id)

        if mapping and mapping.get("playlist_id"):
            try:
                # Get the playlist using the playlist_id from the mapping
                return await self.playlist_repo.get_by_id(mapping["playlist_id"])
            except ValueError:
                # Handle case where playlist was deleted but mapping wasn't
                return None

        # No mapping found, return None
        return None

    @db_operation("map_playlist_to_connector")
    async def map_playlist_to_connector(
        self,
        playlist: Playlist,
        connector: str,
        connector_id: str,
        metadata: dict | None = None,
    ) -> Playlist:
        """Map an existing playlist to a connector."""
        if playlist.id is None:
            raise ValueError("Cannot map playlist with no ID")

        # Ensure the playlist exists in the database
        try:
            await self.playlist_repo.get_by_id(playlist.id)
        except ValueError as err:
            raise ValueError(f"Playlist with ID {playlist.id} not found") from err

        now = datetime.now(UTC)
        metadata_to_save = metadata or {}

        # Create or update connector playlist using the domain model approach
        existing_connector_playlist = await self.connector_repo.get_by_connector_id(
            connector, connector_id
        )

        # Create the domain model with all properties
        connector_playlist = ConnectorPlaylist(
            id=existing_connector_playlist.id if existing_connector_playlist else None,
            connector_name=connector,
            connector_playlist_id=connector_id,
            name=playlist.name,
            description=playlist.description,
            owner=metadata_to_save.get("owner"),
            owner_id=metadata_to_save.get("owner_id"),
            is_public=metadata_to_save.get("is_public", False),
            collaborative=metadata_to_save.get("collaborative", False),
            follower_count=metadata_to_save.get("follower_count"),
            # Preserve existing items if present
            items=(
                existing_connector_playlist.items
                if existing_connector_playlist and existing_connector_playlist.items
                else metadata_to_save.get("items", [])
            ),
            raw_metadata=metadata_to_save,
            last_updated=now,
        )

        # Use the upsert_model method which handles all properties
        persisted_playlist = await self.connector_repo.upsert_model(connector_playlist)

        logger.debug(
            f"{'Updated' if existing_connector_playlist else 'Created'} connector playlist for {connector}:{connector_id}",
            connector_playlist_id=persisted_playlist.id,
            has_items=bool(persisted_playlist.items),
            items_count=len(persisted_playlist.items)
            if persisted_playlist.items
            else 0,
        )

        # Create or update the mapping - use upsert to reduce redundancy
        await self.mapping_repo.upsert(
            lookup_attrs={
                "playlist_id": playlist.id,
                "connector_name": connector,
            },
            create_attrs={
                "connector_playlist_id": connector_id,
                "last_synced": now,
            },
        )

        # Return updated playlist with connector ID
        return playlist.with_connector_playlist_id(connector, connector_id)

    @db_operation("ingest_connector_playlist")
    async def ingest_connector_playlist(
        self,
        connector_playlist: ConnectorPlaylist,
        create_internal_playlist: bool = True,
        tracks: list[Track] | None = None,
    ) -> tuple[ConnectorPlaylist, Playlist | None]:
        """Ingest connector playlist data from external source.

        Args:
            connector_playlist: Complete domain model representation of external playlist
            create_internal_playlist: If True, create/update internal playlist
            tracks: Optional list of tracks (if not extractable from connector_playlist)

        Returns:
            Tuple of (persisted_connector_playlist, internal_playlist or None)
        """
        # 1. Upsert connector playlist - always create/update this
        persisted_playlist = await self.connector_repo.upsert_model(connector_playlist)

        # 2. Handle internal playlist if requested
        internal_playlist = None
        if create_internal_playlist:
            connector = connector_playlist.connector_name
            connector_id = connector_playlist.connector_playlist_id

            # Try to find existing playlist by connector
            existing_playlist = await self.find_playlist_by_connector(
                connector, connector_id
            )

            # Create domain model for the playlist
            if existing_playlist and existing_playlist.id is not None:
                # Update existing playlist with fresh data
                internal_playlist = await self.playlist_repo.update_playlist(
                    existing_playlist.id,
                    Playlist(
                        id=existing_playlist.id,
                        name=connector_playlist.name,
                        description=connector_playlist.description,
                        tracks=tracks or [],
                        connector_playlist_ids={connector: connector_id},
                    ),
                )
            else:
                # Create new playlist with connector mapping
                playlist_obj = Playlist(
                    name=connector_playlist.name,
                    description=connector_playlist.description,
                    tracks=tracks or [],
                ).with_connector_playlist_id(connector, connector_id)

                internal_playlist = await self.playlist_repo.save_playlist(playlist_obj)

        return persisted_playlist, internal_playlist
