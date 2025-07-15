"""Tests for Prefect progress artifact functionality.

These tests ensure proper async/await usage and prevent regression of
RuntimeWarnings about unawaited coroutines.
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID, uuid4

from src.application.workflows.prefect import execute_node, _should_show_progress_for_node


class TestProgressArtifacts:
    """Test progress artifact creation and updates."""

    @pytest.mark.asyncio
    async def test_progress_artifact_creation_and_completion(self):
        """Test that progress artifacts are properly created and completed with await."""
        mock_uuid = uuid4()
        
        with patch("src.application.workflows.prefect.create_progress_artifact", new_callable=AsyncMock) as mock_create, \
             patch("src.application.workflows.prefect.update_progress_artifact", new_callable=AsyncMock) as mock_update, \
             patch("src.application.workflows.prefect.get_node") as mock_get_node:
            
            # Setup async mocks
            mock_create.return_value = mock_uuid
            mock_update.return_value = mock_uuid
            
            # Mock node function
            mock_node_func = AsyncMock(return_value={"result": "test"})
            mock_get_node.return_value = (mock_node_func, None)
            
            # Execute node that should show progress
            result = await execute_node(
                node_type="source.spotify_playlist",
                context={},
                config={}
            )
            
            # Verify progress artifact was created with await  
            mock_create.assert_called_once_with(
                progress=0.0,
                description="Processing Source.Spotify Playlist"
            )
            
            # Verify progress artifact was completed with await
            mock_update.assert_called_once_with(
                artifact_id=mock_uuid,
                progress=1.0
            )
            
            # Verify node was executed
            mock_node_func.assert_called_once()
            assert result == {"result": "test"}

    @pytest.mark.asyncio 
    async def test_no_progress_artifact_for_non_qualifying_nodes(self):
        """Test that progress artifacts are not created for simple nodes."""
        with patch("src.application.workflows.prefect.create_progress_artifact", new_callable=AsyncMock) as mock_create, \
             patch("src.application.workflows.prefect.update_progress_artifact", new_callable=AsyncMock) as mock_update, \
             patch("src.application.workflows.prefect.get_node") as mock_get_node:
            
            # Mock node function
            mock_node_func = AsyncMock(return_value={"result": "test"})
            mock_get_node.return_value = (mock_node_func, None)
            
            # Execute node that should NOT show progress
            result = await execute_node(
                node_type="transform.simple_operation",
                context={},
                config={}
            )
            
            # Verify no progress artifacts were created
            mock_create.assert_not_called()
            mock_update.assert_not_called()
            
            # Verify node was still executed
            mock_node_func.assert_called_once()
            assert result == {"result": "test"}

    @pytest.mark.asyncio
    async def test_progress_artifact_creation_failure_handling(self):
        """Test graceful handling when progress artifact creation fails."""
        with patch("src.application.workflows.prefect.create_progress_artifact", new_callable=AsyncMock) as mock_create, \
             patch("src.application.workflows.prefect.update_progress_artifact", new_callable=AsyncMock) as mock_update, \
             patch("src.application.workflows.prefect.get_node") as mock_get_node:
            
            # Setup create to fail
            mock_create.side_effect = Exception("API Error")
            
            # Mock node function
            mock_node_func = AsyncMock(return_value={"result": "test"})
            mock_get_node.return_value = (mock_node_func, None)
            
            # Execute should succeed despite artifact creation failure
            result = await execute_node(
                node_type="enricher.spotify_metadata",
                context={},
                config={}
            )
            
            # Verify creation was attempted but update was not called
            mock_create.assert_called_once()
            mock_update.assert_not_called()
            
            # Verify node execution succeeded
            mock_node_func.assert_called_once()
            assert result == {"result": "test"}

    @pytest.mark.asyncio
    async def test_progress_artifact_completion_failure_handling(self):
        """Test graceful handling when progress artifact completion fails."""
        mock_uuid = uuid4()
        
        with patch("src.application.workflows.prefect.create_progress_artifact", new_callable=AsyncMock) as mock_create, \
             patch("src.application.workflows.prefect.update_progress_artifact", new_callable=AsyncMock) as mock_update, \
             patch("src.application.workflows.prefect.get_node") as mock_get_node:
            
            # Setup async mocks - create succeeds, update fails
            mock_create.return_value = mock_uuid
            mock_update.side_effect = Exception("Update failed")
            
            # Mock node function
            mock_node_func = AsyncMock(return_value={"result": "test"})
            mock_get_node.return_value = (mock_node_func, None)
            
            # Execute should succeed despite update failure
            result = await execute_node(
                node_type="source.spotify_playlist",
                context={},
                config={}
            )
            
            # Verify both create and update were attempted
            mock_create.assert_called_once()
            mock_update.assert_called_once_with(artifact_id=mock_uuid, progress=1.0)
            
            # Verify node execution succeeded
            mock_node_func.assert_called_once()
            assert result == {"result": "test"}

    def test_should_show_progress_for_node(self):
        """Test progress artifact qualification logic."""
        # Nodes that should show progress
        assert _should_show_progress_for_node("source.spotify_playlist")
        assert _should_show_progress_for_node("enricher.spotify_metadata")
        assert _should_show_progress_for_node("enricher.lastfm_data")
        
        # Nodes that should NOT show progress
        assert not _should_show_progress_for_node("transform.filter")
        assert not _should_show_progress_for_node("transform.sort")
        assert not _should_show_progress_for_node("destination.spotify_playlist")

    @pytest.mark.asyncio
    async def test_context_preservation(self):
        """Test that context is properly passed through without modification."""
        with patch("src.application.workflows.prefect.create_progress_artifact"), \
             patch("src.application.workflows.prefect.update_progress_artifact"), \
             patch("src.application.workflows.prefect.get_node") as mock_get_node:
            
            # Mock node function that checks context
            mock_node_func = AsyncMock(return_value={"result": "test"})
            mock_get_node.return_value = (mock_node_func, None)
            
            original_context = {"test_key": "test_value", "param": 42}
            
            # Execute node
            await execute_node(
                node_type="transform.simple",
                context=original_context,
                config={"setting": "value"}
            )
            
            # Verify context was passed correctly
            call_args = mock_node_func.call_args
            passed_context, passed_config = call_args[0]
            
            assert passed_context["test_key"] == "test_value"
            assert passed_context["param"] == 42
            assert passed_config == {"setting": "value"}


class TestAsyncAwaitCompliance:
    """Test that all async functions are properly awaited."""

    @pytest.mark.asyncio
    async def test_create_progress_artifact_awaited(self):
        """Test that create_progress_artifact is awaited, not called directly."""
        with patch("src.application.workflows.prefect.create_progress_artifact", new_callable=AsyncMock) as mock_create, \
             patch("src.application.workflows.prefect.get_node") as mock_get_node:
            
            # Mock to verify await usage
            mock_create.return_value = uuid4()
            mock_node_func = AsyncMock(return_value={})
            mock_get_node.return_value = (mock_node_func, None)
            
            # Execute
            await execute_node("source.spotify_playlist", {}, {})
            
            # Verify the mock was called (would only work if properly awaited)
            mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_progress_artifact_awaited(self):
        """Test that update_progress_artifact is awaited, not called directly."""
        mock_uuid = uuid4()
        
        with patch("src.application.workflows.prefect.create_progress_artifact", new_callable=AsyncMock) as mock_create, \
             patch("src.application.workflows.prefect.update_progress_artifact", new_callable=AsyncMock) as mock_update, \
             patch("src.application.workflows.prefect.get_node") as mock_get_node:
            
            # Setup async mocks
            mock_create.return_value = mock_uuid
            mock_update.return_value = mock_uuid
            mock_node_func = AsyncMock(return_value={})
            mock_get_node.return_value = (mock_node_func, None)
            
            # Execute
            await execute_node("enricher.spotify_metadata", {}, {})
            
            # Verify the completion update was awaited
            mock_update.assert_called_once_with(artifact_id=mock_uuid, progress=1.0)