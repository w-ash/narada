"""Database layer for Narada music integration platform.

This package provides database models and utilities for persistence, including:
- Core entity models (Track, Playlist, etc.)
- Session management
- Database operations
- Data schema management

Usage:
------
1. Get a session:
   async with get_session() as session:
       tracks = await session.execute(DBTrack.active_records())
       result = tracks.scalars().all()

2. Create records
    track = DBTrack(title="Song Name", artists={"name": "Artist Name"})
    session.add(track)
    await session.commit()

3. Initialize database:
    await init_db()  # Creates schema if needed
"""

# Import database models
from narada.database.database import (
    engine,
    get_session,
    session_factory,
    soft_delete_record,
)
from narada.database.dbmodels import (
    DBPlayCount,
    DBPlaylist,
    DBPlaylistMapping,
    DBPlaylistTrack,
    DBTrack,
    DBTrackMapping,
    init_db,
)

# Define explicit public API
__all__ = [
    "DBPlayCount",
    "DBPlaylist",
    "DBPlaylistMapping",
    "DBPlaylistTrack",
    "DBTrack",
    "DBTrackMapping",
    "engine",
    "get_session",
    "init_db",
    "session_factory",
    "soft_delete_record",
]
