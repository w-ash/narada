"""SQLAlchemy database configuration and connection management.

This module is responsible for:
- Engine creation and configuration
- Connection pooling
- Session management
- Transaction handling
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import os
from typing import Any

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from narada.config import get_logger

# Create module logger
logger = get_logger(__name__)

# Convention for consistent constraint naming
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Create metadata with naming convention
metadata = MetaData(naming_convention=convention)


class Base(AsyncAttrs, DeclarativeBase):
    """Base class for all SQLAlchemy ORM models with async attributes support."""

    metadata = metadata


def create_db_engine(connection_string: str | None = None) -> AsyncEngine:
    """Create async SQLAlchemy engine with optimized connection pooling."""
    # Use connection string from args or environment
    db_url = connection_string or os.environ.get(
        "DATABASE_URL",
        "sqlite+aiosqlite:///narada.db",
    )

    # SQLite-specific connect args
    connect_args = {}
    if db_url.startswith("sqlite"):
        connect_args = {
            "check_same_thread": False,
            # Increase SQLite timeout to help with concurrency
            "timeout": 30.0,  # 30 seconds timeout for busy connections
        }

        # Add query parameters for SQLite pragmas
        if "?" not in db_url:
            db_url += "?"
        else:
            db_url += "&"
        # Enhanced SQLite pragmas for better concurrency:
        # - WAL journal mode for concurrent access
        # - NORMAL synchronous for better performance without losing too much safety
        # - Explicitly enable foreign keys
        # - Increase busy_timeout to prevent "database is locked" errors
        # - Use immediate transactions to avoid deadlocks
        db_url += "journal_mode=WAL&synchronous=NORMAL&foreign_keys=ON&busy_timeout=10000&isolation_level=IMMEDIATE"

    # Configure engine with optimizations for parallel operations
    engine = create_async_engine(
        db_url,
        # Connection pool configuration for parallel operations
        pool_size=10,
        max_overflow=20,
        connect_args=connect_args,
        pool_timeout=30,
        pool_recycle=28800,
        # Validate connections before using them to avoid stale connections
        pool_pre_ping=True,
        # Echo SQL for debugging (disable in production)
        echo=False,
    )

    # Log engine creation
    logger.info("Created database engine with connection pool")
    return engine


# Global engine singleton
_engine: AsyncEngine | None = None


def get_engine() -> AsyncEngine:
    """Get or create the global database engine singleton.

    Returns:
        SQLAlchemy async engine instance
    """
    global _engine
    if _engine is None:
        _engine = create_db_engine()
    return _engine


def create_session_factory(engine: AsyncEngine | None = None) -> async_sessionmaker:
    """Create an async session factory for the given engine.

    Args:
        engine: Optional engine (uses global engine if None)

    Returns:
        Async session factory for creating properly configured sessions
    """
    return async_sessionmaker(
        bind=engine or get_engine(),
        expire_on_commit=False,  # Important: Don't expire objects after commit
        autoflush=True,
        autocommit=False,  # Always work in transactions
    )


# Global session factory singleton
_session_factory: async_sessionmaker | None = None


def get_session_factory() -> async_sessionmaker:
    """Get or create the global session factory singleton.

    Returns:
        Async session factory
    """
    global _session_factory
    if _session_factory is None:
        _session_factory = create_session_factory()
    return _session_factory


@asynccontextmanager
async def get_session(rollback: bool = True) -> AsyncGenerator[AsyncSession]:
    """Get an asynchronous database session with transaction management.

    Args:
        rollback: If True (default), automatically rolls back on exception.
                If False, allows manual transaction management.

    Yields:
        AsyncSession: Managed database session
    """
    session = session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        if rollback:
            await session.rollback()
        raise
    finally:
        await session.close()


@asynccontextmanager
async def get_isolated_session() -> AsyncGenerator[AsyncSession]:
    """Get a session with optimized isolation for operations that need it.

    This creates a session specifically optimized for operations like metrics
    that need better isolation to avoid database locks and conflicts.

    Yields:
        AsyncSession: Isolated database session
    """
    # Create a new session factory with specific settings for isolation
    isolated_factory = async_sessionmaker(
        bind=get_engine(),
        expire_on_commit=False,
        autoflush=False,  # Disable autoflush to avoid implicit I/O
        autocommit=False,
    )

    session = isolated_factory()
    try:
        # Execute pragma statement to ensure immediate transaction mode
        # This helps prevent SQLite database locks in concurrent operations
        from sqlalchemy import text

        await session.execute(text("PRAGMA busy_timeout = 10000"))

        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


@asynccontextmanager
async def transaction(session: AsyncSession) -> AsyncGenerator[AsyncSession]:
    """Create a transaction context that automatically handles commit/rollback.

    This context manager ensures proper transaction handling:
    - Automatically commits if no exceptions occur
    - Automatically rolls back on exceptions
    - Properly nests within parent transactions

    Args:
        session: SQLAlchemy async session

    Yields:
        The same session for operation chaining

    Example:
        ```python
        async with get_session() as session:
            async with transaction(session):
                await session.execute(stmt1)
                await session.execute(stmt2)
                # Auto-commits if no exceptions
        ```
    """
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise


async def soft_delete_record(session: AsyncSession, record: Any) -> None:
    """Soft delete a record by setting is_deleted flag.

    Args:
        session: SQLAlchemy session
        record: Database record with is_deleted attribute
    """
    record.is_deleted = True
    session.add(record)
    await session.flush()


class SafeQuery[T: Any]:
    """Utility for safe query execution with error handling.

    This class provides a safer way to execute queries with proper
    error handling and consistent result processing.

    Example:
        ```python
        result = await SafeQuery(session).execute(
            select(User).where(User.id == user_id)
        ).scalar_one_or_none()
        ```
    """

    def __init__(self, session: AsyncSession):
        """Initialize with a session.

        Args:
            session: Active SQLAlchemy session
        """
        self.session = session
        self._logger = logger.bind(service="database")

    async def execute(self, stmt: Any) -> Any:
        """Execute a statement with proper error handling.

        Args:
            stmt: SQLAlchemy statement to execute

        Returns:
            SQLAlchemy result proxy

        Raises:
            Exception: If query execution fails
        """
        try:
            return await self.session.execute(stmt)
        except Exception as e:
            self._logger.error(f"Query execution error: {e}")
            await self.session.rollback()
            raise


# Import database models after base class is defined to avoid circular imports
from narada.database.db_models import (  # noqa
    DBConnectorTrack,
    DBPlaylist,
    DBPlaylistMapping,
    DBPlaylistTrack,
    DBSyncCheckpoint,
    DBTrack,
    DBTrackLike,
    DBTrackMapping,
    DBTrackMetric,
    DBTrackPlay,
)

# Create aliases for public API
engine = get_engine()
session_factory = get_session_factory()


__all__ = [
    "DBConnectorTrack",
    "DBPlaylist",
    "DBPlaylistMapping",
    "DBPlaylistTrack",
    "DBSyncCheckpoint",
    "DBTrack",
    "DBTrackLike",
    "DBTrackMapping",
    "DBTrackMetric",
    "DBTrackPlay",
    "SafeQuery",
    "create_db_engine",
    "create_session_factory",
    "engine",
    "get_engine",
    "get_isolated_session",
    "get_session",
    "get_session_factory",
    "session_factory",
    "soft_delete_record",
    "transaction",
]
