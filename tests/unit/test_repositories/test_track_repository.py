"""Unit tests for TrackRepository core operations."""

from unittest.mock import AsyncMock

import pytest

from src.infrastructure.persistence.repositories.track.core import TrackRepository


class TestTrackRepository:
    """Test core track repository operations."""

    @pytest.fixture
    def repo(self, db_session):
        """Track repository instance."""
        return TrackRepository(db_session)

    @pytest.mark.asyncio
    async def test_find_tracks_by_ids_empty_list(self, repo):
        """Should handle empty ID list gracefully."""
        result = await repo.find_tracks_by_ids([])
        assert result == {}

    @pytest.mark.asyncio
    async def test_find_tracks_by_ids_single_track(self, repo, track):
        """Should find track by ID when it exists."""
        # Create a database track mock that matches DBTrack structure
        from unittest.mock import MagicMock

        from src.infrastructure.persistence.database.db_models import DBTrack
        db_track = DBTrack(
            id=1,
            title="Test Track",
            artists={"names": ["Test Artist"]},
            duration_ms=200000,
            release_date=None,
            isrc=None,
            spotify_id=None,
            mbid=None
        )
        # Ensure required attributes are set
        db_track.mappings = []
        db_track.likes = []
        
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [db_track]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        repo.session.execute = AsyncMock(return_value=mock_result)
        
        result = await repo.find_tracks_by_ids([1])
        
        assert 1 in result
        assert result[1].title == "Test Track"

    @pytest.mark.asyncio
    async def test_find_tracks_by_ids_multiple_tracks(self, repo, tracks):
        """Should find multiple tracks by IDs."""
        # Mock the session execute to return our database tracks
        from unittest.mock import MagicMock
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = tracks
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        repo.session.execute = AsyncMock(return_value=mock_result)
        
        result = await repo.find_tracks_by_ids([1, 2, 3])
        
        assert len(result) == 3
        assert all(i in result for i in [1, 2, 3])

    @pytest.mark.asyncio
    async def test_find_tracks_by_ids_missing_tracks(self, repo):
        """Should return empty dict when no tracks found."""
        # Mock the session execute to return empty result
        from unittest.mock import MagicMock
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        repo.session.execute = AsyncMock(return_value=mock_result)
        
        result = await repo.find_tracks_by_ids([999])
        
        assert result == {}