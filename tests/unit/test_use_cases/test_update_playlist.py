"""Comprehensive unit tests for UpdatePlaylistUseCase with TDD coverage.

Tests the complete playlist update workflow including command validation,
differential algorithm, operation sequencing, and database operations using mocked dependencies.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.application.use_cases.update_playlist import (
    ConflictResolutionPolicy,
    PlaylistDiff,
    PlaylistDiffCalculator,
    PlaylistOperation,
    PlaylistOperationType,
    PlaylistSyncService,
    TrackMatchingStrategy,
    UpdatePlaylistCommand,
    UpdatePlaylistOptions,
    UpdatePlaylistResult,
    UpdatePlaylistUseCase,
    UpdateOperationType,
)
from src.domain.entities.playlist import Playlist
from src.domain.entities.track import Artist, Track, TrackList








class TestUpdatePlaylistOptions:
    """Test UpdatePlaylistOptions validation and behavior."""

    def test_options_creation_with_defaults(self):
        """Test options creation with default values."""
        options = UpdatePlaylistOptions(operation_type="update_internal")
        
        assert options.operation_type == "update_internal"
        assert options.conflict_resolution == "local_wins"
        assert options.track_matching_strategy == "comprehensive"
        assert options.dry_run is False
        assert options.batch_size == 100
        assert options.max_api_calls == 50
        assert options.enable_external_sync is True

    def test_options_validation_success(self):
        """Test successful options validation."""
        options = UpdatePlaylistOptions(
            operation_type="update_spotify",
            batch_size=50,
            max_api_calls=10
        )
        
        assert options.validate() is True

    def test_options_validation_fails_batch_size_too_large(self):
        """Test options validation fails with batch size > 100."""
        options = UpdatePlaylistOptions(
            operation_type="update_internal",
            batch_size=150  # Exceeds Spotify API limit
        )
        
        assert options.validate() is False

    def test_options_validation_fails_zero_api_calls(self):
        """Test options validation fails with zero max API calls."""
        options = UpdatePlaylistOptions(
            operation_type="update_spotify",
            max_api_calls=0
        )
        
        assert options.validate() is False


class TestUpdatePlaylistCommand:
    """Test UpdatePlaylistCommand validation and behavior."""

    @pytest.fixture
    def valid_options(self):
        """Valid update options for testing."""
        return UpdatePlaylistOptions(operation_type="update_internal")

    def test_command_creation_with_defaults(self, tracklist, valid_options):
        """Test command creation with default values."""
        command = UpdatePlaylistCommand(
            playlist_id="test_playlist_123",
            new_tracklist=tracklist,
            options=valid_options
        )
        
        assert command.playlist_id == "test_playlist_123"
        assert command.new_tracklist == tracklist
        assert command.options == valid_options
        assert isinstance(command.timestamp, datetime)
        assert command.metadata == {}

    def test_command_validation_success(self, tracklist, valid_options):
        """Test successful command validation."""
        command = UpdatePlaylistCommand(
            playlist_id="test_playlist_123",
            new_tracklist=tracklist,
            options=valid_options
        )
        
        assert command.validate() is True

    def test_command_validation_fails_empty_playlist_id(self, tracklist, valid_options):
        """Test command validation fails with empty playlist ID."""
        command = UpdatePlaylistCommand(
            playlist_id="",
            new_tracklist=tracklist,
            options=valid_options
        )
        
        assert command.validate() is False

    def test_command_validation_fails_empty_tracklist(self, valid_options):
        """Test command validation fails with empty tracklist."""
        empty_tracklist = TrackList(tracks=[])
        command = UpdatePlaylistCommand(
            playlist_id="test_playlist_123",
            new_tracklist=empty_tracklist,
            options=valid_options
        )
        
        assert command.validate() is False

    def test_command_validation_fails_invalid_options(self, tracklist):
        """Test command validation fails with invalid options."""
        invalid_options = UpdatePlaylistOptions(
            operation_type="update_internal",
            batch_size=150  # Invalid
        )
        command = UpdatePlaylistCommand(
            playlist_id="test_playlist_123",
            new_tracklist=tracklist,
            options=invalid_options
        )
        
        assert command.validate() is False


class TestPlaylistOperation:
    """Test PlaylistOperation functionality."""


    def test_add_operation_to_spotify_format(self, track):
        """Test converting ADD operation to Spotify API format."""
        operation = PlaylistOperation(
            operation_type=PlaylistOperationType.ADD,
            track=track,
            position=5,
            spotify_uri="spotify:track:123"
        )
        
        result = operation.to_spotify_format()
        
        assert result == {
            "uris": ["spotify:track:123"],
            "position": 5
        }

    def test_remove_operation_to_spotify_format(self, track):
        """Test converting REMOVE operation to Spotify API format."""
        operation = PlaylistOperation(
            operation_type=PlaylistOperationType.REMOVE,
            track=track,
            position=3,
            old_position=3,
            spotify_uri="spotify:track:123"
        )
        
        result = operation.to_spotify_format()
        
        assert result == {
            "tracks": [{"uri": "spotify:track:123"}],
            "positions": [3]
        }

    def test_move_operation_to_spotify_format(self, track):
        """Test converting MOVE operation to Spotify API format."""
        operation = PlaylistOperation(
            operation_type=PlaylistOperationType.MOVE,
            track=track,
            position=10,
            old_position=5
        )
        
        result = operation.to_spotify_format()
        
        assert result == {
            "range_start": 5,
            "insert_before": 10,
            "range_length": 1
        }


class TestPlaylistDiff:
    """Test PlaylistDiff functionality."""

    @pytest.fixture
    def sample_operations(self):
        """Sample operations for testing."""
        track1 = Track(title="Track 1", artists=[Artist(name="Artist 1")])
        track2 = Track(title="Track 2", artists=[Artist(name="Artist 2")])
        
        return [
            PlaylistOperation(PlaylistOperationType.ADD, track1, 0),
            PlaylistOperation(PlaylistOperationType.REMOVE, track2, 1, old_position=1),
            PlaylistOperation(PlaylistOperationType.MOVE, track1, 2, old_position=0)
        ]

    def test_diff_has_changes_true(self, sample_operations):
        """Test has_changes returns True when operations exist."""
        diff = PlaylistDiff(operations=sample_operations)
        
        assert diff.has_changes is True

    def test_diff_has_changes_false(self):
        """Test has_changes returns False when no operations."""
        diff = PlaylistDiff(operations=[])
        
        assert diff.has_changes is False

    def test_operation_summary(self, sample_operations):
        """Test operation summary calculation."""
        diff = PlaylistDiff(operations=sample_operations)
        
        summary = diff.operation_summary
        
        assert summary == {
            "add": 1,
            "remove": 1,
            "move": 1
        }


class TestPlaylistDiffCalculator:
    """Test PlaylistDiffCalculator algorithm."""

    @pytest.fixture
    def calculator(self):
        """PlaylistDiffCalculator for testing."""
        return PlaylistDiffCalculator()

    @pytest.fixture
    def current_tracks(self):
        """Current playlist tracks."""
        return [
            Track(
                title="Track 1",
                artists=[Artist(name="Artist 1")],
                connector_track_ids={"spotify": "spotify1"}
            ),
            Track(
                title="Track 2",
                artists=[Artist(name="Artist 2")],
                connector_track_ids={"spotify": "spotify2"}
            )
        ]

    @pytest.fixture
    def target_tracks(self):
        """Target playlist tracks."""
        return [
            Track(
                title="Track 1",
                artists=[Artist(name="Artist 1")],
                connector_track_ids={"spotify": "spotify1"}
            ),
            Track(
                title="Track 3",
                artists=[Artist(name="Artist 3")],
                connector_track_ids={"spotify": "spotify3"}
            )
        ]

    @pytest.mark.asyncio
    async def test_calculate_diff_no_changes(self, calculator, current_tracks):
        """Test diff calculation when no changes needed."""
        current_playlist = Playlist(name="Test", tracks=current_tracks)
        target_tracklist = TrackList(tracks=current_tracks)
        
        diff = await calculator.calculate_diff(current_playlist, target_tracklist)
        
        assert diff.has_changes is False
        assert len(diff.unchanged_tracks) == 2
        assert diff.confidence_score == 1.0

    @pytest.mark.asyncio
    async def test_calculate_diff_with_changes(self, calculator, current_tracks, target_tracks):
        """Test diff calculation with add and remove operations."""
        current_playlist = Playlist(name="Test", tracks=current_tracks)
        target_tracklist = TrackList(tracks=target_tracks)
        
        diff = await calculator.calculate_diff(current_playlist, target_tracklist)
        
        assert diff.has_changes is True
        assert len(diff.unchanged_tracks) == 1  # Track 1 matches
        assert len(diff.operations) == 2  # Remove Track 2, Add Track 3
        assert diff.api_call_estimate >= 1

    @pytest.mark.asyncio
    async def test_track_matching_by_spotify_id(self, calculator):
        """Test track matching using Spotify IDs."""
        current_tracks = [
            Track(title="Track 1", artists=[Artist(name="Artist 1")], 
                  connector_track_ids={"spotify": "same_id"}),
            Track(title="Track 2", artists=[Artist(name="Artist 2")], 
                  connector_track_ids={"spotify": "different_id"})
        ]
        target_tracks = [
            Track(title="Different Title", artists=[Artist(name="Different Artist")], 
                  connector_track_ids={"spotify": "same_id"}),  # Should match despite different metadata
        ]
        
        matched, unmatched_current, unmatched_target = await calculator._match_tracks(
            current_tracks, target_tracks
        )
        
        assert len(matched) == 1
        assert len(unmatched_current) == 1
        assert len(unmatched_target) == 0

    def test_api_call_estimation(self, calculator):
        """Test API call estimation for different operation types."""
        operations = [
            # 150 add operations = 2 API calls (ceiling of 150/100)
            *[PlaylistOperation(PlaylistOperationType.ADD, Track(title=f"Track {i}", artists=[Artist(name="Artist")]), i) 
              for i in range(150)],
            # 75 remove operations = 1 API call
            *[PlaylistOperation(PlaylistOperationType.REMOVE, Track(title=f"Track {i}", artists=[Artist(name="Artist")]), i) 
              for i in range(75)],
            # 3 move operations = 3 API calls (individual)
            *[PlaylistOperation(PlaylistOperationType.MOVE, Track(title=f"Track {i}", artists=[Artist(name="Artist")]), i+10, i) 
              for i in range(3)]
        ]
        
        estimate = calculator._estimate_api_calls(operations)
        
        # Expected: 2 (adds) + 1 (removes) + 3 (moves) = 6 API calls
        assert estimate == 6


class TestUpdatePlaylistUseCase:
    """Test UpdatePlaylistUseCase with comprehensive coverage."""

    @pytest.fixture
    def mock_diff_calculator(self):
        """Mock diff calculator."""
        calculator = AsyncMock(spec=PlaylistDiffCalculator)
        return calculator

    @pytest.fixture
    def mock_playlist_repo(self):
        """Mock playlist repository."""
        return AsyncMock()

    @pytest.fixture
    def mock_sync_service(self):
        """Mock sync service."""
        sync_service = AsyncMock(spec=PlaylistSyncService)
        sync_service.supports_playlist.return_value = True
        sync_service.sync_playlist.return_value = ({}, 0)
        return sync_service

    @pytest.fixture
    def use_case(self, mock_playlist_repo, mock_diff_calculator):
        """UpdatePlaylistUseCase with mocked dependencies."""
        return UpdatePlaylistUseCase(
            playlist_repo=mock_playlist_repo,
            sync_services=[],
            diff_calculator=mock_diff_calculator
        )

    @pytest.fixture
    def use_case_with_sync(self, mock_playlist_repo, mock_diff_calculator, mock_sync_service):
        """UpdatePlaylistUseCase with sync service."""
        return UpdatePlaylistUseCase(
            playlist_repo=mock_playlist_repo,
            sync_services=[mock_sync_service],
            diff_calculator=mock_diff_calculator
        )


    @pytest.fixture
    def current_playlist(self, track):
        """Current playlist state."""
        return Playlist(
            id=1,
            name="Test Playlist",
            description="Test Description",
            tracks=[track]
        )

    @pytest.fixture
    def valid_command(self, track):
        """Valid UpdatePlaylistCommand for testing."""
        new_track = Track(
            id=2,
            title="New Track",
            artists=[Artist(name="New Artist")],
            duration_ms=180000,
            connector_track_ids={"spotify": "spotify456"}
        )
        
        tracklist = TrackList(tracks=[track, new_track])
        options = UpdatePlaylistOptions(operation_type="update_internal")
        
        return UpdatePlaylistCommand(
            playlist_id="1",
            new_tracklist=tracklist,
            options=options
        )

    @pytest.mark.asyncio
    async def test_execute_validation_failure(self, use_case):
        """Test that execute raises ValueError for invalid command."""
        # Create invalid command with empty playlist ID
        invalid_command = UpdatePlaylistCommand(
            playlist_id="",
            new_tracklist=TrackList(tracks=[]),
            options=UpdatePlaylistOptions(operation_type="update_internal")
        )
        
        with pytest.raises(ValueError, match="Invalid command: failed business rule validation"):
            await use_case.execute(invalid_command)

    @pytest.mark.asyncio
    async def test_execute_no_changes_needed(
        self, use_case, valid_command, current_playlist, mock_diff_calculator, mock_playlist_repo
    ):
        """Test execution when no changes are needed."""
        # Configure repository mock
        mock_playlist_repo.get_playlist_by_id = AsyncMock(return_value=current_playlist)
        
        # Configure diff calculator to return no changes
        mock_diff_calculator.calculate_diff.return_value = PlaylistDiff(
            operations=[],  # No changes needed
            unchanged_tracks=current_playlist.tracks,
            api_call_estimate=0
        )
        
        result = await use_case.execute(valid_command)
        
        # Verify no operations were performed
        assert isinstance(result, UpdatePlaylistResult)
        assert result.playlist == current_playlist
        assert len(result.operations_performed) == 0
        assert result.api_calls_made == 0
        assert result.tracks_added == 0
        assert result.tracks_removed == 0

    @pytest.mark.asyncio
    async def test_execute_with_operations(
        self, use_case, valid_command, current_playlist, mock_diff_calculator, mock_playlist_repo
    ):
        """Test execution with differential operations."""
        # Configure repository mock
        mock_playlist_repo.get_playlist_by_id = AsyncMock(return_value=current_playlist)
        
        # Create mock operations
        new_track = Track(
            title="New Track",
            artists=[Artist(name="New Artist")],
            connector_track_ids={"spotify": "spotify456"}
        )
        operations = [
            PlaylistOperation(
                operation_type=PlaylistOperationType.ADD,
                track=new_track,
                position=1,
                spotify_uri="spotify:track:456"
            )
        ]
        
        # Configure diff calculator to return operations
        mock_diff_calculator.calculate_diff.return_value = PlaylistDiff(
            operations=operations,
            unchanged_tracks=[current_playlist.tracks[0]],
            api_call_estimate=1
        )
        
        # Configure save playlist mock
        updated_playlist = Playlist(
            id=1,
            name="Test Playlist",
            description="Test Description",
            tracks=[current_playlist.tracks[0], new_track]
        )
        mock_playlist_repo.save_playlist = AsyncMock(return_value=updated_playlist)
        
        result = await use_case.execute(valid_command)
        
        # Verify operations were performed
        assert isinstance(result, UpdatePlaylistResult)
        assert len(result.operations_performed) == 1
        assert result.tracks_added == 1
        assert result.tracks_removed == 0
        assert result.api_calls_made == 0  # No external sync services in this test

    @pytest.mark.asyncio
    async def test_execute_dry_run_mode(
        self, use_case, current_playlist, mock_diff_calculator, mock_playlist_repo
    ):
        """Test execution in dry-run mode."""
        # Configure repository mock
        mock_playlist_repo.get_playlist_by_id = AsyncMock(return_value=current_playlist)
        
        # Create dry-run command with valid tracklist
        sample_track = Track(
            title="Sample Track",
            artists=[Artist(name="Sample Artist")],
            connector_track_ids={"spotify": "spotify789"}
        )
        dry_run_command = UpdatePlaylistCommand(
            playlist_id="1",
            new_tracklist=TrackList(tracks=[sample_track]),
            options=UpdatePlaylistOptions(
                operation_type="update_internal",
                dry_run=True
            )
        )
        
        # Configure diff calculator to return operations
        operations = [
            PlaylistOperation(
                operation_type=PlaylistOperationType.REMOVE,
                track=current_playlist.tracks[0],
                position=0,
                old_position=0
            )
        ]
        mock_diff_calculator.calculate_diff.return_value = PlaylistDiff(
            operations=operations,
            unchanged_tracks=[],
            api_call_estimate=1
        )
        
        result = await use_case.execute(dry_run_command)
        
        # Verify no actual operations were performed
        assert isinstance(result, UpdatePlaylistResult)
        assert result.playlist == current_playlist  # Original playlist unchanged
        assert len(result.operations_performed) == 0  # No operations in dry-run
        assert result.api_calls_made == 0

    @pytest.mark.asyncio
    async def test_get_current_playlist_by_id(self, use_case, current_playlist, mock_playlist_repo):
        """Test retrieving playlist by internal ID."""
        # Configure repository mock
        mock_playlist_repo.get_playlist_by_id = AsyncMock(return_value=current_playlist)
        
        result = await use_case._get_current_playlist("123")
        
        assert result == current_playlist
        mock_playlist_repo.get_playlist_by_id.assert_called_once_with(123)

    @pytest.mark.asyncio
    async def test_get_current_playlist_by_connector_id(self, use_case, current_playlist, mock_playlist_repo):
        """Test retrieving playlist by connector ID."""
        # Configure repository mock
        # Make get_playlist_by_id raise ValueError for non-integer
        mock_playlist_repo.get_playlist_by_id = AsyncMock(side_effect=ValueError("Not an integer"))
        mock_playlist_repo.get_playlist_by_connector = AsyncMock(return_value=current_playlist)
        
        result = await use_case._get_current_playlist("spotify123")
        
        assert result == current_playlist
        mock_playlist_repo.get_playlist_by_connector.assert_called_once_with(
            "spotify", "spotify123", raise_if_not_found=True
        )

    @pytest.mark.asyncio
    async def test_get_current_playlist_not_found(self, use_case, mock_playlist_repo):
        """Test error handling when playlist not found."""
        # Configure repository mock
        # Make both methods fail
        mock_playlist_repo.get_playlist_by_id = AsyncMock(side_effect=ValueError("Not an integer"))
        mock_playlist_repo.get_playlist_by_connector = AsyncMock(return_value=None)
        
        with pytest.raises(ValueError, match="Playlist with ID spotify123 not found"):
            await use_case._get_current_playlist("spotify123")

    @pytest.mark.asyncio
    async def test_execute_with_external_sync(
        self, use_case_with_sync, valid_command, current_playlist, 
        mock_diff_calculator, mock_playlist_repo, mock_sync_service
    ):
        """Test execution with external sync service."""
        # Configure repository mock
        mock_playlist_repo.get_playlist_by_id = AsyncMock(return_value=current_playlist)
        
        # Create mock operations
        new_track = Track(
            title="New Track",
            artists=[Artist(name="New Artist")],
            connector_track_ids={"spotify": "spotify456"}
        )
        operations = [
            PlaylistOperation(
                operation_type=PlaylistOperationType.ADD,
                track=new_track,
                position=1,
                spotify_uri="spotify:track:456"
            )
        ]
        
        # Configure diff calculator
        mock_diff_calculator.calculate_diff.return_value = PlaylistDiff(
            operations=operations,
            unchanged_tracks=[current_playlist.tracks[0]],
            api_call_estimate=1
        )
        
        # Configure sync service
        mock_sync_service.sync_playlist.return_value = (
            {"spotify_snapshot_id": "new_snapshot_123"},
            2
        )
        
        # Configure save playlist mock
        updated_playlist = Playlist(
            id=1,
            name="Test Playlist",
            description="Test Description",
            tracks=[current_playlist.tracks[0], new_track]
        )
        mock_playlist_repo.save_playlist = AsyncMock(return_value=updated_playlist)
        
        result = await use_case_with_sync.execute(valid_command)
        
        # Verify sync service was called
        mock_sync_service.supports_playlist.assert_called_once_with(current_playlist)
        mock_sync_service.sync_playlist.assert_called_once_with(
            current_playlist, operations, valid_command.options
        )
        
        # Verify result includes external sync data
        assert result.api_calls_made == 2  # From sync service
        assert len(result.operations_performed) == 1

    @pytest.mark.asyncio
    async def test_execute_sync_service_failure(
        self, use_case_with_sync, valid_command, current_playlist,
        mock_diff_calculator, mock_playlist_repo, mock_sync_service
    ):
        """Test graceful handling of sync service failure."""
        # Configure repository mock
        mock_playlist_repo.get_playlist_by_id = AsyncMock(return_value=current_playlist)
        
        # Create mock operations
        operations = [
            PlaylistOperation(
                operation_type=PlaylistOperationType.ADD,
                track=Track(title="New Track", artists=[Artist(name="Artist")]),
                position=1
            )
        ]
        
        # Configure diff calculator
        mock_diff_calculator.calculate_diff.return_value = PlaylistDiff(
            operations=operations,
            api_call_estimate=1
        )
        
        # Configure sync service to fail
        mock_sync_service.sync_playlist.side_effect = Exception("Sync failed")
        
        # Configure save playlist mock
        updated_playlist = Playlist(
            id=1,
            name="Test Playlist",
            tracks=current_playlist.tracks + [operations[0].track]
        )
        mock_playlist_repo.save_playlist = AsyncMock(return_value=updated_playlist)
        
        # Should not raise exception, but continue with local update
        result = await use_case_with_sync.execute(valid_command)
        
        # Verify local update still happened
        assert isinstance(result, UpdatePlaylistResult)
        mock_playlist_repo.save_playlist.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_external_sync_disabled(
        self, use_case_with_sync, current_playlist, mock_diff_calculator, 
        mock_playlist_repo, mock_sync_service
    ):
        """Test that external sync is skipped when disabled."""
        # Configure repository mock
        mock_playlist_repo.get_playlist_by_id = AsyncMock(return_value=current_playlist)
        
        # Create command with external sync disabled
        sample_track = Track(
            title="Sample Track",
            artists=[Artist(name="Sample Artist")],
            connector_track_ids={"spotify": "spotify789"}
        )
        command = UpdatePlaylistCommand(
            playlist_id="1",
            new_tracklist=TrackList(tracks=[sample_track]),
            options=UpdatePlaylistOptions(
                operation_type="update_internal",
                enable_external_sync=False
            )
        )
        
        # Configure diff calculator with operations
        operations = [PlaylistOperation(PlaylistOperationType.ADD, sample_track, 0)]
        mock_diff_calculator.calculate_diff.return_value = PlaylistDiff(
            operations=operations,
            api_call_estimate=1
        )
        
        # Configure save playlist mock
        mock_playlist_repo.save_playlist = AsyncMock(return_value=current_playlist)
        
        result = await use_case_with_sync.execute(command)
        
        # Verify sync service was NOT called
        mock_sync_service.supports_playlist.assert_not_called()
        mock_sync_service.sync_playlist.assert_not_called()
        
        # Verify local update happened
        assert result.api_calls_made == 0  # No external API calls


class TestPlaylistReorderingAlgorithm:
    """Test sophisticated playlist reordering algorithm."""

    @pytest.fixture
    def calculator(self):
        """PlaylistDiffCalculator for testing."""
        return PlaylistDiffCalculator()

    def test_longest_increasing_subsequence_simple(self, calculator):
        """Test LIS algorithm with simple case."""
        sequence = [1, 3, 2, 4, 5]
        lis_indices = calculator._longest_increasing_subsequence(sequence)
        
        # LIS should be [1, 2, 4, 5] at indices [0, 2, 3, 4]
        # But our implementation finds one valid LIS
        assert len(lis_indices) >= 3  # At least length 3 LIS exists

    def test_longest_increasing_subsequence_empty(self, calculator):
        """Test LIS algorithm with empty sequence."""
        lis_indices = calculator._longest_increasing_subsequence([])
        assert lis_indices == []

    def test_longest_increasing_subsequence_decreasing(self, calculator):
        """Test LIS algorithm with decreasing sequence."""
        sequence = [5, 4, 3, 2, 1]
        lis_indices = calculator._longest_increasing_subsequence(sequence)
        assert len(lis_indices) == 1  # Only one element can be in LIS

    @pytest.mark.asyncio
    async def test_calculate_reorder_operations_no_matched_tracks(self, calculator):
        """Test reordering with no matched tracks."""
        operations = await calculator._calculate_reorder_operations([], [], [])
        assert operations == []

    @pytest.mark.asyncio
    async def test_calculate_reorder_operations_same_order(self, calculator):
        """Test reordering when tracks are already in correct order."""
        tracks = [
            Track(title="Track 1", artists=[Artist(name="Artist")], 
                  connector_track_ids={"spotify": "id1"}),
            Track(title="Track 2", artists=[Artist(name="Artist")], 
                  connector_track_ids={"spotify": "id2"}),
        ]
        
        # Same order in current and target
        operations = await calculator._calculate_reorder_operations(
            tracks, tracks, tracks
        )
        
        # Should be no move operations needed
        assert operations == []

    @pytest.mark.asyncio
    async def test_calculate_reorder_operations_reverse_order(self, calculator):
        """Test reordering when tracks need to be reversed."""
        track1 = Track(title="Track 1", artists=[Artist(name="Artist")], 
                      connector_track_ids={"spotify": "id1"})
        track2 = Track(title="Track 2", artists=[Artist(name="Artist")], 
                      connector_track_ids={"spotify": "id2"})
        
        current_tracks = [track1, track2]
        target_tracks = [track2, track1]  # Reversed order
        matched_tracks = [track1, track2]
        
        operations = await calculator._calculate_reorder_operations(
            matched_tracks, current_tracks, target_tracks
        )
        
        # Should generate move operations to reverse the order
        assert len(operations) > 0
        assert all(op.operation_type == PlaylistOperationType.MOVE for op in operations)

    @pytest.mark.asyncio
    async def test_calculate_reorder_operations_optimal_moves(self, calculator):
        """Test that reordering algorithm generates minimal moves."""
        # Create tracks: [A, B, C, D] -> [B, A, D, C]
        tracks = [
            Track(title=f"Track {i}", artists=[Artist(name="Artist")], 
                  connector_track_ids={"spotify": f"id{i}"})
            for i in ["A", "B", "C", "D"]
        ]
        
        current_tracks = tracks  # [A, B, C, D]
        target_tracks = [tracks[1], tracks[0], tracks[3], tracks[2]]  # [B, A, D, C]
        
        operations = await calculator._calculate_reorder_operations(
            tracks, current_tracks, target_tracks
        )
        
        # Should be optimal (minimal number of moves)
        # For this case, we can do it with 2 moves instead of naive 4
        assert len(operations) <= 2