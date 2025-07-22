"""Comprehensive unit tests for SavePlaylistUseCase with TDD coverage.

Tests the complete playlist save workflow including command validation,
track enrichment, and persistence operations using mocked dependencies.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.application.use_cases.save_playlist import (
    BasicEnrichmentStrategy,
    EnrichmentConfig,
    PersistenceOptions,
    SavePlaylistCommand,
    SavePlaylistResult,
    SavePlaylistUseCase,
    TrackEnrichmentStrategy,
)
from src.domain.entities.playlist import Playlist
from src.domain.entities.track import Artist, Track, TrackList


class TestSavePlaylistCommand:
    """Test SavePlaylistCommand validation and behavior."""

    @pytest.fixture
    def valid_enrichment_config(self):
        """Valid enrichment configuration."""
        return EnrichmentConfig(
            enabled=True,
            primary_provider="spotify",
            fallback_providers=["lastfm"],
            timeout_seconds=30,
        )

    @pytest.fixture
    def valid_persistence_options(self):
        """Valid persistence options for create_internal operation."""
        return PersistenceOptions(
            operation_type="create_internal",
            playlist_name="Test Playlist",
            playlist_description="Test Description",
        )

    def test_command_creation_with_defaults(self, tracklist):
        """Test command creation with default values."""
        enrichment_config = EnrichmentConfig()
        persistence_options = PersistenceOptions(
            operation_type="create_internal",
            playlist_name="Test Playlist"
        )
        
        command = SavePlaylistCommand(
            tracklist=tracklist,
            enrichment_config=enrichment_config,
            persistence_options=persistence_options,
        )
        
        assert command.tracklist == tracklist
        assert command.enrichment_config.enabled is True
        assert command.persistence_options.operation_type == "create_internal"
        assert isinstance(command.timestamp, datetime)
        assert command.metadata == {}

    def test_command_validation_success(
        self, tracklist, valid_enrichment_config, valid_persistence_options
    ):
        """Test successful command validation."""
        command = SavePlaylistCommand(
            tracklist=tracklist,
            enrichment_config=valid_enrichment_config,
            persistence_options=valid_persistence_options,
        )
        
        assert command.validate() is True

    def test_command_validation_fails_empty_tracklist(
        self, valid_enrichment_config, valid_persistence_options
    ):
        """Test command validation fails with empty tracklist."""
        empty_tracklist = TrackList(tracks=[])
        command = SavePlaylistCommand(
            tracklist=empty_tracklist,
            enrichment_config=valid_enrichment_config,
            persistence_options=valid_persistence_options,
        )
        
        assert command.validate() is False

    def test_command_validation_fails_update_spotify_without_id(
        self, tracklist, valid_enrichment_config
    ):
        """Test command validation fails for update_spotify without playlist_id."""
        persistence_options = PersistenceOptions(
            operation_type="update_spotify",
            playlist_name="Test Playlist",
            spotify_playlist_id=None,  # Missing required ID
        )
        command = SavePlaylistCommand(
            tracklist=tracklist,
            enrichment_config=valid_enrichment_config,
            persistence_options=persistence_options,
        )
        
        assert command.validate() is False

    def test_command_validation_success_update_spotify_with_id(
        self, tracklist, valid_enrichment_config
    ):
        """Test command validation succeeds for update_spotify with playlist_id."""
        persistence_options = PersistenceOptions(
            operation_type="update_spotify",
            playlist_name="Test Playlist",
            spotify_playlist_id="spotify123",
        )
        command = SavePlaylistCommand(
            tracklist=tracklist,
            enrichment_config=valid_enrichment_config,
            persistence_options=persistence_options,
        )
        
        assert command.validate() is True


class TestBasicEnrichmentStrategy:
    """Test BasicEnrichmentStrategy implementation."""


    @pytest.mark.asyncio
    async def test_basic_enrichment_returns_unchanged_tracks(self, tracks):
        """Test that BasicEnrichmentStrategy returns tracks unchanged."""
        strategy = BasicEnrichmentStrategy()
        config = EnrichmentConfig(enabled=True)
        
        result = await strategy.enrich_tracks(tracks, config)
        
        assert result == tracks
        assert len(result) == 3  # Domain tracks fixture has 3 tracks
        assert result[0].title == "Track 1"
        assert result[1].title == "Track 2"


class TestSavePlaylistUseCase:
    """Test SavePlaylistUseCase with comprehensive coverage."""

    @pytest.fixture
    def mock_enrichment_strategy(self):
        """Mock enrichment strategy."""
        strategy = AsyncMock(spec=TrackEnrichmentStrategy)
        return strategy

    @pytest.fixture
    def mock_track_repo(self):
        """Mock track repository."""
        return AsyncMock()

    @pytest.fixture
    def mock_playlist_repo(self):
        """Mock playlist repository."""
        return AsyncMock()

    @pytest.fixture
    def use_case(self, mock_track_repo, mock_playlist_repo, mock_enrichment_strategy):
        """SavePlaylistUseCase with mocked dependencies."""
        return SavePlaylistUseCase(
            track_repo=mock_track_repo,
            playlist_repo=mock_playlist_repo,
            enrichment_strategy=mock_enrichment_strategy
        )


    @pytest.fixture
    def enriched_track(self):
        """Sample enriched track."""
        return Track(
            id=1,
            title="Test Track",
            artists=[Artist(name="Test Artist")],
            duration_ms=200000,
            connector_track_ids={"spotify": "spotify123"},  # Added by enrichment
        )

    @pytest.fixture
    def sample_command(self, track):
        """Valid SavePlaylistCommand for testing."""
        tracklist = TrackList(tracks=[track])
        enrichment_config = EnrichmentConfig(enabled=True)
        persistence_options = PersistenceOptions(
            operation_type="create_internal",
            playlist_name="Test Playlist",
            playlist_description="Test Description",
        )
        
        return SavePlaylistCommand(
            tracklist=tracklist,
            enrichment_config=enrichment_config,
            persistence_options=persistence_options,
        )

    @pytest.mark.asyncio
    async def test_execute_validation_failure(self, use_case):
        """Test that execute raises ValueError for invalid command."""
        # Create invalid command with empty tracklist
        invalid_command = SavePlaylistCommand(
            tracklist=TrackList(tracks=[]),
            enrichment_config=EnrichmentConfig(),
            persistence_options=PersistenceOptions(
                operation_type="create_internal",
                playlist_name="Test"
            ),
        )
        
        with pytest.raises(ValueError, match="Invalid command: failed business rule validation"):
            await use_case.execute(invalid_command)

    @pytest.mark.asyncio
    async def test_execute_enrichment_disabled(
        self, use_case, track, mock_enrichment_strategy, mock_track_repo, mock_playlist_repo
    ):
        """Test execution with enrichment disabled."""
        # Configure repository mocks
        mock_track_repo.save_track = AsyncMock(return_value=track)
        
        saved_playlist = Playlist(
            id=1,
            name="Test Playlist",
            description="Test Description",
            tracks=[track],
        )
        mock_playlist_repo.save_playlist = AsyncMock(return_value=saved_playlist)
        
        # Create command with enrichment disabled
        command = SavePlaylistCommand(
            tracklist=TrackList(tracks=[track]),
            enrichment_config=EnrichmentConfig(enabled=False),
            persistence_options=PersistenceOptions(
                operation_type="create_internal",
                playlist_name="Test Playlist",
                playlist_description="Test Description",
            ),
        )
        
        result = await use_case.execute(command)
        
        # Verify enrichment strategy was not called
        mock_enrichment_strategy.enrich_tracks.assert_not_called()
        
        # Verify result
        assert isinstance(result, SavePlaylistResult)
        assert result.playlist.name == "Test Playlist"
        assert result.track_count == 1
        assert result.operation_type == "create_internal"

    @pytest.mark.asyncio
    async def test_execute_enrichment_enabled(
        self, use_case, track, enriched_track, 
        mock_enrichment_strategy, sample_command, mock_track_repo, mock_playlist_repo
    ):
        """Test execution with enrichment enabled."""
        # Configure enrichment strategy
        mock_enrichment_strategy.enrich_tracks.return_value = [enriched_track]
        
        # Configure repository mocks
        mock_track_repo.save_track = AsyncMock(return_value=enriched_track)
        
        saved_playlist = Playlist(
            id=1,
            name="Test Playlist",
            description="Test Description", 
            tracks=[enriched_track],
        )
        mock_playlist_repo.save_playlist = AsyncMock(return_value=saved_playlist)
        
        result = await use_case.execute(sample_command)
        
        # Verify enrichment strategy was called
        mock_enrichment_strategy.enrich_tracks.assert_called_once_with(
            [track], sample_command.enrichment_config
        )
        
        # Verify result contains enriched track
        assert isinstance(result, SavePlaylistResult)
        assert result.playlist.name == "Test Playlist"
        assert result.track_count == 1
        assert result.enriched_tracks[0].connector_track_ids["spotify"] == "spotify123"

    @pytest.mark.asyncio
    async def test_execute_create_spotify_operation(
        self, use_case, track, mock_enrichment_strategy, mock_track_repo, mock_playlist_repo
    ):
        """Test execution with create_spotify operation type."""
        # Configure mocks
        mock_enrichment_strategy.enrich_tracks.return_value = [track]
        mock_track_repo.save_track = AsyncMock(return_value=track)
        
        saved_playlist = Playlist(
            id=1,
            name="Test Playlist",
            description="Test Description",
            tracks=[track],
            connector_playlist_ids={"spotify": "spotify123"},
        )
        mock_playlist_repo.save_playlist = AsyncMock(return_value=saved_playlist)
        
        # Create command for Spotify operation
        command = SavePlaylistCommand(
            tracklist=TrackList(tracks=[track]),
            enrichment_config=EnrichmentConfig(enabled=True),
            persistence_options=PersistenceOptions(
                operation_type="create_spotify",
                playlist_name="Test Playlist",
                spotify_playlist_id="spotify123",
            ),
        )
        
        result = await use_case.execute(command)
        
        # Verify result
        assert result.operation_type == "create_spotify"
        assert result.playlist.connector_playlist_ids == {"spotify": "spotify123"}

    @pytest.mark.asyncio
    async def test_execute_track_persistence_error_handling(
        self, use_case, track, mock_enrichment_strategy, mock_track_repo, mock_playlist_repo
    ):
        """Test error handling during track persistence."""
        # Configure enrichment strategy
        mock_enrichment_strategy.enrich_tracks.return_value = [track]
        
        # Configure track repository to fail
        mock_track_repo.save_track = AsyncMock(side_effect=Exception("Database error"))
        
        saved_playlist = Playlist(
            id=1,
            name="Test Playlist",
            description="Test Description",
            tracks=[track],  # Original track preserved
        )
        mock_playlist_repo.save_playlist = AsyncMock(return_value=saved_playlist)
        
        command = SavePlaylistCommand(
            tracklist=TrackList(tracks=[track]),
            enrichment_config=EnrichmentConfig(enabled=True),
            persistence_options=PersistenceOptions(
                operation_type="create_internal",
                playlist_name="Test Playlist",
                fail_on_track_error=False,  # Allow graceful degradation
            ),
        )
        
        result = await use_case.execute(command)
        
        # Verify operation completed despite track persistence error
        assert isinstance(result, SavePlaylistResult)
        assert result.track_count == 1