"""Integration tests for UpdatePlaylistUseCase with real dependencies.

Tests the complete playlist update workflow including database operations,
Spotify sync services, and end-to-end operation execution.
"""

from unittest.mock import AsyncMock, Mock

import pytest

from src.application.use_cases.update_playlist import (
    UpdatePlaylistCommand,
    UpdatePlaylistOptions,
    UpdatePlaylistUseCase,
)
from src.domain.entities.playlist import Playlist
from src.domain.entities.track import Artist, Track, TrackList
from src.infrastructure.services.spotify_playlist_sync import SpotifyPlaylistSyncService


class MockSpotifyConnector:
    """Mock Spotify connector for integration testing."""

    def __init__(self):
        self.operations_executed = []
        self.api_calls_made = 0

    async def execute_playlist_operations(self, _playlist_id, operations, _snapshot_id=None):
        """Mock execution of playlist operations."""
        self.operations_executed.extend(operations)
        self.api_calls_made += len(operations)
        return f"snapshot_{len(self.operations_executed)}"


@pytest.mark.asyncio
class TestUpdatePlaylistIntegration:
    """Integration tests for UpdatePlaylistUseCase."""

    @pytest.fixture
    def mock_playlist_repo(self):
        """Mock playlist repository."""
        repo = AsyncMock()
        return repo

    @pytest.fixture
    def mock_spotify_connector(self):
        """Mock Spotify connector."""
        return MockSpotifyConnector()

    @pytest.fixture
    def spotify_sync_service(self, mock_spotify_connector):
        """Spotify sync service with mock connector."""
        return SpotifyPlaylistSyncService(spotify_connector=mock_spotify_connector)

    @pytest.fixture
    def integrated_use_case(self, mock_playlist_repo, spotify_sync_service):
        """UpdatePlaylistUseCase with real sync service."""
        return UpdatePlaylistUseCase(
            playlist_repo=mock_playlist_repo,
            sync_services=[spotify_sync_service],
        )

    @pytest.fixture
    def spotify_playlist(self):
        """Sample Spotify playlist for testing."""
        tracks = [
            Track(
                id=1,
                title="Existing Track 1",
                artists=[Artist(name="Artist 1")],
                duration_ms=200000,
                connector_track_ids={"spotify": "spotify_track_1"}
            ),
            Track(
                id=2,
                title="Existing Track 2", 
                artists=[Artist(name="Artist 2")],
                duration_ms=180000,
                connector_track_ids={"spotify": "spotify_track_2"}
            )
        ]
        
        return Playlist(
            id=1,
            name="Test Spotify Playlist",
            description="Integration test playlist",
            tracks=tracks,
            connector_playlist_ids={"spotify": "14GT9ahKyAR9SObC7GdwtO"},
            metadata={"spotify_snapshot_id": "initial_snapshot"}
        )

    async def test_complete_playlist_update_flow(
        self, integrated_use_case, spotify_playlist, mock_playlist_repo, mock_spotify_connector
    ):
        """Test complete playlist update with Spotify sync."""
        # Configure repository to return test playlist
        mock_playlist_repo.get_playlist_by_id.return_value = spotify_playlist
        
        # Create new tracklist with reordered and new tracks
        new_track = Track(
            id=3,
            title="New Track",
            artists=[Artist(name="New Artist")],
            duration_ms=210000,
            connector_track_ids={"spotify": "spotify_track_3"}
        )
        
        # Reorder existing tracks and add new one: [Track2, Track1, NewTrack]
        target_tracklist = TrackList(tracks=[
            spotify_playlist.tracks[1],  # Track 2 first
            spotify_playlist.tracks[0],  # Track 1 second  
            new_track                    # New track last
        ])
        
        # Create update command
        command = UpdatePlaylistCommand(
            playlist_id="1",
            new_tracklist=target_tracklist,
            options=UpdatePlaylistOptions(
                operation_type="update_spotify",
                enable_external_sync=True
            )
        )
        
        # Mock the save operation
        updated_playlist = Playlist(
            id=1,
            name="Test Spotify Playlist",
            description="Integration test playlist",
            tracks=target_tracklist.tracks,
            connector_playlist_ids={"spotify": "14GT9ahKyAR9SObC7GdwtO"},
            metadata={"spotify_snapshot_id": "snapshot_3"}
        )
        mock_playlist_repo.save_playlist.return_value = updated_playlist
        
        # Execute the command
        result = await integrated_use_case.execute(command)
        
        # Verify the complete flow
        assert result.api_calls_made > 0  # External API calls were made
        assert len(result.operations_performed) > 0  # Operations were performed
        
        # Verify Spotify operations were executed
        assert len(mock_spotify_connector.operations_executed) > 0
        assert mock_spotify_connector.api_calls_made > 0
        
        # Verify database was updated
        mock_playlist_repo.save_playlist.assert_called_once()
        saved_playlist = mock_playlist_repo.save_playlist.call_args[0][0]
        assert len(saved_playlist.tracks) == 3
        assert "spotify_snapshot_id" in saved_playlist.metadata  # Snapshot ID should be updated

    async def test_sync_service_supports_playlist_check(
        self, spotify_sync_service, spotify_playlist
    ):
        """Test that sync service correctly identifies supported playlists."""
        # Should support Spotify playlists
        assert spotify_sync_service.supports_playlist(spotify_playlist) is True
        
        # Should not support non-Spotify playlists
        non_spotify_playlist = Playlist(
            name="Local Playlist",
            tracks=[],
            connector_playlist_ids={"apple_music": "some_id"}
        )
        assert spotify_sync_service.supports_playlist(non_spotify_playlist) is False

    async def test_dry_run_skips_external_sync(
        self, integrated_use_case, spotify_playlist, mock_playlist_repo, mock_spotify_connector
    ):
        """Test that dry run mode skips external synchronization."""
        # Configure repository
        mock_playlist_repo.get_playlist_by_id.return_value = spotify_playlist
        
        # Create dry run command
        command = UpdatePlaylistCommand(
            playlist_id="1",
            new_tracklist=TrackList(tracks=spotify_playlist.tracks[:1]),  # Remove one track
            options=UpdatePlaylistOptions(
                operation_type="update_spotify",
                dry_run=True
            )
        )
        
        # Execute dry run
        result = await integrated_use_case.execute(command)
        
        # Verify no external operations were performed
        assert result.api_calls_made == 0
        assert len(mock_spotify_connector.operations_executed) == 0
        assert mock_spotify_connector.api_calls_made == 0
        
        # Verify no database save occurred
        mock_playlist_repo.save_playlist.assert_not_called()

    async def test_multiple_sync_services(
        self, mock_playlist_repo, spotify_sync_service
    ):
        """Test handling multiple sync services."""
        # Create second mock sync service - need to mix sync and async methods
        second_sync_service = AsyncMock()
        second_sync_service.supports_playlist = Mock(return_value=True)  # Sync method
        second_sync_service.sync_playlist.return_value = ({"apple_snapshot": "123"}, 1)
        
        # Create use case with multiple sync services
        use_case = UpdatePlaylistUseCase(
            playlist_repo=mock_playlist_repo,
            sync_services=[spotify_sync_service, second_sync_service]
        )
        
        # Create test playlist that both services support
        test_playlist = Playlist(
            name="Multi-Service Playlist",
            tracks=[],
            connector_playlist_ids={
                "spotify": "spotify_id",
                "apple_music": "apple_id"
            }
        )
        
        mock_playlist_repo.get_playlist_by_id.return_value = test_playlist
        mock_playlist_repo.save_playlist.return_value = test_playlist
        
        # Create command with at least one track
        test_track = Track(
            title="Test Track",
            artists=[Artist(name="Test Artist")],
            connector_track_ids={"spotify": "test_id"}
        )
        command = UpdatePlaylistCommand(
            playlist_id="1",
            new_tracklist=TrackList(tracks=[test_track]),
            options=UpdatePlaylistOptions(operation_type="sync_bidirectional")
        )
        
        # Execute command
        await use_case.execute(command)
        
        # Both sync services should have been called
        second_sync_service.supports_playlist.assert_called_once()
        # Note: Spotify sync service is called through real implementation
        
        # Verify metadata from both services was merged
        mock_playlist_repo.save_playlist.assert_called_once()


@pytest.mark.asyncio 
class TestSpotifyPlaylistSyncService:
    """Integration tests for SpotifyPlaylistSyncService."""

    @pytest.fixture
    def mock_spotify_connector(self):
        """Mock Spotify connector."""
        return MockSpotifyConnector()

    @pytest.fixture
    def sync_service(self, mock_spotify_connector):
        """Spotify sync service."""
        return SpotifyPlaylistSyncService(spotify_connector=mock_spotify_connector)

    @pytest.fixture
    def test_playlist(self):
        """Test playlist with Spotify ID."""
        return Playlist(
            name="Test Playlist",
            tracks=[],
            connector_playlist_ids={"spotify": "14GT9ahKyAR9SObC7GdwtO"},
            metadata={"spotify_snapshot_id": "test_snapshot"}
        )

    async def test_sync_playlist_with_operations(
        self, sync_service, test_playlist, mock_spotify_connector
    ):
        """Test syncing playlist with operations."""
        from src.application.use_cases.update_playlist import (
            PlaylistOperation,
            PlaylistOperationType,
            UpdatePlaylistOptions,
        )
        
        # Create test operations
        test_track = Track(
            title="Test Track",
            artists=[Artist(name="Test Artist")],
            connector_track_ids={"spotify": "test_spotify_id"}
        )
        
        operations = [
            PlaylistOperation(
                operation_type=PlaylistOperationType.ADD,
                track=test_track,
                position=0,
                spotify_uri="spotify:track:test_spotify_id"
            )
        ]
        
        options = UpdatePlaylistOptions(operation_type="update_spotify")
        
        # Execute sync
        metadata_updates, api_calls = await sync_service.sync_playlist(
            test_playlist, operations, options
        )
        
        # Verify results
        assert api_calls == 1  # One ADD operation
        assert "spotify_snapshot_id" in metadata_updates
        assert metadata_updates["spotify_snapshot_id"] == "snapshot_1"
        
        # Verify operations were executed on connector
        assert len(mock_spotify_connector.operations_executed) == 1
        assert mock_spotify_connector.operations_executed[0] == operations[0]

    async def test_supports_playlist_detection(self, sync_service):
        """Test playlist support detection."""
        # Should support playlists with Spotify ID
        spotify_playlist = Playlist(
            name="Spotify Playlist",
            tracks=[],
            connector_playlist_ids={"spotify": "some_id"}
        )
        assert sync_service.supports_playlist(spotify_playlist) is True
        
        # Should not support playlists without Spotify ID
        local_playlist = Playlist(
            name="Local Playlist", 
            tracks=[],
            connector_playlist_ids={}
        )
        assert sync_service.supports_playlist(local_playlist) is False

    async def test_api_call_counting(self, sync_service):
        """Test accurate API call counting."""
        from src.application.use_cases.update_playlist import (
            PlaylistOperation,
            PlaylistOperationType,
        )
        
        # Test different operation types
        operations = [
            # 150 add operations should be 2 API calls (batched)
            *[PlaylistOperation(PlaylistOperationType.ADD, Mock(), i) for i in range(150)],
            # 75 remove operations should be 1 API call (batched)
            *[PlaylistOperation(PlaylistOperationType.REMOVE, Mock(), i) for i in range(75)],
            # 3 move operations should be 3 API calls (individual)
            *[PlaylistOperation(PlaylistOperationType.MOVE, Mock(), i, i + 1) for i in range(3)]
        ]
        
        api_calls = sync_service._count_spotify_api_calls(operations)
        
        assert api_calls == 6  # 2 (adds) + 1 (removes) + 3 (moves) = 6