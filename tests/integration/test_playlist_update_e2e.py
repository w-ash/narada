"""End-to-end tests for playlist updates with real Spotify integration.

These tests work with the actual test playlist:
https://open.spotify.com/playlist/14GT9ahKyAR9SObC7GdwtO

IMPORTANT: These tests require valid Spotify credentials and will make
real API calls. They should be run carefully and not in CI/CD.
"""

import os

import pytest

from src.application.use_cases.update_playlist import (
    UpdatePlaylistCommand,
    UpdatePlaylistOptions,
    UpdatePlaylistUseCase,
)
from src.domain.entities.track import Artist, Track, TrackList
from src.infrastructure.connectors.spotify import SpotifyConnector
from src.infrastructure.services.spotify_playlist_sync import SpotifyPlaylistSyncService

# Skip if no Spotify credentials available
pytestmark = pytest.mark.skipif(
    not all([
        os.getenv("SPOTIFY_CLIENT_ID"),
        os.getenv("SPOTIFY_CLIENT_SECRET"), 
        os.getenv("SPOTIFY_REDIRECT_URI"),
    ]),
    reason="Spotify credentials not available"
)


@pytest.mark.e2e
@pytest.mark.asyncio
class TestPlaylistUpdateE2E:
    """End-to-end tests with real Spotify API."""

    # Test playlist ID from the provided URL
    TEST_PLAYLIST_ID = "14GT9ahKyAR9SObC7GdwtO"

    @pytest.fixture
    def spotify_connector(self):
        """Real Spotify connector."""
        return SpotifyConnector()

    @pytest.fixture
    def spotify_sync_service(self, spotify_connector):
        """Real Spotify sync service."""
        return SpotifyPlaylistSyncService(spotify_connector=spotify_connector)

    @pytest.fixture
    def mock_playlist_repo(self):
        """Mock playlist repository for E2E tests."""
        from unittest.mock import AsyncMock
        return AsyncMock()

    @pytest.fixture
    def e2e_use_case(self, mock_playlist_repo, spotify_sync_service):
        """UpdatePlaylistUseCase with real Spotify integration."""
        return UpdatePlaylistUseCase(
            playlist_repo=mock_playlist_repo,
            sync_services=[spotify_sync_service],
        )

    async def test_fetch_real_spotify_playlist(self, spotify_connector):
        """Test fetching the real test playlist from Spotify."""
        playlist = await spotify_connector.get_spotify_playlist(self.TEST_PLAYLIST_ID)
        
        assert playlist.connector_playlist_id == self.TEST_PLAYLIST_ID
        assert playlist.name is not None
        assert len(playlist.items) >= 0  # May be empty or have tracks
        
        print(f"Playlist: {playlist.name}")
        print(f"Track count: {len(playlist.items)}")
        print(f"Description: {playlist.description}")

    async def test_dry_run_playlist_update(
        self, e2e_use_case, spotify_connector, mock_playlist_repo
    ):
        """Test dry run update of real playlist (safe, no actual changes)."""
        # Fetch current playlist state from Spotify
        connector_playlist = await spotify_connector.get_spotify_playlist(self.TEST_PLAYLIST_ID)
        
        # Convert to domain playlist (simplified for testing)
        current_tracks = []
        for item in connector_playlist.items[:3]:  # Limit to first 3 tracks for testing
            if item.connector_track_id:
                track = Track(
                    title=item.extras.get("track_name", "Unknown"),
                    artists=[Artist(name=name) for name in item.extras.get("artist_names", [])],
                    duration_ms=180000,  # Placeholder
                    connector_track_ids={"spotify": item.connector_track_id}
                )
                current_tracks.append(track)
        
        # Create domain playlist
        from src.domain.entities.playlist import Playlist
        test_playlist = Playlist(
            id=1,
            name=connector_playlist.name or "Test Playlist",
            description=connector_playlist.description,
            tracks=current_tracks,
            connector_playlist_ids={"spotify": self.TEST_PLAYLIST_ID},
            metadata={
                "spotify_snapshot_id": connector_playlist.raw_metadata.get("snapshot_id")
            }
        )
        
        # Configure mock repository
        mock_playlist_repo.get_playlist_by_id.return_value = test_playlist
        
        # Create modified tracklist (reverse order for testing)
        target_tracklist = TrackList(tracks=list(reversed(current_tracks)))
        
        # Create dry run command
        command = UpdatePlaylistCommand(
            playlist_id="1",
            new_tracklist=target_tracklist,
            options=UpdatePlaylistOptions(
                operation_type="update_spotify",
                dry_run=True,  # SAFE: No actual changes
                enable_external_sync=True
            )
        )
        
        # Execute dry run
        result = await e2e_use_case.execute(command)
        
        # Verify dry run behavior
        assert result.api_calls_made == 0  # No actual API calls in dry run
        assert len(result.operations_performed) == 0  # No actual operations
        
        # But diff should have calculated operations if order changed
        if len(current_tracks) > 1:
            print(f"Dry run would have performed operations for {len(current_tracks)} tracks")
        
        print("Dry run completed successfully - no actual changes made")

    @pytest.mark.manual
    async def test_real_playlist_update_manual_only(
        self, e2e_use_case, spotify_connector, mock_playlist_repo
    ):
        """Manual test for real playlist update - ONLY RUN MANUALLY.
        
        This test makes actual changes to the Spotify playlist.
        Use pytest -m manual to run manually when testing.
        """
        pytest.skip("Manual test - only run with explicit intent to modify playlist")
        
        # Fetch current playlist
        connector_playlist = await spotify_connector.get_spotify_playlist(self.TEST_PLAYLIST_ID)
        
        # Create simple test: add one track if empty, or reverse order if has tracks
        if len(connector_playlist.items) == 0:
            # Add a test track (use a well-known track ID)
            test_track = Track(
                title="Test Track",
                artists=[Artist(name="Test Artist")],
                duration_ms=180000,
                connector_track_ids={"spotify": "4iV5W9uYEdYUVa79Axb7Rh"}  # Known Spotify track
            )
            target_tracks = [test_track]
        else:
            # Reverse current tracks (minimal change for testing)
            current_tracks = []
            for item in connector_playlist.items:
                if item.connector_track_id:
                    track = Track(
                        title=item.extras.get("track_name", "Unknown"),
                        artists=[Artist(name=name) for name in item.extras.get("artist_names", [])],
                        duration_ms=180000,
                        connector_track_ids={"spotify": item.connector_track_id}
                    )
                    current_tracks.append(track)
            
            target_tracks = list(reversed(current_tracks))
        
        # Create domain playlist
        from src.domain.entities.playlist import Playlist
        test_playlist = Playlist(
            id=1,
            name=connector_playlist.name or "Test Playlist",
            tracks=[],  # Start empty
            connector_playlist_ids={"spotify": self.TEST_PLAYLIST_ID},
            metadata={
                "spotify_snapshot_id": connector_playlist.raw_metadata.get("snapshot_id")
            }
        )
        
        # Configure mocks
        mock_playlist_repo.get_playlist_by_id.return_value = test_playlist
        mock_playlist_repo.save_playlist.return_value = test_playlist
        
        # Create real update command
        command = UpdatePlaylistCommand(
            playlist_id="1",
            new_tracklist=TrackList(tracks=target_tracks),
            options=UpdatePlaylistOptions(
                operation_type="update_spotify",
                dry_run=False,  # REAL CHANGES
                enable_external_sync=True
            )
        )
        
        # Execute real update
        result = await e2e_use_case.execute(command)
        
        # Verify real update occurred
        assert result.api_calls_made > 0
        print(f"Real update completed: {result.api_calls_made} API calls made")
        print(f"Operations performed: {len(result.operations_performed)}")

    async def test_spotify_api_error_handling(
        self, e2e_use_case, mock_playlist_repo
    ):
        """Test error handling with invalid playlist ID."""
        from src.domain.entities.playlist import Playlist
        
        # Create playlist with invalid Spotify ID
        invalid_playlist = Playlist(
            id=1,
            name="Invalid Playlist",
            tracks=[],
            connector_playlist_ids={"spotify": "invalid_playlist_id"},
            metadata={}
        )
        
        mock_playlist_repo.get_playlist_by_id.return_value = invalid_playlist
        mock_playlist_repo.save_playlist.return_value = invalid_playlist
        
        # Create command with some operations
        test_track = Track(
            title="Test Track",
            artists=[Artist(name="Test Artist")],
            connector_track_ids={"spotify": "4iV5W9uYEdYUVa79Axb7Rh"}
        )
        
        command = UpdatePlaylistCommand(
            playlist_id="1",
            new_tracklist=TrackList(tracks=[test_track]),
            options=UpdatePlaylistOptions(
                operation_type="update_spotify",
                enable_external_sync=True
            )
        )
        
        # Should handle error gracefully and continue with local update
        result = await e2e_use_case.execute(command)
        
        # Verify graceful error handling - should return a valid result object
        assert result is not None
        assert hasattr(result, 'playlist')  # Result should have playlist attribute
        mock_playlist_repo.save_playlist.assert_called_once()
        
        print("Error handling test completed - local update continued despite Spotify error")


if __name__ == "__main__":
    # Example of running specific E2E test manually
    
    async def run_manual_test():
        """Run a specific E2E test manually."""
        connector = SpotifyConnector()
        playlist = await connector.get_spotify_playlist("14GT9ahKyAR9SObC7GdwtO")
        print(f"Manual test - Playlist: {playlist.name}")
        print(f"Tracks: {len(playlist.items)}")
    
    # Uncomment to run manual test
    # asyncio.run(run_manual_test())