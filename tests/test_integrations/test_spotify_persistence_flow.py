"""Integration tests for Spotify playlist download and persistence.

This module tests the end-to-end flow of downloading Spotify playlists
and persisting them to the local database, ensuring proper track
deduplication and relationship management.

Uses SQLAlchemy 2.0 async patterns to prevent greenlet errors.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from narada.core.repositories import PlaylistRepository, TrackRepository
from narada.database.database import get_session
from narada.integrations.spotify import SpotifyConnector


@pytest.fixture
async def spotify() -> SpotifyConnector:
    """Provide authenticated Spotify client for testing."""
    return SpotifyConnector()


@pytest.fixture
async def track_repo(db_session: AsyncSession) -> TrackRepository:
    """Provide track repository with injected test session."""
    return TrackRepository(db_session)


@pytest.fixture
async def playlist_repo(db_session: AsyncSession) -> PlaylistRepository:
    """Provide playlist repository with injected test session."""
    return PlaylistRepository(db_session)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_spotify_playlist_persistence(
    spotify: SpotifyConnector,
    track_repo: TrackRepository,
    playlist_repo: PlaylistRepository,
) -> None:
    """Test end-to-end flow of downloading and persisting a Spotify playlist.

    Flow:
    1. Fetch playlist from Spotify API
    2. Save tracks to database
    3. Create playlist with track relationships
    4. Verify persistence and relationships
    """
    TEST_PLAYLIST_ID = "54z4aq8BmCPox937mVrt9v"  # 🪢 43rd - Twin paradox

    # Fetch and verify playlist
    domain_playlist = await spotify.get_spotify_playlist(TEST_PLAYLIST_ID)
    assert domain_playlist.name is not None
    assert len(domain_playlist.tracks) > 0

    # Verify connector ID mapping
    assert "spotify" in domain_playlist.connector_track_ids

    # Save playlist and verify relationships
    playlist_id = await playlist_repo.save_playlist(domain_playlist, track_repo)
    saved_playlist = await playlist_repo.get_playlist("internal", playlist_id)

    assert saved_playlist is not None
    assert saved_playlist.name == domain_playlist.name
    assert len(saved_playlist.tracks) == len(domain_playlist.tracks)

    # Verify first track has proper mappings
    first_track = saved_playlist.tracks[0]
    original_track = domain_playlist.tracks[0]
    assert first_track.title == original_track.title
    assert first_track.artists == original_track.artists
    assert "spotify" in first_track.connector_track_ids


@pytest.mark.integration
@pytest.mark.asyncio
async def test_duplicate_track_handling(
    spotify: SpotifyConnector,
    track_repo: TrackRepository,
    playlist_repo: PlaylistRepository,
) -> None:
    """Test handling of duplicate tracks across different playlists.

    Flow:
    1. Save first playlist and collect track IDs
    2. Save second playlist with overlapping tracks
    3. Verify shared tracks weren't duplicated
    4. Verify both playlists reference same track records
    """
    PLAYLIST_IDS = [
        "54z4aq8BmCPox937mVrt9v",  # 🪢 43rd - Twin paradox
        "14GT9ahKyAR9SObC7GdwtO",  # 🤔 Interesting `25
    ]

    # 1. Save first playlist and collect track IDs
    first_playlist = await spotify.get_spotify_playlist(PLAYLIST_IDS[0])
    print(f"First playlist: {first_playlist.name}, {len(first_playlist.tracks)} tracks")

    first_track_ids = {
        t.connector_track_ids.get("spotify", "") for t in first_playlist.tracks
    }
    print(f"First track IDs (first 5): {list(first_track_ids)[:5]}")
    first_playlist_id = await playlist_repo.save_playlist(first_playlist, track_repo)

    # 2. Save second playlist with overlapping tracks
    second_playlist = await spotify.get_spotify_playlist(PLAYLIST_IDS[1])
    print(
        f"Second playlist: {second_playlist.name}, {len(second_playlist.tracks)} tracks",
    )

    second_track_ids = {
        t.connector_track_ids.get("spotify", "") for t in second_playlist.tracks
    }
    print(f"Second track IDs (first 5): {list(second_track_ids)[:5]}")
    second_playlist_id = await playlist_repo.save_playlist(second_playlist, track_repo)

    # Print all track IDs to check for overlap
    print(f"Common track IDs: {first_track_ids.intersection(second_track_ids)}")

    # Create artificial overlap if needed
    if not first_track_ids.intersection(second_track_ids):
        print("No natural overlap found - creating artificial overlap for testing")
        # Take a track from the first playlist and add it to the second
        track_to_share = first_playlist.tracks[0]

        # Get the modified second playlist
        modified_second_tracks = [track_to_share] + second_playlist.tracks
        modified_second_playlist = second_playlist.with_tracks(modified_second_tracks)

        # Update second_track_ids to include the shared track
        second_track_ids = {
            t.connector_track_ids.get("spotify", "")
            for t in modified_second_playlist.tracks
        }

        # Save the modified second playlist
        second_playlist_id = await playlist_repo.save_playlist(
            modified_second_playlist,
            track_repo,
        )
        shared_track_ids = {track_to_share.connector_track_ids.get("spotify", "")}
        print(f"Created artificial overlap with track ID: {shared_track_ids}")
    else:
        shared_track_ids = first_track_ids.intersection(second_track_ids)

    assert shared_track_ids, "Test playlists must share tracks for valid test"

    # 3. Verify shared tracks weren't duplicated
    shared_track_ids = first_track_ids.intersection(second_track_ids)
    assert shared_track_ids, "Test playlists must share tracks for valid test"

    for spotify_id in shared_track_ids:
        # Check that track exists
        track = await track_repo.get_track("spotify", spotify_id)
        assert track is not None
        assert track.id is not None

        # Get playlists containing this track
        playlists = await track_repo.get_playlists_for_track(track.id)
        assert len(playlists) > 1, f"Track {spotify_id} should be in multiple playlists"

    # 4. Verify both playlists reference same track records
    first_saved = await playlist_repo.get_playlist("internal", first_playlist_id)
    second_saved = await playlist_repo.get_playlist("internal", second_playlist_id)

    assert first_saved is not None
    assert second_saved is not None

    # Check lengths match original playlists
    assert len(first_saved.tracks) == len(first_playlist.tracks)
    assert len(second_saved.tracks) == len(second_playlist.tracks)

    # Verify shared tracks have same IDs in both playlists
    first_db_ids = {
        t.id
        for t in first_saved.tracks
        if t.connector_track_ids.get("spotify") in shared_track_ids
    }
    second_db_ids = {
        t.id
        for t in second_saved.tracks
        if t.connector_track_ids.get("spotify") in shared_track_ids
    }
    assert first_db_ids == second_db_ids, "Shared tracks should have same database IDs"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_playlist_update(spotify: SpotifyConnector) -> None:
    """Test updating an existing playlist with new tracks.

    Tests the update flow:
    1. Create initial playlist
    2. Modify playlist to contain fewer tracks
    3. Verify database state reflects changes
    """
    TEST_PLAYLIST_ID = "1GIx0RMn8WRRzzw2GUDXql"  # 🛼 New galaxy

    async with get_session(rollback=True) as session:
        track_repo = TrackRepository(session)
        playlist_repo = PlaylistRepository(session)

        # Initial save
        domain_playlist = await spotify.get_spotify_playlist(TEST_PLAYLIST_ID)
        playlist_id = await playlist_repo.save_playlist(domain_playlist, track_repo)

        # Modify playlist (take first 5 tracks)
        modified_playlist = domain_playlist.with_tracks(domain_playlist.tracks[:5])
        await playlist_repo.update_playlist(playlist_id, modified_playlist, track_repo)

        # Verify update using the standard get_playlist method
        updated = await playlist_repo.get_playlist("spotify", TEST_PLAYLIST_ID)
        assert updated is not None
        assert len(updated.tracks) == 5
        assert [t.title for t in updated.tracks] == [
            t.title for t in modified_playlist.tracks
        ]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_playlist_operations(spotify: SpotifyConnector) -> None:
    """Test handling multiple concurrent playlist operations.

    This test specifically checks that we don't encounter greenlet errors
    when performing multiple async database operations in parallel.
    """
    PLAYLIST_IDS = [
        "54z4aq8BmCPox937mVrt9v",  # 🪢 43rd - Twin paradox
        "14GT9ahKyAR9SObC7GdwtO",  # 🤔 Interesting `25
    ]

    async with get_session(rollback=True) as session:
        track_repo = TrackRepository(session)
        playlist_repo = PlaylistRepository(session)

        # Fetch both playlists concurrently
        import asyncio

        domain_playlists = await asyncio.gather(
            *[spotify.get_spotify_playlist(pid) for pid in PLAYLIST_IDS],
        )

        # Save playlists sequentially (since they share the same session)
        playlist_ids = []
        for playlist in domain_playlists:
            playlist_id = await playlist_repo.save_playlist(playlist, track_repo)
            playlist_ids.append(playlist_id)

        # Fetch saved playlists concurrently
        saved_playlists = await asyncio.gather(
            *[playlist_repo.get_playlist("internal", pid) for pid in playlist_ids],
        )

        # Verify all playlists were saved correctly
        for original, saved in zip(domain_playlists, saved_playlists, strict=False):
            assert saved is not None
            assert saved.name == original.name
            assert len(saved.tracks) == len(original.tracks)
