"""Tests for refactored SpotifyImportService using BaseImportService template method pattern."""

from datetime import UTC, datetime
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest

from src.domain.entities import OperationResult, TrackPlay
from src.infrastructure.connectors.spotify_personal_data import SpotifyPlayRecord


class TestSpotifyImportServiceRefactored:
    """Test suite for refactored SpotifyImportService using template method pattern."""

    @pytest.fixture
    def mock_repositories(self):
        """Mock track repositories."""
        repositories = Mock()
        repositories.plays = AsyncMock()
        repositories.plays.bulk_insert_plays = AsyncMock(return_value=3)
        repositories.core = AsyncMock()
        repositories.connector = AsyncMock()
        return repositories

    @pytest.fixture
    def mock_spotify_connector(self):
        """Mock Spotify connector."""
        connector = AsyncMock()
        return connector

    @pytest.fixture
    def mock_play_resolver(self):
        """Mock Spotify play resolver."""
        resolver = AsyncMock()
        resolver.resolve_with_fallback = AsyncMock(return_value={
            "spotify:track:123": Mock(
                track_id=1,
                resolution_method="direct_id",
                confidence=95,
                metadata={"source": "api"}
            ),
            "spotify:track:456": Mock(
                track_id=2,
                resolution_method="search_match",
                confidence=85,
                metadata={"source": "search"}
            ),
            "spotify:track:789": Mock(
                track_id=None,
                resolution_method="preserved_metadata",
                confidence=0,
                metadata={"source": "preserved"}
            ),
        })
        return resolver

    @pytest.fixture
    def service(self, mock_repositories, mock_spotify_connector, mock_play_resolver):
        """Create refactored service instance."""
        from src.infrastructure.services.spotify_import import SpotifyImportService
        service = SpotifyImportService(mock_repositories)
        service.spotify_connector = mock_spotify_connector
        service.resolver = mock_play_resolver
        return service

    @pytest.fixture
    def sample_spotify_records(self):
        """Sample Spotify play records."""
        return [
            SpotifyPlayRecord(
                timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
                track_uri="spotify:track:123",
                track_name="Test Song 1",
                artist_name="Test Artist 1",
                album_name="Test Album 1",
                ms_played=180000,
                platform="ios",
                country="US",
                reason_start="fwdbtn",
                reason_end="trackdone",
                shuffle=True,
                skipped=False,
                offline=False,
                incognito_mode=False
            ),
            SpotifyPlayRecord(
                timestamp=datetime(2024, 1, 1, 13, 0, 0, tzinfo=UTC),
                track_uri="spotify:track:456",
                track_name="Test Song 2",
                artist_name="Test Artist 2",
                album_name="Test Album 2",
                ms_played=240000,
                platform="web_player",
                country="US",
                reason_start="clickrow",
                reason_end="endplay",
                shuffle=False,
                skipped=True,
                offline=False,
                incognito_mode=False
            ),
            SpotifyPlayRecord(
                timestamp=datetime(2024, 1, 1, 14, 0, 0, tzinfo=UTC),
                track_uri="spotify:track:789",
                track_name="Test Song 3",
                artist_name="Test Artist 3",
                album_name="Test Album 3",
                ms_played=60000,
                platform="android",
                country="US",
                reason_start="trackdone",
                reason_end="trackdone",
                shuffle=False,
                skipped=False,
                offline=True,
                incognito_mode=True
            ),
        ]

    @pytest.fixture
    def temp_spotify_file(self, tmp_path, sample_spotify_records):
        """Create temporary Spotify export file."""
        file_path = tmp_path / "test_spotify_export.json"
        # Convert SpotifyPlayRecord objects to raw JSON format
        raw_data = [{
                "ts": record.timestamp.isoformat().replace("+00:00", "Z"),
                "spotify_track_uri": record.track_uri,
                "master_metadata_track_name": record.track_name,
                "master_metadata_album_artist_name": record.artist_name,
                "master_metadata_album_album_name": record.album_name,
                "ms_played": record.ms_played,
                "platform": record.platform,
                "conn_country": record.country,
                "reason_start": record.reason_start,
                "reason_end": record.reason_end,
                "shuffle": record.shuffle,
                "skipped": record.skipped,
                "offline": record.offline,
                "incognito_mode": record.incognito_mode,
            } for record in sample_spotify_records]
        
        with open(file_path, "w") as f:
            json.dump(raw_data, f)
        return file_path

    async def test_import_from_file_uses_template_method(
        self, service, temp_spotify_file, sample_spotify_records, mock_repositories
    ):
        """Test that import_from_file delegates to template method."""
        # Mock file parsing to return our sample records
        with patch("src.infrastructure.services.spotify_import.parse_spotify_personal_data") as mock_parse:
            mock_parse.return_value = sample_spotify_records
            
            # Act: Import from file
            result = await service.import_from_file(temp_spotify_file)
            
            # Assert: Template method was used (inherits from BaseImportService)
            assert isinstance(result, OperationResult)
            assert result.operation_name == "Spotify Import"
            assert result.plays_processed == 3
            assert result.imported_count == 3
            
            # Assert: File was parsed
            mock_parse.assert_called_once_with(temp_spotify_file)
            
            # Assert: Plays were saved to database
            mock_repositories.plays.bulk_insert_plays.assert_called_once()
            saved_plays = mock_repositories.plays.bulk_insert_plays.call_args[0][0]
            assert len(saved_plays) == 3
            assert all(isinstance(play, TrackPlay) for play in saved_plays)

    async def test_fetch_data_strategy_parses_json_file(
        self, service, temp_spotify_file, sample_spotify_records
    ):
        """Test that _fetch_data strategy correctly parses JSON file."""
        # Mock file parsing
        with patch("src.infrastructure.services.spotify_import.parse_spotify_personal_data") as mock_parse:
            mock_parse.return_value = sample_spotify_records
            
            # Act: Call fetch data strategy directly
            raw_data = await service._fetch_data(file_path=temp_spotify_file)
            
            # Assert: File was parsed and data returned
            assert raw_data == sample_spotify_records
            mock_parse.assert_called_once_with(temp_spotify_file)

    async def test_process_data_strategy_creates_track_plays_with_resolution(
        self, service, sample_spotify_records, mock_play_resolver
    ):
        """Test that _process_data strategy creates TrackPlay objects with resolution."""
        batch_id = str(uuid4())
        import_timestamp = datetime.now(UTC)
        
        # Act: Call process data strategy directly
        track_plays = await service._process_data(
            raw_data=sample_spotify_records,
            batch_id=batch_id,
            import_timestamp=import_timestamp
        )
        
        # Assert: Resolution was called
        mock_play_resolver.resolve_with_fallback.assert_called_once_with(sample_spotify_records)
        
        # Assert: TrackPlay objects were created
        assert len(track_plays) == 3
        assert all(isinstance(play, TrackPlay) for play in track_plays)
        
        # Assert: TrackPlay objects have correct metadata
        for i, play in enumerate(track_plays):
            assert play.service == "spotify"
            assert play.import_batch_id == batch_id
            assert play.import_timestamp == import_timestamp
            assert play.import_source == "spotify_export"
            assert play.played_at == sample_spotify_records[i].timestamp
            assert play.ms_played == sample_spotify_records[i].ms_played
            
            # Assert: Resolution info is in context
            assert "resolution_method" in play.context
            assert "resolution_confidence" in play.context
            assert "spotify_track_uri" in play.context
            assert play.context["spotify_track_uri"] == sample_spotify_records[i].track_uri

    async def test_process_data_preserves_spotify_behavioral_metadata(
        self, service, sample_spotify_records
    ):
        """Test that processing preserves all Spotify behavioral metadata."""
        batch_id = str(uuid4())
        import_timestamp = datetime.now(UTC)
        
        # Act: Process data
        track_plays = await service._process_data(
            raw_data=sample_spotify_records,
            batch_id=batch_id,
            import_timestamp=import_timestamp
        )
        
        # Assert: All Spotify-specific metadata is preserved
        for i, play in enumerate(track_plays):
            context = play.context
            record = sample_spotify_records[i]
            
            # Behavioral metadata
            assert context["platform"] == record.platform
            assert context["country"] == record.country
            assert context["reason_start"] == record.reason_start
            assert context["reason_end"] == record.reason_end
            assert context["shuffle"] == record.shuffle
            assert context["skipped"] == record.skipped
            assert context["offline"] == record.offline
            assert context["incognito_mode"] == record.incognito_mode
            
            # Original track metadata
            assert context["track_name"] == record.track_name
            assert context["artist_name"] == record.artist_name
            assert context["album_name"] == record.album_name

    async def test_handle_checkpoints_no_op_for_file_imports(self, service, sample_spotify_records):
        """Test that _handle_checkpoints is no-op for file imports."""
        # Act: Call checkpoint handling (should be no-op)
        await service._handle_checkpoints(raw_data=sample_spotify_records)
        
        # Assert: No exceptions raised, method completes successfully
        # For file imports, checkpoints are not relevant

    async def test_resolution_statistics_included_in_result(
        self, service, temp_spotify_file, sample_spotify_records
    ):
        """Test that resolution statistics are included in operation result."""
        with patch("src.infrastructure.services.spotify_import.parse_spotify_personal_data") as mock_parse:
            mock_parse.return_value = sample_spotify_records
            
            # Act: Import file
            result = await service.import_from_file(temp_spotify_file)
            
            # Assert: Resolution statistics are included
            metrics = result.play_metrics
            assert "resolution_stats" in metrics
            
            resolution_stats = metrics["resolution_stats"]
            assert resolution_stats["direct_id"] == 1
            assert resolution_stats["search_match"] == 1
            assert resolution_stats["preserved_metadata"] == 1
            assert resolution_stats["total_with_track_id"] == 2
            
            # Assert: Resolution rate calculated
            assert "resolution_rate_percent" in metrics
            assert metrics["resolution_rate_percent"] == pytest.approx(66.7, rel=0.1)

    async def test_affected_tracks_included_in_result(
        self, service, temp_spotify_file, sample_spotify_records
    ):
        """Test that affected tracks are included in operation result."""
        with patch("src.infrastructure.services.spotify_import.parse_spotify_personal_data") as mock_parse:
            mock_parse.return_value = sample_spotify_records
            
            # Act: Import file
            result = await service.import_from_file(temp_spotify_file)
            
            # Assert: Affected tracks are included
            assert hasattr(result, 'tracks')
            assert len(result.tracks) == 2  # Only tracks with resolved IDs
            
            # Assert: Track objects have IDs from resolution
            track_ids = {track.id for track in result.tracks}
            assert track_ids == {1, 2}  # IDs from mock resolver

    async def test_error_handling_preserves_template_method_behavior(
        self, service, tmp_path
    ):
        """Test that error handling follows template method pattern."""
        # Arrange: Create invalid JSON file
        invalid_file = tmp_path / "invalid.json"
        invalid_file.write_text("invalid json content")
        
        # Act: Import invalid file
        result = await service.import_from_file(invalid_file)
        
        # Assert: Error result follows template format
        assert result.operation_name == "Spotify Import"
        assert result.plays_processed == 0
        assert result.error_count == 1
        assert result.imported_count == 0
        assert "errors" in result.play_metrics
        error_message = result.play_metrics["errors"][0]
        assert "Spotify Import failed:" in error_message
        assert ("JSON" in error_message or "json" in error_message or "Expecting value" in error_message)

    async def test_file_not_found_error_handling(self, service):
        """Test error handling for non-existent files."""
        non_existent_file = Path("/non/existent/file.json")
        
        # Act: Import non-existent file
        result = await service.import_from_file(non_existent_file)
        
        # Assert: File not found error handled gracefully
        assert result.operation_name == "Spotify Import"
        assert result.plays_processed == 0
        assert result.error_count == 1
        error_message = result.play_metrics["errors"][0]
        assert "Spotify Import failed:" in error_message
        assert ("File not found" in error_message or "No such file or directory" in error_message)

    async def test_progress_callback_integration_with_template(
        self, service, temp_spotify_file, sample_spotify_records
    ):
        """Test that progress callbacks integrate properly with template method."""
        with patch("src.infrastructure.services.spotify_import.parse_spotify_personal_data") as mock_parse:
            mock_parse.return_value = sample_spotify_records
            
            # Arrange: Mock progress callback
            progress_callback = Mock()
            
            # Act: Import with progress callback
            await service.import_from_file(temp_spotify_file, progress_callback=progress_callback)
            
            # Assert: Progress callback was called multiple times
            assert progress_callback.call_count >= 3
            
            # Assert: Progress goes from 0 to 100
            progress_calls = progress_callback.call_args_list
            first_progress = progress_calls[0][0][0]
            last_progress = progress_calls[-1][0][0]
            assert first_progress == 0
            assert last_progress == 100
            
            # Assert: Progress messages are Spotify-specific
            messages = [call[0][2] for call in progress_calls]
            assert any("Spotify" in msg or "export" in msg for msg in messages)

    async def test_empty_file_handling(self, service, tmp_path):
        """Test handling of empty Spotify export files."""
        # Arrange: Create empty JSON file
        empty_file = tmp_path / "empty.json"
        with open(empty_file, "w") as f:
            json.dump([], f)
        
        with patch("src.infrastructure.services.spotify_import.parse_spotify_personal_data") as mock_parse:
            mock_parse.return_value = []
            
            # Act: Import empty file
            result = await service.import_from_file(empty_file)
            
            # Assert: Empty result handled gracefully
            assert result.operation_name == "Spotify Import"
            assert result.plays_processed == 0
            assert result.imported_count == 0
            assert result.error_count == 0

    async def test_refactored_service_reduces_code_duplication(self, service):
        """Test that refactored service eliminates original code duplication."""
        # Assert: Service inherits from BaseImportService
        from src.infrastructure.services.base_import import BaseImportService
        assert isinstance(service, BaseImportService)
        
        # Assert: Template method is used for import workflow
        import inspect
        import_source = inspect.getsource(service.import_from_file)
        assert "import_data" in import_source  # Delegates to template method
        
        # Assert: Required abstract methods are implemented
        assert hasattr(service, '_fetch_data')
        assert hasattr(service, '_process_data')
        assert hasattr(service, '_handle_checkpoints')
        
        # Assert: Methods are async and callable
        assert inspect.iscoroutinefunction(service._fetch_data)
        assert inspect.iscoroutinefunction(service._process_data)
        assert inspect.iscoroutinefunction(service._handle_checkpoints)

    async def test_spotify_specific_result_metrics_preserved(
        self, service, temp_spotify_file, sample_spotify_records
    ):
        """Test that Spotify-specific result metrics are preserved in refactoring."""
        with patch("src.infrastructure.services.spotify_import.parse_spotify_personal_data") as mock_parse:
            mock_parse.return_value = sample_spotify_records
            
            # Act: Import file
            result = await service.import_from_file(temp_spotify_file)
            
            # Assert: Spotify-specific metrics are preserved
            metrics = result.play_metrics
            
            # Standard metrics from BaseImportService (unified interface)
            assert result.imported_count >= 0  # Direct property
            assert result.skipped_count >= 0   # Direct property
            assert result.error_count >= 0     # Direct property
            assert "batch_id" in metrics       # Metadata remains in play_metrics
            
            # Spotify-specific metrics
            assert "resolution_stats" in metrics
            assert "resolution_rate_percent" in metrics
            
            # Resolution stats breakdown
            resolution_stats = metrics["resolution_stats"]
            expected_keys = [
                "direct_id", "relinked_id", "search_match", 
                "preserved_metadata", "total_with_track_id"
            ]
            for key in expected_keys:
                assert key in resolution_stats