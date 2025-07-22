"""Unit tests for PlayHistoryEnricher application service."""

from unittest.mock import AsyncMock, Mock

import pytest

from src.application.services.play_history_enricher import PlayHistoryEnricher
from src.domain.entities.track import Artist, Track, TrackList
from src.infrastructure.persistence.repositories.track import TrackRepositories


class TestPlayHistoryEnricher:
    """Test play history enrichment service."""

    @pytest.fixture
    def mock_repositories(self):
        """Create mock repositories."""
        mock_repos = Mock(spec=TrackRepositories)
        mock_repos.plays = AsyncMock()
        return mock_repos

    @pytest.fixture
    def enricher(self, mock_repositories):
        """Create enricher with mock dependencies."""
        return PlayHistoryEnricher(mock_repositories)

    @pytest.mark.asyncio
    async def test_enrich_with_default_metrics(self, enricher, mock_repositories):
        """Test enrichment with default metrics."""
        tracks = [Track(id=1, title="Track 1", artists=[Artist(name="Artist 1")])]
        tracklist = TrackList(tracks=tracks)
        
        mock_aggregations = {"total_plays": {1: 5}}
        mock_repositories.plays.get_play_aggregations.return_value = mock_aggregations

        result = await enricher.enrich_with_play_history(tracklist)

        mock_repositories.plays.get_play_aggregations.assert_called_once_with(
            track_ids=[1],
            metrics=["total_plays", "last_played_dates"],
            period_start=None,
            period_end=None,
        )
        assert result.metadata["metrics"]["total_plays"] == {1: 5}

    @pytest.mark.asyncio
    async def test_enrich_preserves_existing_metadata(self, enricher, mock_repositories):
        """Test that enrichment preserves existing metadata."""
        tracks = [Track(id=1, title="Track 1", artists=[Artist(name="Artist 1")])]
        existing_metadata = {"spotify_popularity": {1: 75}}
        tracklist = TrackList(tracks=tracks, metadata=existing_metadata)

        mock_aggregations = {"total_plays": {1: 5}}
        mock_repositories.plays.get_play_aggregations.return_value = mock_aggregations

        result = await enricher.enrich_with_play_history(tracklist)

        # Existing metadata preserved
        assert result.metadata["spotify_popularity"] == {1: 75}
        # New metadata added
        assert result.metadata["metrics"]["total_plays"] == {1: 5}

    @pytest.mark.asyncio
    async def test_enrich_empty_tracklist(self, enricher, mock_repositories):
        """Test enrichment with empty tracklist."""
        empty_tracklist = TrackList(tracks=[])

        result = await enricher.enrich_with_play_history(empty_tracklist)

        mock_repositories.plays.get_play_aggregations.assert_not_called()
        assert len(result.tracks) == 0
        assert result.metadata == {}