"""Tests for CLI app help system consolidation."""

from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from src.infrastructure.cli.app import app


@pytest.fixture
def runner():
    """CLI test runner."""
    return CliRunner()


class TestWorkflowRegistration:
    """Test workflow registration reliability in help system."""

    def test_all_workflows_appear_in_help(self, runner):
        """Test that narada --help shows all available workflows."""
        # Since workflows are registered at import time, just test that 
        # the current real workflows appear in help output
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        
        # Should have the Playlist Workflows panel
        assert "🎵 Playlist Workflows" in result.stdout
        
        # Should have some workflow commands (test with real ones)
        assert "discovery_mix" in result.stdout
        assert "Latest Discovery Mix" in result.stdout

    def test_workflow_registration_with_db_unavailable(self, runner):
        """Test workflow registration gracefully handles database unavailable."""
        with patch("src.infrastructure.cli.app.list_workflows", side_effect=Exception("Database unavailable")):
            result = runner.invoke(app, ["--help"])
            assert result.exit_code == 0
            # Should still show other commands even if workflows fail to load
            assert "status" in result.stdout
            assert "setup" in result.stdout

    def test_workflow_registration_with_empty_list(self, runner):
        """Test workflow registration with empty workflow list."""
        with patch("src.infrastructure.cli.app.list_workflows") as mock_list:
            mock_list.return_value = []
            
            result = runner.invoke(app, ["--help"])
            assert result.exit_code == 0
            # Should still show basic structure
            assert "🎵 Playlist Workflows" in result.stdout or "Playlist Workflows" in result.stdout

    def test_registered_workflows_are_callable(self, runner):
        """Test that registered workflows can actually be called."""
        # Test with a real workflow that should be registered
        result = runner.invoke(app, ["discovery_mix", "--help"])
        # Should not get "No such command" error
        assert "No such command" not in result.stdout
        assert result.exit_code == 0


class TestHelpConsolidation:
    """Test help system consolidation to single native Typer help."""

    def test_no_args_shows_help(self, runner):
        """Test that running narada with no args shows help (no_args_is_help=True)."""
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        # Should show help content, not welcome message
        assert "Usage:" in result.stdout
        assert "─ Options ─" in result.stdout  # Rich formatting

    def test_custom_help_command_does_not_exist(self, runner):
        """Test that custom help command is removed."""
        result = runner.invoke(app, ["help"])
        # Should either not exist or redirect to --help
        # If it doesn't exist, we get "No such command" error
        # If it redirects, we get help output
        assert result.exit_code != 0 or "Usage:" in result.stdout

    def test_all_help_panels_present_in_native_help(self, runner):
        """Test that all command panels are present in native Typer help."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        
        # All panels should be present
        expected_panels = [
            "⚙️ System",
            "📊 Data Sync", 
            "🔧 Playlist Workflow Management",
            "🎵 Playlist Workflows"
        ]
        
        for panel in expected_panels:
            assert panel in result.stdout

    def test_no_redundant_welcome_message(self, runner):
        """Test that there's no redundant welcome message logic."""
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        
        # Should not contain welcome-specific text that directs to multiple help options
        assert "Type narada help to get started" not in result.stdout
        assert "Type narada --help for all commands" not in result.stdout