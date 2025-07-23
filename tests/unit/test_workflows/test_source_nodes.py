"""Test source workflow nodes with comprehensive TDD coverage."""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestSpotifyPlaylistSource:
    """Test Spotify playlist source node with TDD."""

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

    @pytest.fixture
    def sample_config(self):
        """Sample configuration for Spotify playlist source."""
        return {"playlist_id": "test_playlist_123"}

    async def test_spotify_playlist_source_empty_playlist(self, mock_workflow_context, sample_config):
        """Test handling of empty Spotify playlist."""
        from src.application.workflows.source_nodes import spotify_playlist_source
        
        # Setup mocks for empty playlist
        mock_spotify = mock_workflow_context.connectors.get_connector.return_value
        mock_playlist = MagicMock()
        mock_playlist.name = "Empty Playlist"
        mock_playlist.items = []  # Empty playlist
        mock_spotify.get_spotify_playlist.return_value = mock_playlist
        
        # Execute the function with mocked connector
        result = await spotify_playlist_source({}, sample_config, mock_spotify)
        
        # Verify empty playlist handling
        assert result["operation"] == "spotify_playlist_source"
        assert result["playlist_name"] == "Empty Playlist"
        assert result["track_count"] == 0
        assert len(result["tracklist"].tracks) == 0

    async def test_spotify_playlist_source_missing_playlist_id(self, mock_workflow_context):
        """Test error handling for missing playlist_id."""
        from src.application.workflows.source_nodes import spotify_playlist_source
        
        # Execute with missing playlist_id
        with pytest.raises(ValueError, match="Missing required config parameter: playlist_id"):
            await spotify_playlist_source({}, {})

    async def test_spotify_playlist_source_not_found(self, mock_workflow_context, sample_config):
        """Test handling of playlist not found."""
        from src.application.workflows.source_nodes import spotify_playlist_source
        
        # Setup mocks for not found
        mock_spotify = mock_workflow_context.connectors.get_connector.return_value
        mock_spotify.get_spotify_playlist.return_value = None
        
        # Execute the function with mocked connector
        result = await spotify_playlist_source({}, sample_config, mock_spotify)
        
        # Verify not found handling
        assert result["operation"] == "spotify_playlist_source"
        assert result["playlist_name"] == "Unknown"
        assert result["playlist_id"] is None
        assert result["track_count"] == 0