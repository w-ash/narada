"""Contract tests for workflow context dependency injection.

These tests prevent runtime failures by validating that create_workflow_context()
provides working repositories, connectors, and other dependencies that workflow
nodes expect.

Purpose: Catch dependency injection failures like 'NoneType' object has no attribute 'get_connector_mappings'
"""

import pytest
from unittest.mock import AsyncMock

from src.application.workflows.context import create_workflow_context
from src.infrastructure.persistence.database.db_connection import get_session


class TestWorkflowContextContracts:
    """Test that workflow context provides working dependencies."""

    @pytest.mark.asyncio
    async def test_workflow_context_with_shared_session_provides_real_repositories(self):
        """Test that workflow context with shared session provides working repositories.
        
        Prevents: 'NoneType' object has no attribute 'get_connector_mappings'
        """
        # Create workflow context with shared session (workflow execution pattern)
        async with get_session() as session:
            context = create_workflow_context(shared_session=session)
            
            # Verify repositories are not None
            assert context.repositories is not None, (
                "Repositories should not be None when shared session provided"
            )
            
            # Verify critical repository properties exist
            assert hasattr(context.repositories, "connector"), (
                "Repository provider must have connector property"
            )
            assert context.repositories.connector is not None, (
                "Connector repository must not be None"
            )
            
            # Verify connector repository has required methods
            assert hasattr(context.repositories.connector, "get_connector_mappings"), (
                "Connector repository must have get_connector_mappings method"
            )
            assert callable(context.repositories.connector.get_connector_mappings), (
                "get_connector_mappings must be callable"
            )

    def test_workflow_context_without_session_provides_fallback(self):
        """Test that workflow context without session provides fallback.
        
        Prevents: Runtime errors when context created outside workflow execution
        """
        # Create workflow context without shared session (non-workflow usage)
        context = create_workflow_context()
        
        # Should not fail to create
        assert context is not None
        
        # Should have repositories (even if placeholder)
        assert hasattr(context, "repositories")

    def test_workflow_context_provides_working_connectors(self):
        """Test that workflow context provides working connector registry.
        
        Prevents: 'No connector registry available' errors
        """
        context = create_workflow_context()
        
        # Verify connector registry exists
        assert hasattr(context, "connectors"), (
            "Workflow context must have connectors"
        )
        assert context.connectors is not None, (
            "Connector registry must not be None"
        )
        
        # Verify required methods exist
        assert hasattr(context.connectors, "get_connector"), (
            "Connector registry must have get_connector method"
        )
        assert hasattr(context.connectors, "list_connectors"), (
            "Connector registry must have list_connectors method"
        )

    def test_workflow_context_provides_working_use_cases(self):
        """Test that workflow context provides working use case provider.
        
        Prevents: 'Use case provider not found in context' errors
        """
        context = create_workflow_context()
        
        # Verify use case provider exists
        assert hasattr(context, "use_cases"), (
            "Workflow context must have use_cases"
        )
        assert context.use_cases is not None, (
            "Use case provider must not be None"
        )
        
        # Verify critical use case methods exist
        assert hasattr(context.use_cases, "get_save_playlist_use_case"), (
            "Use case provider must have get_save_playlist_use_case method"
        )


class TestRepositoryProviderContracts:
    """Detailed contract tests for repository provider interface."""

    @pytest.mark.asyncio
    async def test_repository_provider_with_session_has_all_repositories(self):
        """Test that RepositoryProviderImpl provides all required repositories.
        
        Prevents: Missing repository errors in enrichment services
        """
        async with get_session() as session:
            context = create_workflow_context(shared_session=session)
            repos = context.repositories
            
            # Check all required repository properties exist
            required_repos = ["core", "connector", "metrics", "likes", "plays", "checkpoints", "playlists"]
            
            for repo_name in required_repos:
                assert hasattr(repos, repo_name), (
                    f"Repository provider must have {repo_name} property"
                )
                repo = getattr(repos, repo_name)
                assert repo is not None, (
                    f"{repo_name} repository must not be None"
                )

    @pytest.mark.asyncio  
    async def test_track_repositories_integration(self):
        """Test that TrackRepositories work properly in workflow context.
        
        Prevents: Repository initialization failures
        """
        async with get_session() as session:
            context = create_workflow_context(shared_session=session)
            
            # Access connector repository through the provider
            connector_repo = context.repositories.connector
            
            # Should be able to call methods without errors
            # (Note: This tests the integration, not the database operations)
            try:
                # This should not raise AttributeError
                method = getattr(connector_repo, "get_connector_mappings")
                assert callable(method)
            except AttributeError as e:
                pytest.fail(f"Connector repository missing required method: {e}")


class TestExtractorContracts:
    """Contract tests for extractor configuration integration."""

    def test_lastfm_extractor_config_accessible(self):
        """Test that Last.fm extractor configuration can be accessed.
        
        Prevents: ImportError or missing extractor configuration
        """
        try:
            from src.infrastructure.connectors.lastfm import get_connector_config
            config = get_connector_config()
            
            assert "extractors" in config, (
                "Last.fm connector config must provide extractors"
            )
            
            extractors = config["extractors"]
            assert isinstance(extractors, dict), (
                "Extractors must be a dictionary"
            )
            
            # Check for key extractors used by workflow
            expected_extractors = [
                "lastfm_user_playcount",
                "lastfm_global_playcount", 
                "lastfm_listeners"
            ]
            
            for extractor_name in expected_extractors:
                assert extractor_name in extractors, (
                    f"Missing required extractor: {extractor_name}"
                )
                assert callable(extractors[extractor_name]), (
                    f"Extractor {extractor_name} must be callable"
                )
                
        except ImportError as e:
            pytest.fail(f"Could not import Last.fm connector config: {e}")

    def test_spotify_extractor_config_accessible(self):
        """Test that Spotify extractor configuration can be accessed.
        
        Prevents: ImportError or missing extractor configuration  
        """
        try:
            from src.infrastructure.connectors.spotify import get_connector_config
            config = get_connector_config()
            
            assert "extractors" in config, (
                "Spotify connector config must provide extractors"
            )
            
            extractors = config["extractors"]
            assert isinstance(extractors, dict), (
                "Extractors must be a dictionary"
            )
            
        except ImportError as e:
            pytest.fail(f"Could not import Spotify connector config: {e}")