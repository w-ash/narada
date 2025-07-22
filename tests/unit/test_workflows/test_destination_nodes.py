"""Test destination workflow nodes with comprehensive TDD coverage."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.entities.track import Track, TrackList, Artist
from src.domain.entities.playlist import Playlist


class TestDestinationNodes:
    """Test destination workflow nodes with TDD."""

    @pytest.fixture
    def mock_workflow_context(self):
        """Mock WorkflowContext for testing."""
        context = MagicMock()
        
        # Mock logger
        context.logger = MagicMock()
        context.logger.info = MagicMock()
        context.logger.warning = MagicMock()
        context.logger.error = MagicMock()
        
        # Mock connectors
        context.connectors = MagicMock()
        mock_spotify = AsyncMock()
        context.connectors.get_connector.return_value = mock_spotify
        
        # Mock session provider
        context.session_provider = MagicMock()
        mock_session = AsyncMock()
        context.session_provider.get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        context.session_provider.get_session.return_value.__aexit__ = AsyncMock(return_value=None)
        
        return context





class TestSpotifyDestination(TestDestinationNodes):
    """Test Spotify destination node."""

    async def test_handle_update_spotify_destination_missing_playlist_id(self, mock_workflow_context, tracklist):
        """Test error handling for missing playlist_id in update."""
        from src.application.workflows.destination_nodes import handle_update_spotify_destination
        
        # Execute with missing playlist_id
        with pytest.raises(ValueError, match="Missing required playlist_id for update operation"):
            await handle_update_spotify_destination(tracklist, {}, {})