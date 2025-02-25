"""SQLAlchemy database configuration and models."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    declared_attr,
    mapped_column,
    relationship,
)
from sqlalchemy.sql import Select

from narada.config import get_config

# Shared configuration

engine = create_async_engine(
    url=get_config("DATABASE_URL"),
    pool_pre_ping=True,
    pool_timeout=get_config("DATABASE_POOL_TIMEOUT"),
    pool_recycle=get_config("DATABASE_POOL_RECYCLE"),
    max_overflow=get_config("DATABASE_MAX_OVERFLOW"),
    echo=get_config("DATABASE_ECHO"),
)

session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class NaradaDBBase(DeclarativeBase):
    """Base class for all database models with timestamps and soft delete."""

    id: Mapped[int] = mapped_column(primary_key=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    def mark_soft_deleted(self) -> None:
        """Mark record as logically deleted (soft delete).

        This is NOT a database deletion - it only sets is_deleted=True.
        For actual record deletion, use session.delete().
        """
        self.is_deleted = True
        self.deleted_at = func.now()

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, Any]:
        """Configure mapper arguments."""
        return {
            "eager_defaults": True,
        }

    @classmethod
    def active_records(cls) -> Select:
        """Return a select statement for non-deleted records."""
        return select(cls).where(cls.is_deleted == False)  # noqa: E712


class DBTrack(NaradaDBBase):
    """Core track entity with essential metadata."""

    __tablename__ = "tracks"

    title: Mapped[str] = mapped_column(String(255))
    artists: Mapped[dict[str, Any]] = mapped_column(JSON)
    album: Mapped[str | None] = mapped_column(String(255))
    duration_ms: Mapped[int | None]
    release_date: Mapped[datetime | None]
    spotify_id: Mapped[str | None] = mapped_column(String(64), index=True)
    isrc: Mapped[str | None] = mapped_column(String(32), index=True)
    lastfm_url: Mapped[str | None] = mapped_column(String(255))

    play_counts = relationship(
        "DBPlayCount",
        back_populates="track",
        passive_deletes=True,
        cascade_backrefs=False,
    )

    mappings = relationship(
        "DBTrackMapping",
        back_populates="track",
        passive_deletes=True,
        cascade_backrefs=False,
    )
    playlist_tracks = relationship(
        "DBPlaylistTrack",
        back_populates="track",
        passive_deletes=True,
        cascade_backrefs=False,
    )


class DBPlayCount(NaradaDBBase):
    """Play count data from Last.fm."""

    __tablename__ = "play_counts"
    __table_args__ = (UniqueConstraint("track_id", "user_id"),)

    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id"))
    user_id: Mapped[str] = mapped_column(String(64))
    play_count: Mapped[int] = mapped_column(default=0)
    user_play_count: Mapped[int] = mapped_column(default=0)
    last_updated: Mapped[datetime] = mapped_column(default=func.now())

    track = relationship("DBTrack", back_populates="play_counts")


class DBTrackMapping(NaradaDBBase):
    """Cross-source track identifier mappings."""

    __tablename__ = "track_mappings"
    __table_args__ = (
        UniqueConstraint("connector_name", "connector_id"),
        Index("ix_track_mappings_lookup", "track_id", "connector_name"),
    )

    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id"))
    connector_name: Mapped[str] = mapped_column(String(32))
    connector_id: Mapped[str] = mapped_column(String(64))
    match_method: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[int]
    last_verified: Mapped[datetime] = mapped_column(default=func.now())
    connector_metadata: Mapped[dict[str, Any]] = mapped_column(JSON)

    track = relationship("DBTrack", back_populates="mappings", passive_deletes=True)


class DBPlaylist(NaradaDBBase):
    """User playlist metadata."""

    __tablename__ = "playlists"

    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(1000))
    track_count: Mapped[int] = mapped_column(default=0)

    tracks = relationship(
        "DBPlaylistTrack",
        back_populates="playlist",
        passive_deletes=True,
        cascade_backrefs=False,
    )
    mappings = relationship(
        "DBPlaylistMapping",
        back_populates="playlist",
        passive_deletes=True,
        cascade_backrefs=False,
    )


class DBPlaylistMapping(NaradaDBBase):
    """External source playlist mappings."""

    __tablename__ = "playlist_mappings"
    __table_args__ = (UniqueConstraint("playlist_id", "connector_name"),)

    playlist_id: Mapped[int] = mapped_column(ForeignKey("playlists.id"))
    connector_name: Mapped[str] = mapped_column(String(32))
    connector_id: Mapped[str] = mapped_column(String(64))
    last_synced: Mapped[datetime] = mapped_column(default=func.now())

    playlist = relationship("DBPlaylist", back_populates="mappings")


class DBPlaylistTrack(NaradaDBBase):
    """Playlist track ordering and metadata."""

    __tablename__ = "playlist_tracks"
    __table_args__ = (Index("ix_playlist_tracks_order", "playlist_id", "sort_key"),)

    playlist_id: Mapped[int] = mapped_column(ForeignKey("playlists.id"))
    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id"))
    sort_key: Mapped[str] = mapped_column(String(32))

    playlist = relationship("DBPlaylist", back_populates="tracks", passive_deletes=True)
    track = relationship(
        "DBTrack", back_populates="playlist_tracks", passive_deletes=True
    )


# Database Operations
@asynccontextmanager
async def get_session(
    rollback: bool = True,
) -> AsyncGenerator[AsyncSession, None]:
    """Get database session with automatic transaction management.

    Args:
        rollback: If True, rolls back changes (for tests)
                 If False, commits changes (for development/inspection)
        expire_on_commit: If True, invalidates objects after commit
                         If False, keeps objects valid (better for testing)

    Yields:
        AsyncSession: Managed database session

    Example:
        async with get_session(rollback=False) as session:
            stmt = select(DBTrack)
            result = await session.scalar(stmt)  # New SQLAlchemy 2.0 pattern
    """
    async with session_factory() as session:
        try:
            async with session.begin():
                yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            if rollback:
                await session.rollback()
            else:
                await session.commit()
            await session.close()


async def init_db() -> None:
    """Initialize database schema."""
    async with engine.begin() as conn:
        await conn.run_sync(NaradaDBBase.metadata.create_all)


async def soft_delete_record(session: AsyncSession, model: NaradaDBBase) -> None:
    """Soft delete a record and cascade to relationships."""
    # Mark the parent as deleted
    model.mark_soft_deleted()

    # Load all relationships explicitly (SQLAlchemy 2.0 best practice)
    await session.refresh(
        model, attribute_names=[rel.key for rel in model.__mapper__.relationships]
    )

    # Mark all related records as deleted
    for rel in model.__mapper__.relationships:
        related = getattr(model, rel.key)
        if related is not None:
            if isinstance(related, list):
                for item in related:
                    item.mark_soft_deleted()
                    await session.flush()

            else:
                related.mark_soft_deleted()
                await session.flush()

    # Single transaction
    await session.commit()
