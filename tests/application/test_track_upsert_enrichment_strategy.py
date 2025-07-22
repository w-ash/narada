"""Tests for TrackUpsertEnrichmentStrategy."""

import pytest
from unittest.mock import AsyncMock, Mock

from src.application.use_cases.save_playlist import TrackUpsertEnrichmentStrategy
from src.domain.entities import Track, Artist
from src.infrastructure.persistence.repositories.track import TrackRepositories


@pytest.fixture
def mock_track_repo():
    """Create mock track repository."""
    return AsyncMock()


@pytest.fixture
def enrichment_strategy(mock_track_repo):
    """Create TrackUpsertEnrichmentStrategy instance."""
    return TrackUpsertEnrichmentStrategy(mock_track_repo)


@pytest.fixture
def sample_tracks():
    """Create sample tracks for testing."""
    return [
        Track(
            title="Home",
            artists=[Artist(name="Mac DeMarco")],
            album="This Old Dog",
            duration_ms=180000,
        ),
        Track(
            title="Falling",
            artists=[Artist(name="Chris Lake"), Artist(name="Bonobo")],
            album="Single",
            duration_ms=240000,
        ),
    ]


class TestTrackUpsertEnrichmentStrategy:
    """Test cases for TrackUpsertEnrichmentStrategy."""

    @pytest.mark.asyncio
    async def test_enrich_tracks_success(self, enrichment_strategy, mock_track_repo, sample_tracks):
        """Test successful track enrichment with upsert."""
        # Setup: Mock repository to return tracks with IDs
        enriched_track_1 = sample_tracks[0].with_id(1)
        enriched_track_2 = sample_tracks[1].with_id(2)
        
        mock_track_repo.save_track.side_effect = [
            enriched_track_1,
            enriched_track_2,
        ]

        # Execute
        config = Mock()  # EnrichmentConfig not needed for this strategy
        result = await enrichment_strategy.enrich_tracks(sample_tracks, config)

        # Verify
        assert len(result) == 2
        assert result[0].id == 1
        assert result[1].id == 2
        assert result[0].title == "Home"
        assert result[1].title == "Falling"

        # Verify repository was called for each track
        assert mock_track_repo.save_track.call_count == 2
        mock_track_repo.save_track.assert_any_call(sample_tracks[0])
        mock_track_repo.save_track.assert_any_call(sample_tracks[1])

    @pytest.mark.asyncio
    async def test_enrich_tracks_empty_list(self, enrichment_strategy, mock_track_repo):
        """Test enrichment with empty track list."""
        config = Mock()
        result = await enrichment_strategy.enrich_tracks([], config)

        assert result == []
        mock_track_repo.save_track.assert_not_called()

    @pytest.mark.asyncio
    async def test_enrich_tracks_repository_error(self, enrichment_strategy, mock_track_repo, sample_tracks):
        """Test handling of repository errors during upsert."""
        # Setup: First track succeeds, second fails
        enriched_track_1 = sample_tracks[0].with_id(1)
        mock_track_repo.save_track.side_effect = [
            enriched_track_1,
            Exception("Database connection error"),
        ]

        config = Mock()

        # Execute: Should handle the exception gracefully
        result = await enrichment_strategy.enrich_tracks(sample_tracks, config)

        # Verify: Both tracks returned, successful track has ID, failed track keeps original
        assert len(result) == 2
        assert result[0].id == 1  # Successful upsert
        assert result[0].title == "Home"
        assert result[1].id is None  # Failed upsert, original track preserved
        assert result[1].title == "Falling"

        # Verify both tracks were attempted
        assert mock_track_repo.save_track.call_count == 2

    @pytest.mark.asyncio
    async def test_enrich_tracks_preserves_track_order(self, enrichment_strategy, mock_track_repo):
        """Test that track order is preserved during enrichment."""
        # Create multiple tracks
        tracks = [
            Track(title=f"Track {i}", artists=[Artist(name=f"Artist {i}")]) 
            for i in range(5)
        ]
        
        # Mock repository to return tracks with sequential IDs
        mock_track_repo.save_track.side_effect = [
            track.with_id(i + 10) for i, track in enumerate(tracks)
        ]

        config = Mock()
        result = await enrichment_strategy.enrich_tracks(tracks, config)

        # Verify order and IDs
        assert len(result) == 5
        for i, track in enumerate(result):
            assert track.id == i + 10
            assert track.title == f"Track {i}"
            assert track.artists[0].name == f"Artist {i}"

    @pytest.mark.asyncio
    async def test_enrich_tracks_with_existing_ids(self, enrichment_strategy, mock_track_repo, sample_tracks):
        """Test enrichment when tracks already have IDs."""
        # Setup: Tracks already have IDs
        tracks_with_ids = [
            sample_tracks[0].with_id(100),
            sample_tracks[1].with_id(200),
        ]
        
        # Repository should still process them (might update existing records)
        mock_track_repo.save_track.side_effect = tracks_with_ids

        config = Mock()
        result = await enrichment_strategy.enrich_tracks(tracks_with_ids, config)

        # Verify repository was called even for tracks with existing IDs
        assert mock_track_repo.save_track.call_count == 2
        assert result[0].id == 100
        assert result[1].id == 200

    @pytest.mark.asyncio
    async def test_enrich_tracks_ignores_config_parameter(self, enrichment_strategy, mock_track_repo, sample_tracks):
        """Test that enrichment strategy ignores the config parameter."""
        enriched_track = sample_tracks[0].with_id(1)
        mock_track_repo.save_track.return_value = enriched_track

        # Pass various config types - should all work the same
        for config in [None, Mock(), {"some": "config"}, "string_config"]:
            mock_track_repo.save_track.reset_mock()
            
            result = await enrichment_strategy.enrich_tracks([sample_tracks[0]], config)
            
            assert len(result) == 1
            assert result[0].id == 1
            mock_track_repo.save_track.assert_called_once_with(sample_tracks[0])