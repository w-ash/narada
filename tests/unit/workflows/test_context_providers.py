"""Unit tests for workflow context providers.

These tests verify individual context providers work correctly in isolation,
following the test pyramid principle of many fast unit tests.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.application.workflows.context import (
    ConfigProviderImpl,
    LoggerProviderImpl,
    ConnectorRegistryImpl,
    UseCaseProviderImpl,
    DatabaseSessionProviderImpl,
    create_workflow_context,
)


class TestConfigProviderImpl:
    """Test configuration provider implementation."""
    
    def test_config_provider_initialization(self):
        """Test that config provider initializes correctly."""
        provider = ConfigProviderImpl()
        assert provider._get_config is not None
    
    @patch('src.config.get_config')
    def test_config_provider_get(self, mock_get_config):
        """Test that config provider delegates to get_config."""
        mock_get_config.return_value = "test_value"
        
        provider = ConfigProviderImpl()
        result = provider.get("test_key", "default")
        
        mock_get_config.assert_called_once_with("test_key", "default")
        assert result == "test_value"


class TestLoggerProviderImpl:
    """Test logger provider implementation."""
    
    @patch('src.application.workflows.context.get_logger')
    def test_logger_provider_initialization(self, mock_get_logger):
        """Test that logger provider initializes with correct name."""
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger
        
        provider = LoggerProviderImpl("test_module")
        
        mock_get_logger.assert_called_once_with("test_module")
        assert provider._logger == mock_logger
    
    @patch('src.application.workflows.context.get_logger')
    def test_logger_provider_methods(self, mock_get_logger):
        """Test that logger provider methods delegate to underlying logger."""
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger
        
        provider = LoggerProviderImpl()
        
        # Test each logging method
        provider.info("test message", key="value")
        provider.debug("debug message", key="value")
        provider.warning("warning message", key="value")
        provider.error("error message", key="value")
        
        mock_logger.info.assert_called_once_with("test message", key="value")
        mock_logger.debug.assert_called_once_with("debug message", key="value")
        mock_logger.warning.assert_called_once_with("warning message", key="value")
        mock_logger.error.assert_called_once_with("error message", key="value")


class TestConnectorRegistryImpl:
    """Test connector registry implementation."""
    
    @patch('src.application.workflows.context.discover_connectors')
    @patch('src.application.workflows.context.CONNECTORS', {"test_connector": {"factory": MagicMock()}})
    def test_connector_registry_initialization(self, mock_discover):
        """Test that connector registry initializes correctly."""
        provider = ConnectorRegistryImpl()
        
        mock_discover.assert_called_once()
        assert "test_connector" in provider._connectors
    
    @patch('src.application.workflows.context.discover_connectors')
    def test_get_connector_success(self, mock_discover):
        """Test successful connector retrieval."""
        mock_connector_factory = MagicMock()
        mock_connector_instance = MagicMock()
        mock_connector_factory.return_value = mock_connector_instance
        
        with patch('src.application.workflows.context.CONNECTORS', {"test_connector": {"factory": mock_connector_factory}}):
            provider = ConnectorRegistryImpl()
            result = provider.get_connector("test_connector")
        
        # Check that factory was called correctly
        mock_connector_factory.assert_called_once_with({})
        
        # Result is returned directly (no adapter wrapper)
        assert result == mock_connector_instance
    
    @patch('src.application.workflows.context.discover_connectors')
    def test_get_connector_not_found(self, mock_discover):
        """Test connector not found error."""
        with patch('src.application.workflows.context.CONNECTORS', {}):
            provider = ConnectorRegistryImpl()
            
            with pytest.raises(ValueError, match="Unknown connector: unknown"):
                provider.get_connector("unknown")
    
    @patch('src.application.workflows.context.discover_connectors')
    def test_list_connectors(self, mock_discover):
        """Test listing available connectors."""
        connectors = {"connector1": {"factory": MagicMock()}, "connector2": {"factory": MagicMock()}}
        
        with patch('src.application.workflows.context.CONNECTORS', connectors):
            provider = ConnectorRegistryImpl()
            result = provider.list_connectors()
        
        assert result == ["connector1", "connector2"]


class TestDatabaseSessionProviderImpl:
    """Test database session provider implementation."""
    
    @patch('src.application.workflows.context.get_session')
    def test_session_provider_get_session(self, mock_get_session):
        """Test that session provider returns session from get_session."""
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session
        
        provider = DatabaseSessionProviderImpl()
        result = provider.get_session()
        
        mock_get_session.assert_called_once()
        assert result == mock_session


class TestUseCaseProviderImpl:
    """Test use case provider implementation."""
    
    @pytest.mark.asyncio
    @patch('src.application.workflows.context.get_session')
    async def test_get_save_playlist_use_case(self, mock_get_session):
        """Test getting SavePlaylistUseCase with dependency injection."""
        # Mock session context manager
        mock_session_ctx = MagicMock()
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session_ctx)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_get_session.return_value = mock_session
        
        # Mock repositories
        with patch('src.application.workflows.context.TrackRepositories') as mock_track_repos, \
             patch('src.application.workflows.context.PlaylistRepositories') as mock_playlist_repos, \
             patch('src.application.use_cases.save_playlist.SavePlaylistUseCase') as mock_use_case_class:
            
            mock_track_repo_instance = MagicMock()
            mock_playlist_repo_instance = MagicMock()
            mock_track_repos.return_value.core = mock_track_repo_instance
            mock_playlist_repos.return_value.core = mock_playlist_repo_instance
            mock_use_case_instance = MagicMock()
            mock_use_case_class.return_value = mock_use_case_instance
            
            provider = UseCaseProviderImpl()
            
            # This should work with proper session management
            async with mock_session:
                result = await provider.get_save_playlist_use_case()
            
            # Verify the use case was created with correct dependencies
            mock_use_case_class.assert_called_once_with(
                track_repo=mock_track_repo_instance,
                playlist_repo=mock_playlist_repo_instance
            )
            assert result == mock_use_case_instance


class TestCreateWorkflowContext:
    """Test workflow context creation function."""
    
    @patch('src.application.workflows.context.ConfigProviderImpl')
    @patch('src.application.workflows.context.LoggerProviderImpl')
    @patch('src.application.workflows.context.ConnectorRegistryImpl')
    @patch('src.application.workflows.context.UseCaseProviderImpl')
    @patch('src.application.workflows.context.DatabaseSessionProviderImpl')
    def test_create_workflow_context(self, mock_session_provider, mock_use_cases, 
                                   mock_connectors, mock_logger, mock_config):
        """Test that create_workflow_context wires up all dependencies correctly."""
        mock_config_instance = MagicMock()
        mock_logger_instance = MagicMock()
        mock_connectors_instance = MagicMock()
        mock_use_cases_instance = MagicMock()
        mock_session_provider_instance = MagicMock()
        
        mock_config.return_value = mock_config_instance
        mock_logger.return_value = mock_logger_instance
        mock_connectors.return_value = mock_connectors_instance
        mock_use_cases.return_value = mock_use_cases_instance
        mock_session_provider.return_value = mock_session_provider_instance
        
        context = create_workflow_context()
        
        # Verify all providers were created
        mock_config.assert_called_once()
        mock_logger.assert_called_once()
        mock_connectors.assert_called_once()
        mock_use_cases.assert_called_once()
        mock_session_provider.assert_called_once()
        
        # Verify context has all required attributes
        assert context.config == mock_config_instance
        assert context.logger == mock_logger_instance
        assert context.connectors == mock_connectors_instance
        assert context.use_cases == mock_use_cases_instance
        assert context.session_provider == mock_session_provider_instance
        assert context.repositories is not None  # Legacy compatibility
    
    def test_context_structure(self):
        """Test that created context has the expected structure."""
        context = create_workflow_context()
        
        # Verify all required attributes exist
        assert hasattr(context, 'config')
        assert hasattr(context, 'logger')
        assert hasattr(context, 'connectors')
        assert hasattr(context, 'use_cases')
        assert hasattr(context, 'session_provider')
        assert hasattr(context, 'repositories')
        
        # Verify types are correct
        assert isinstance(context.config, ConfigProviderImpl)
        assert isinstance(context.logger, LoggerProviderImpl)
        assert isinstance(context.connectors, ConnectorRegistryImpl)
        assert isinstance(context.use_cases, UseCaseProviderImpl)
        assert isinstance(context.session_provider, DatabaseSessionProviderImpl)