import asyncio

import pytest

from narada.database.database import get_session, init_db


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
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
    from narada.core.repositories import TrackRepository

    return TrackRepository(db_session)


@pytest.fixture
async def playlist_repo_fixture(db_session):
    """Provide a playlist repository."""
    from narada.core.repositories import PlaylistRepository

    return PlaylistRepository(db_session)
