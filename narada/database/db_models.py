"""SQLAlchemy database models for the Narada music platform.

This module defines the core domain entities and their relationships using
SQLAlchemy 2.0 patterns with proper type annotations and relationship definitions.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Select,
    String,
    UniqueConstraint,
    select,
)
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from narada.config import get_logger

# Create module logger
logger = get_logger(__name__)


class NaradaDBBase(AsyncAttrs, DeclarativeBase):
    """Base class for all database models with timestamps and soft delete."""

    id: Mapped[int] = mapped_column(primary_key=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    def mark_soft_deleted(self) -> None:
        """Mark record as logically deleted (soft delete)."""
        self.is_deleted = True
        self.deleted_at = datetime.now(UTC)

    @classmethod
    def active_records(cls) -> Select:
        """Return a select statement for non-deleted records."""
        return select(cls).where(cls.is_deleted == False)  # noqa: E712


class DBTrack(NaradaDBBase):
    """Core track entity with essential metadata."""

    __tablename__ = "tracks"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    artists: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    album: Mapped[str | None] = mapped_column(String(255))
    duration_ms: Mapped[int | None]
    release_date: Mapped[datetime | None]
    isrc: Mapped[str | None] = mapped_column(String(32), index=True)
    spotify_id: Mapped[str | None] = mapped_column(String(64), index=True)
    mbid: Mapped[str | None] = mapped_column(String(36), index=True)

    # Relationships
    mappings: Mapped[list["DBTrackMapping"]] = relationship(
        back_populates="track",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    metrics: Mapped[list["DBTrackMetric"]] = relationship(
        back_populates="track",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    likes: Mapped[list["DBTrackLike"]] = relationship(
        back_populates="track",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    plays: Mapped[list["DBTrackPlay"]] = relationship(
        back_populates="track",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    playlist_tracks: Mapped[list["DBPlaylistTrack"]] = relationship(
        back_populates="track",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class DBConnectorTrack(NaradaDBBase):
    """External track representation from a specific music service."""

    __tablename__ = "connector_tracks"

    connector_name: Mapped[str] = mapped_column(String(32), index=True)
    connector_track_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    artists: Mapped[dict[str, Any]] = mapped_column(JSON)
    album: Mapped[str | None] = mapped_column(String(255))
    duration_ms: Mapped[int | None]
    isrc: Mapped[str | None] = mapped_column(String(32), index=True)
    release_date: Mapped[datetime | None]
    raw_metadata: Mapped[dict[str, Any]] = mapped_column(JSON)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )

    # Mapping relationship - plural to reflect conceptual many-to-one possibility
    mappings: Mapped[list["DBTrackMapping"]] = relationship(
        back_populates="connector_track",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint("connector_name", "connector_track_id"),
        Index("ix_connector_tracks_lookup", "connector_name", "isrc"),
    )


class DBTrackMapping(NaradaDBBase):
    """Maps external connector tracks to internal canonical tracks."""

    __tablename__ = "track_mappings"

    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id", ondelete="CASCADE"))
    connector_track_id: Mapped[int] = mapped_column(
        ForeignKey("connector_tracks.id", ondelete="CASCADE"),
    )
    match_method: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[int]

    # Relationships
    track: Mapped["DBTrack"] = relationship(
        back_populates="mappings",
        passive_deletes=True,
    )
    connector_track: Mapped["DBConnectorTrack"] = relationship(
        back_populates="mappings",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_track_mappings_lookup", "track_id", "connector_track_id"),
    )


class DBTrackMetric(NaradaDBBase):
    """Time-series metrics for tracks from external services."""

    __tablename__ = "track_metrics"
    __table_args__ = (
        Index("ix_track_metrics_lookup", "track_id", "connector_name", "metric_type"),
    )

    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id", ondelete="CASCADE"))
    connector_name: Mapped[str] = mapped_column(String(32))
    metric_type: Mapped[str] = mapped_column(String(32))
    value: Mapped[float]
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )

    # Relationships
    track: Mapped[DBTrack] = relationship(
        back_populates="metrics",
        passive_deletes=True,
    )


class DBTrackLike(NaradaDBBase):
    """Track preference state across music services."""

    __tablename__ = "track_likes"
    __table_args__ = (
        UniqueConstraint("track_id", "service"),
        Index("ix_track_likes_lookup", "service", "is_liked"),
    )

    # Core fields
    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id", ondelete="CASCADE"))
    service: Mapped[str] = mapped_column(String(32))  # 'spotify', 'lastfm', 'internal'
    is_liked: Mapped[bool] = mapped_column(Boolean, default=True)
    liked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_synced: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    track: Mapped["DBTrack"] = relationship(
        back_populates="likes",
        passive_deletes=True,
    )


class DBTrackPlay(NaradaDBBase):
    """Immutable record of track plays across services."""

    __tablename__ = "track_plays"
    __table_args__ = (
        Index("ix_track_plays_service", "service"),
        Index("ix_track_plays_timeline", "played_at"),  # For chronological queries
    )

    # Core fields
    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id", ondelete="CASCADE"))
    service: Mapped[str] = mapped_column(String(32))  # 'spotify', 'lastfm', 'internal'
    played_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    ms_played: Mapped[int | None]
    context: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    # Relationships
    track: Mapped["DBTrack"] = relationship(
        back_populates="plays",
        passive_deletes=True,
    )


class DBPlaylist(NaradaDBBase):
    """User playlist metadata."""

    __tablename__ = "playlists"

    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(1000))
    track_count: Mapped[int] = mapped_column(default=0)

    # Relationships
    tracks: Mapped[list["DBPlaylistTrack"]] = relationship(
        back_populates="playlist",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    mappings: Mapped[list["DBPlaylistMapping"]] = relationship(
        back_populates="playlist",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class DBPlaylistMapping(NaradaDBBase):
    """External service playlist mappings."""

    __tablename__ = "playlist_mappings"
    __table_args__ = (UniqueConstraint("playlist_id", "connector_name"),)

    playlist_id: Mapped[int] = mapped_column(
        ForeignKey("playlists.id", ondelete="CASCADE"),
    )
    connector_name: Mapped[str] = mapped_column(String(32))
    connector_playlist_id: Mapped[str] = mapped_column(String(64))
    last_synced: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )

    # Relationships
    playlist: Mapped[DBPlaylist] = relationship(
        back_populates="mappings",
        passive_deletes=True,
    )


class DBPlaylistTrack(NaradaDBBase):
    """Playlist track ordering and metadata."""

    __tablename__ = "playlist_tracks"
    __table_args__ = (Index("ix_playlist_tracks_order", "playlist_id", "sort_key"),)

    playlist_id: Mapped[int] = mapped_column(
        ForeignKey("playlists.id", ondelete="CASCADE"),
    )
    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id", ondelete="CASCADE"))
    sort_key: Mapped[str] = mapped_column(String(32))

    # Relationships
    playlist: Mapped[DBPlaylist] = relationship(
        back_populates="tracks",
        passive_deletes=True,
    )
    track: Mapped[DBTrack] = relationship(
        back_populates="playlist_tracks",
        passive_deletes=True,
    )


class DBSyncCheckpoint(NaradaDBBase):
    """Sync state tracking for incremental operations."""

    __tablename__ = "sync_checkpoints"
    __table_args__ = (UniqueConstraint("user_id", "service", "entity_type"),)

    user_id: Mapped[str] = mapped_column(String(64))
    service: Mapped[str] = mapped_column(String(32))  # 'spotify', 'lastfm'
    entity_type: Mapped[str] = mapped_column(String(32))  # 'likes', 'plays'
    last_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cursor: Mapped[str | None] = mapped_column(String(1024))  # continuation token


async def init_db() -> None:
    """Initialize database schema.

    Creates all tables if they don't exist.
    """
    from narada.database.db_connection import get_engine

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(NaradaDBBase.metadata.create_all)
    logger.info("Database schema initialized")
