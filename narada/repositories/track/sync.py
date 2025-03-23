"""Track synchronization repository for likes and sync checkpoints."""

from datetime import UTC, datetime
from typing import Literal

from attrs import define
from sqlalchemy.ext.asyncio import AsyncSession

from narada.config import get_logger
from narada.core.models import SyncCheckpoint, TrackLike
from narada.database.db_models import DBSyncCheckpoint, DBTrackLike
from narada.repositories.base_repo import BaseModelMapper, BaseRepository
from narada.repositories.repo_decorator import db_operation

logger = get_logger(__name__)


@define(frozen=True, slots=True)
class TrackLikeMapper(BaseModelMapper[DBTrackLike, TrackLike]):
    """Maps between DBTrackLike and TrackLike domain models."""

    @staticmethod
    async def to_domain(db_model: DBTrackLike) -> TrackLike:
        """Convert database like to domain model."""
        if not db_model:
            return None

        return TrackLike(
            track_id=db_model.track_id,
            service=db_model.service,
            is_liked=db_model.is_liked,
            liked_at=db_model.liked_at,
            last_synced=db_model.last_synced,
            id=db_model.id,
        )

    @staticmethod
    def to_db(domain_model: TrackLike) -> DBTrackLike:
        """Convert domain like to database model."""
        return DBTrackLike(
            id=domain_model.id,
            track_id=domain_model.track_id,
            service=domain_model.service,
            is_liked=domain_model.is_liked,
            liked_at=domain_model.liked_at,
            last_synced=domain_model.last_synced,
        )


@define(frozen=True, slots=True)
class SyncCheckpointMapper(BaseModelMapper[DBSyncCheckpoint, SyncCheckpoint]):
    """Maps between DBSyncCheckpoint and SyncCheckpoint domain models."""

    @staticmethod
    async def to_domain(db_model: DBSyncCheckpoint) -> SyncCheckpoint:
        """Convert database checkpoint to domain model."""
        if not db_model:
            return None

        return SyncCheckpoint(
            user_id=db_model.user_id,
            service=db_model.service,
            entity_type=db_model.entity_type,
            last_timestamp=db_model.last_timestamp,
            cursor=db_model.cursor,
            id=db_model.id,
        )

    @staticmethod
    def to_db(domain_model: SyncCheckpoint) -> DBSyncCheckpoint:
        """Convert domain checkpoint to database model."""
        return DBSyncCheckpoint(
            id=domain_model.id,
            user_id=domain_model.user_id,
            service=domain_model.service,
            entity_type=domain_model.entity_type,
            last_timestamp=domain_model.last_timestamp,
            cursor=domain_model.cursor,
        )


class TrackLikeRepository(BaseRepository[DBTrackLike, TrackLike]):
    """Repository for track like operations."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with session and mapper."""
        super().__init__(
            session=session,
            model_class=DBTrackLike,
            mapper=TrackLikeMapper(),
        )

    @db_operation("get_track_likes")
    async def get_track_likes(
        self,
        track_id: int,
        services: list[str] | None = None,
    ) -> list[TrackLike]:
        """Get likes for a track across services."""
        conditions = [self.model_class.track_id == track_id]

        if services:
            conditions.append(self.model_class.service.in_(services))

        return await self.find_by(conditions)

    @db_operation("get_all_liked_tracks")
    async def get_all_liked_tracks(
        self,
        service: str,
        is_liked: bool = True,
    ) -> list[TrackLike]:
        """Get all tracks liked on a specific service."""
        return await self.find_by([
            self.model_class.service == service,
            self.model_class.is_liked == is_liked,
        ])

    @db_operation("get_unsynced_likes")
    async def get_unsynced_likes(
        self,
        source_service: str,
        target_service: str,
        is_liked: bool = True,
        since_timestamp: datetime | None = None,
    ) -> list[TrackLike]:
        """Get tracks liked in source_service but not in target_service."""
        # First get all source tracks with the requested like status
        source_conditions = [
            self.model_class.service == source_service,
            self.model_class.is_liked == is_liked,
        ]

        if since_timestamp:
            source_conditions.append(self.model_class.updated_at >= since_timestamp)

        source_likes = await self.find_by(source_conditions)

        if not source_likes:
            return []

        # Get track IDs that need syncing
        track_ids = [like.track_id for like in source_likes]

        # Find target likes for these tracks
        target_likes = await self.find_by([
            self.model_class.service == target_service,
            self.model_class.track_id.in_(track_ids),
        ])

        # Create lookup dict of target likes by track_id
        target_likes_dict = {like.track_id: like for like in target_likes}

        # Filter source likes that need syncing to target
        return [
            like
            for like in source_likes
            if like.track_id not in target_likes_dict
            or target_likes_dict[like.track_id].is_liked != is_liked
        ]

    @db_operation("save_track_like")
    async def save_track_like(
        self,
        track_id: int,
        service: str,
        is_liked: bool = True,
        last_synced: datetime | None = None,
    ) -> TrackLike:
        """Save a track like for a service."""
        now = datetime.now(UTC)

        # Prepare new values
        update_values = {
            "is_liked": is_liked,
            "updated_at": now,
        }

        if is_liked:
            update_values["liked_at"] = now

        if last_synced:
            update_values["last_synced"] = last_synced

        # Use upsert to either create or update
        return await self.upsert(
            lookup_attrs={"track_id": track_id, "service": service},
            create_attrs=update_values,
        )

    @db_operation("delete_track_like")
    async def delete_track_like(
        self,
        track_id: int,
        service: str,
    ) -> bool:
        """Remove a track like status for a service."""
        # Find the like
        like = await self.find_one_by([
            self.model_class.track_id == track_id,
            self.model_class.service == service,
        ])

        if not like:
            return False

        # Use soft_delete from base repository
        try:
            if like.id is None:
                return False
            await self.soft_delete(like.id)
            return True
        except ValueError:
            return False


class SyncCheckpointRepository(BaseRepository[DBSyncCheckpoint, SyncCheckpoint]):
    """Repository for sync checkpoint operations."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with session and mapper."""
        super().__init__(
            session=session,
            model_class=DBSyncCheckpoint,
            mapper=SyncCheckpointMapper(),
        )

    @db_operation("get_sync_checkpoint")
    async def get_sync_checkpoint(
        self,
        user_id: str,
        service: str,
        entity_type: Literal["likes", "plays"],
    ) -> SyncCheckpoint | None:
        """Get synchronization checkpoint for incremental operations."""
        return await self.find_one_by({
            "user_id": user_id,
            "service": service,
            "entity_type": entity_type,
        })

    @db_operation("save_sync_checkpoint")
    async def save_sync_checkpoint(
        self,
        checkpoint: SyncCheckpoint,
    ) -> SyncCheckpoint:
        """Save or update a sync checkpoint."""
        # Use upsert to handle both creation and updates
        return await self.upsert(
            lookup_attrs={
                "user_id": checkpoint.user_id,
                "service": checkpoint.service,
                "entity_type": checkpoint.entity_type,
            },
            create_attrs={
                "last_timestamp": checkpoint.last_timestamp,
                "cursor": checkpoint.cursor,
            },
        )
