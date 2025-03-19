"""Track synchronization repository implementation.

This module implements the repository pattern for track sync operations,
providing methods for managing likes and sync checkpoints.
"""

from datetime import UTC, datetime
from typing import Literal

from attrs import define
from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from narada.config import get_logger
from narada.core.models import SyncCheckpoint, TrackLike
from narada.database.db_models import DBSyncCheckpoint, DBTrackLike
from narada.repositories.base import BaseRepository, ModelMapper
from narada.repositories.repo_decorator import db_operation

logger = get_logger(__name__)


@define(frozen=True, slots=True)
class TrackLikeMapper(ModelMapper[DBTrackLike, TrackLike]):
    """Maps between DBTrackLike and TrackLike domain models."""

    @staticmethod
    async def to_domain(db_like: DBTrackLike) -> TrackLike:
        """Convert database like to domain model."""
        if not db_like:
            return None

        return TrackLike(
            track_id=db_like.track_id,
            service=db_like.service,
            is_liked=db_like.is_liked,
            liked_at=db_like.liked_at,
            last_synced=db_like.last_synced,
            id=db_like.id,
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
class SyncCheckpointMapper(ModelMapper[DBSyncCheckpoint, SyncCheckpoint]):
    """Maps between DBSyncCheckpoint and SyncCheckpoint domain models."""

    @staticmethod
    async def to_domain(db_checkpoint: DBSyncCheckpoint) -> SyncCheckpoint:
        """Convert database checkpoint to domain model."""
        if not db_checkpoint:
            return None

        return SyncCheckpoint(
            user_id=db_checkpoint.user_id,
            service=db_checkpoint.service,
            entity_type=db_checkpoint.entity_type,
            last_timestamp=db_checkpoint.last_timestamp,
            cursor=db_checkpoint.cursor,
            id=db_checkpoint.id,
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

    # -------------------------------------------------------------------------
    # ENHANCED QUERY METHODS
    # -------------------------------------------------------------------------

    def select_for_track(
        self,
        track_id: int,
        services: list[str] | None = None,
    ) -> Select:
        """Select likes for a specific track."""
        stmt = self.select().where(self.model_class.track_id == track_id)

        if services:
            stmt = stmt.where(self.model_class.service.in_(services))

        return stmt

    def select_by_service(self, track_id: int, service: str) -> Select:
        """Select like for a specific track and service."""
        return self.select().where(
            self.model_class.track_id == track_id,
            self.model_class.service == service,
        )

    # -------------------------------------------------------------------------
    # PUBLIC API METHODS
    # -------------------------------------------------------------------------

    @db_operation("get_track_likes")
    async def get_track_likes(
        self,
        track_id: int,
        services: list[str] | None = None,
    ) -> list[TrackLike]:
        """Get likes for a track across services."""
        stmt = self.select_for_track(track_id, services)
        db_likes = await self._execute_query(stmt)

        # Convert to domain models
        domain_likes = []
        for db_like in db_likes:
            like = await self.mapper.to_domain(db_like)
            domain_likes.append(like)

        return domain_likes

    @db_operation("save_track_like")
    async def save_track_like(
        self,
        track_id: int,
        service: str,
        is_liked: bool = True,
        last_synced: datetime | None = None,
    ) -> TrackLike:
        """Save a track like for a service."""
        # Look for existing like
        stmt = self.select_by_service(track_id, service)
        db_like = await self._execute_query_one(stmt)

        now = datetime.now(UTC)

        if db_like:
            # Update existing like
            updates = {
                "is_liked": is_liked,
                "updated_at": now,
            }

            if is_liked and not db_like.liked_at:
                updates["liked_at"] = now

            if last_synced:
                updates["last_synced"] = last_synced

            # Use the base repository update method
            domain_like = await self.update(db_like.id, updates)
            return domain_like
        else:
            # Create new like
            like = TrackLike(
                track_id=track_id,
                service=service,
                is_liked=is_liked,
                liked_at=now if is_liked else None,
                last_synced=last_synced,
            )

            # Use the base repository create method
            return await self.create(like)

    @db_operation("delete_track_like")
    async def delete_track_like(
        self,
        track_id: int,
        service: str,
    ) -> bool:
        """Remove a track like status for a service."""
        # Find the like
        stmt = self.select_by_service(track_id, service)
        db_like = await self._execute_query_one(stmt)

        if not db_like:
            return False

        # Use base repository's soft_delete method
        try:
            await self.soft_delete(db_like.id)
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

    # -------------------------------------------------------------------------
    # ENHANCED QUERY METHODS
    # -------------------------------------------------------------------------

    def select_checkpoint(
        self,
        user_id: str,
        service: str,
        entity_type: str,
    ) -> Select:
        """Select a specific checkpoint."""
        return self.select().where(
            self.model_class.user_id == user_id,
            self.model_class.service == service,
            self.model_class.entity_type == entity_type,
        )

    # -------------------------------------------------------------------------
    # PUBLIC API METHODS
    # -------------------------------------------------------------------------

    @db_operation("get_sync_checkpoint")
    async def get_sync_checkpoint(
        self,
        user_id: str,
        service: str,
        entity_type: Literal["likes", "plays"],
    ) -> SyncCheckpoint | None:
        """Get synchronization checkpoint for incremental operations."""
        stmt = self.select_checkpoint(user_id, service, entity_type)
        db_checkpoint = await self._execute_query_one(stmt)

        if not db_checkpoint:
            return None

        return await self.mapper.to_domain(db_checkpoint)

    @db_operation("save_sync_checkpoint")
    async def save_sync_checkpoint(
        self,
        checkpoint: SyncCheckpoint,
    ) -> SyncCheckpoint:
        """Save or update a sync checkpoint."""
        # Look for existing checkpoint
        stmt = self.select_checkpoint(
            checkpoint.user_id,
            checkpoint.service,
            checkpoint.entity_type,
        )

        db_checkpoint = await self._execute_query_one(stmt)

        if db_checkpoint:
            # Update existing checkpoint
            updates = {
                "last_timestamp": checkpoint.last_timestamp,
                "cursor": checkpoint.cursor,
            }

            return await self.update(db_checkpoint.id, updates)
        else:
            # Create new checkpoint
            return await self.create(checkpoint)


class TrackSyncRepository:
    """Combined repository for track synchronization operations."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with session."""
        self.session = session
        self.likes = TrackLikeRepository(session)
        self.checkpoints = SyncCheckpointRepository(session)

    # Re-export methods from component repositories
    async def get_track_likes(self, *args, **kwargs):
        """Get likes for a track across services."""
        return await self.likes.get_track_likes(*args, **kwargs)
        
    async def save_track_like(self, *args, **kwargs):
        """Save a track like for a service."""
        return await self.likes.save_track_like(*args, **kwargs)
        
    async def delete_track_like(self, *args, **kwargs):
        """Remove a track like status for a service."""
        return await self.likes.delete_track_like(*args, **kwargs)
    
    async def get_sync_checkpoint(self, *args, **kwargs):
        """Get synchronization checkpoint for incremental operations."""
        return await self.checkpoints.get_sync_checkpoint(*args, **kwargs)
        
    async def save_sync_checkpoint(self, *args, **kwargs):
        """Save or update a sync checkpoint."""
        return await self.checkpoints.save_sync_checkpoint(*args, **kwargs)
