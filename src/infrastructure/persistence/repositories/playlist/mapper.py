"""Playlist repository mappers for domain-persistence conversions."""

from datetime import UTC, datetime
from typing import Any, TypeVar

from attrs import define
from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_logger
from src.domain.entities import (
    Artist,
    ConnectorPlaylist,
    ConnectorPlaylistItem,
    Playlist,
    Track,
    ensure_utc,
)
from src.infrastructure.persistence.database.db_models import (
    DBConnectorPlaylist,
    DBPlaylist,
    DBPlaylistMapping,
)
from src.infrastructure.persistence.repositories.base_repo import (
    BaseModelMapper,
    BaseRepository,
    safe_fetch_relationship,
)
from src.infrastructure.persistence.repositories.repo_decorator import db_operation
from src.infrastructure.persistence.repositories.track.mapper import TrackMapper

# Create module logger
logger = get_logger(__name__)

# Type variables for generic operations
P = TypeVar("P", bound=Playlist)
CP = TypeVar("CP", bound=ConnectorPlaylist)


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

        # Process tracks - consistently use awaitable_attrs pattern for async safety
        domain_tracks = []

        # Get playlist tracks using safe fetch relationship (always returns a list)
        playlist_tracks = await safe_fetch_relationship(db_model, "tracks")

        # Filter and sort active tracks
        active_tracks = sorted(
            [
                pt
                for pt in playlist_tracks
                if hasattr(pt, "is_deleted") and not pt.is_deleted
            ],
            key=lambda pt: pt.sort_key if hasattr(pt, "sort_key") else 0,
        )

        # Process each playlist track
        for pt in active_tracks:
            # Get track consistently - safe_fetch_relationship always returns a list
            tracks = await safe_fetch_relationship(pt, "track")

            # Skip if no track was found
            if not tracks:
                continue

            # Get the first track from the list (to-one relationship)
            track = tracks[0]

            # Skip deleted or missing tracks
            if not track or (hasattr(track, "is_deleted") and track.is_deleted):
                continue

            # Get track mappings - always returns a list
            track_mappings = await safe_fetch_relationship(track, "mappings")

            # Build connector_track_ids from mappings
            connector_track_ids = {}

            # Process non-deleted track mappings efficiently
            for m in track_mappings:
                if hasattr(m, "is_deleted") and m.is_deleted:
                    continue

                # Get connector tracks - always returns a list
                try:
                    connector_tracks = await safe_fetch_relationship(
                        m, "connector_track"
                    )
                    if not connector_tracks:
                        continue

                    # Get the first connector track (to-one relationship)
                    connector_track = connector_tracks[0]

                    # Skip if it's deleted or missing required attributes
                    if (
                        not connector_track
                        or (
                            hasattr(connector_track, "is_deleted")
                            and connector_track.is_deleted
                        )
                        or not hasattr(connector_track, "connector_name")
                        or not hasattr(connector_track, "connector_track_id")
                    ):
                        continue

                    # Store connector track ID
                    connector_track_ids[connector_track.connector_name] = (
                        connector_track.connector_track_id
                    )
                except Exception as e:
                    logger.debug(f"Error getting connector track: {e}")
                    continue

            # Skip tracks missing essential attributes
            if not all(hasattr(track, attr) for attr in ["id", "title", "artists"]):
                continue

            # Extract artist names using standardized method
            artist_names = TrackMapper.extract_artist_names(
                track.artists.get("names", [])
            )
            if not artist_names:
                continue

            # Create the track domain object
            domain_tracks.append(
                Track(
                    id=track.id,
                    title=track.title,
                    artists=[Artist(name=name) for name in artist_names],
                    album=getattr(track, "album", None),
                    duration_ms=getattr(track, "duration_ms", None),
                    release_date=ensure_utc(getattr(track, "release_date", None)),
                    isrc=getattr(track, "isrc", None),
                    connector_track_ids=connector_track_ids,
                ),
            )

        # Get playlist mappings using safe fetch relationship (always returns a list)
        playlist_mappings = await safe_fetch_relationship(db_model, "mappings")

        # Process active playlist mappings
        connector_playlist_ids = {}
        for m in playlist_mappings:
            if (
                not (hasattr(m, "is_deleted") and m.is_deleted)
                and hasattr(m, "connector_name")
                and hasattr(m, "connector_playlist_id")
            ):
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


@define(frozen=True, slots=True)
class ConnectorPlaylistMapper(BaseModelMapper[DBConnectorPlaylist, ConnectorPlaylist]):
    """Maps between DBConnectorPlaylist and ConnectorPlaylist domain model."""

    @staticmethod
    async def to_domain(db_model: DBConnectorPlaylist) -> ConnectorPlaylist:
        """Convert DB connector playlist to domain model."""
        if not db_model:
            return None

        # Convert stored JSON items to ConnectorPlaylistItem objects
        items = [
            ConnectorPlaylistItem(
                connector_track_id=item_dict["connector_track_id"],
                position=item_dict["position"],
                added_at=item_dict.get("added_at"),
                added_by_id=item_dict.get("added_by_id"),
                extras=item_dict.get("extras", {}),
            )
            for item_dict in db_model.items
        ]

        return ConnectorPlaylist(
            id=db_model.id,
            connector_name=db_model.connector_name,
            connector_playlist_id=db_model.connector_playlist_id,
            name=db_model.name,
            description=db_model.description,
            owner=db_model.owner,
            owner_id=db_model.owner_id,
            is_public=db_model.is_public,
            collaborative=db_model.collaborative,
            follower_count=db_model.follower_count,
            raw_metadata=db_model.raw_metadata,
            items=items,
            last_updated=db_model.last_updated,
        )

    @staticmethod
    def to_db(domain_model: ConnectorPlaylist) -> DBConnectorPlaylist:
        """Convert domain model to DB connector playlist."""
        # Convert ConnectorPlaylistItem objects to serializable dictionaries
        items_dicts = [
            {
                "connector_track_id": item.connector_track_id,
                "position": item.position,
                "added_at": item.added_at,
                "added_by_id": item.added_by_id,
                "extras": item.extras,
            }
            for item in domain_model.items
        ]

        return DBConnectorPlaylist(
            id=domain_model.id,
            connector_name=domain_model.connector_name,
            connector_playlist_id=domain_model.connector_playlist_id,
            name=domain_model.name,
            description=domain_model.description,
            owner=domain_model.owner,
            owner_id=domain_model.owner_id,
            is_public=domain_model.is_public,
            collaborative=domain_model.collaborative,
            follower_count=domain_model.follower_count,
            raw_metadata=domain_model.raw_metadata,
            items=items_dicts,
            last_updated=domain_model.last_updated,
        )

    @staticmethod
    def get_default_relationships() -> list[str]:
        """Get default relationships to load for connector playlists."""
        return []


@define(frozen=True, slots=True)
class PlaylistMappingMapper(BaseModelMapper[DBPlaylistMapping, dict[str, Any]]):
    """Maps between DBPlaylistMapping and dictionary representation."""

    @staticmethod
    async def to_domain(db_model: DBPlaylistMapping) -> dict[str, Any]:
        """Convert DB mapping to dictionary."""
        if not db_model:
            return None

        return {
            "id": db_model.id,
            "playlist_id": db_model.playlist_id,
            "connector_name": db_model.connector_name,
            "connector_playlist_id": db_model.connector_playlist_id,
            "last_synced": db_model.last_synced,
        }

    @staticmethod
    def to_db(domain_model: dict[str, Any]) -> DBPlaylistMapping:
        """Convert dictionary to DB mapping."""
        return DBPlaylistMapping(
            playlist_id=domain_model.get("playlist_id"),
            connector_name=domain_model.get("connector_name"),
            connector_playlist_id=domain_model.get("connector_playlist_id"),
            last_synced=domain_model.get("last_synced", datetime.now(UTC)),
        )

    @staticmethod
    def get_default_relationships() -> list[str]:
        """Get default relationships to load for playlist mappings."""
        return ["playlist"]


class PlaylistMappingRepository(BaseRepository[DBPlaylistMapping, dict[str, Any]]):
    """Repository for playlist mapping operations."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with session and mapper."""
        super().__init__(
            session=session,
            model_class=DBPlaylistMapping,
            mapper=PlaylistMappingMapper(),
        )

    def select_by_connector(self, connector: str, connector_id: str) -> Select:
        """Create a select statement for a mapping by connector details."""
        return self.select().where(
            self.model_class.connector_name == connector,
            self.model_class.connector_playlist_id == connector_id,
        )

    @db_operation("get_by_connector")
    async def get_by_connector(
        self, connector: str, connector_id: str
    ) -> dict[str, Any] | None:
        """Get a playlist mapping by connector name and external ID."""
        stmt = self.select_by_connector(connector, connector_id)
        db_entity = await self.execute_select_one(stmt)

        if not db_entity:
            return None

        return await self.mapper.to_domain(db_entity)
