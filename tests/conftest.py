import asyncio
import os

import pytest

from src.infrastructure.persistence.database.db_connection import get_session
from src.infrastructure.persistence.database.db_models import init_db


@pytest.fixture(scope="session")
def event_loop_policy():
    """Create an event loop policy for the test session."""
    return asyncio.get_event_loop_policy()


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Set up in-memory database for faster tests."""
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="function")
async def initialize_db():
    """Initialize database schema for tests."""
    try:
        await init_db()
    except Exception as e:
        pytest.fail(f"Database initialization failed: {e}")
    return


@pytest.fixture
async def db_session(initialize_db):
    """Provide database session with automatic rollback."""
    async with get_session(rollback=True) as session:
        yield session


@pytest.fixture
async def track_repo_fixture(db_session):
    """Provide a track repository."""
    from src.infrastructure.persistence.repositories import TrackRepository

    return TrackRepository(db_session)


@pytest.fixture
async def playlist_repo_fixture(db_session):
    """Provide a playlist repository."""
    from src.infrastructure.persistence.repositories import PlaylistRepository

    return PlaylistRepository(db_session)
