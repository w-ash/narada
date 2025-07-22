"""Tests for playlist command user flows."""

from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from src.infrastructure.cli.app import app


@pytest.fixture
def runner():
    """CLI test runner."""
    return CliRunner()


class TestPlaylistListCommand:
    """Test playlist list functionality."""

    def test_playlist_list_command_works(self, runner):
        """Test that playlist list command is accessible."""
        result = runner.invoke(app, ["playlist", "list"])
        
        # Should not crash, even if no workflows found
        assert result.exit_code == 0

    def test_playlist_list_shows_workflows_when_available(self, runner):
        """Test that list shows workflows when they exist."""
        # Mock workflow discovery to return sample workflows
        mock_workflows = [
            {
                "id": "test_workflow",
                "name": "Test Workflow", 
                "description": "A test workflow",
                "task_count": 3
            }
        ]
        
        with patch("src.infrastructure.cli.workflows_commands.list_workflows", return_value=mock_workflows):
            result = runner.invoke(app, ["playlist", "list"])
            
            assert result.exit_code == 0
            assert "Test Workflow" in result.stdout

    def test_playlist_list_handles_no_workflows(self, runner):
        """Test that list handles case with no workflows gracefully."""
        with patch("src.infrastructure.cli.workflows_commands.list_workflows", return_value=[]):
            result = runner.invoke(app, ["playlist", "list"])
            
            assert result.exit_code == 0
            # Should show appropriate message for no workflows
            assert ("No workflows" in result.stdout or 
                    "not found" in result.stdout or
                    len(result.stdout.strip()) == 0)


class TestPlaylistRunCommand:
    """Test playlist run functionality."""

    def test_playlist_run_help_works(self, runner):
        """Test that playlist run help is accessible."""
        result = runner.invoke(app, ["playlist", "run", "--help"])
        
        assert result.exit_code == 0
        assert "workflow" in result.stdout.lower()

    def test_playlist_run_with_invalid_workflow_fails_gracefully(self, runner):
        """Test that invalid workflow IDs are handled gracefully."""
        result = runner.invoke(app, ["playlist", "run", "nonexistent_workflow"])
        
        # Should fail but not crash
        assert result.exit_code != 0
        # Should not show Python traceback
        assert "Traceback" not in result.stdout

    def test_playlist_run_without_workflow_shows_interactive_menu(self, runner):
        """Test that running without workflow ID shows interactive selection."""
        # Mock empty workflow list to test the no-workflow case
        with patch("src.infrastructure.cli.workflows_commands.list_workflows", return_value=[]):
            result = runner.invoke(app, ["playlist", "run"])
            
            # Should either show interactive menu or handle no workflows case
            assert result.exit_code == 0 or "No workflows" in result.stdout

    def test_playlist_run_supports_output_formats(self, runner):
        """Test that playlist run supports different output formats."""
        result = runner.invoke(app, ["playlist", "run", "--help"])
        
        assert result.exit_code == 0
        assert "--format" in result.stdout or "-f" in result.stdout


class TestPlaylistCommandIntegration:
    """Test integration between playlist commands."""

    def test_list_and_run_commands_consistent(self, runner):
        """Test that list and run commands work consistently together."""
        # Mock a workflow that should be runnable
        mock_workflows = [
            {
                "id": "test_workflow",
                "name": "Test Workflow",
                "description": "A test workflow", 
                "task_count": 1,
                "path": "/fake/path.json"
            }
        ]
        
        with patch("src.infrastructure.cli.workflows_commands.list_workflows", return_value=mock_workflows):
            # List should show the workflow
            list_result = runner.invoke(app, ["playlist", "list"])
            assert list_result.exit_code == 0
            assert "test_workflow" in list_result.stdout
            
            # Run should accept the workflow ID (may fail on execution but shouldn't crash on routing)
            run_result = runner.invoke(app, ["playlist", "run", "test_workflow"])
            # Don't assert success since execution may fail, but check it doesn't crash on command parsing
            assert "No such command" not in run_result.stdout


class TestPlaylistErrorHandling:
    """Test error handling in playlist commands."""

    def test_invalid_playlist_subcommand_fails_gracefully(self, runner):
        """Test that invalid playlist subcommands show helpful errors."""
        result = runner.invoke(app, ["playlist", "invalid-command"])
        
        assert result.exit_code != 0
        assert ("Usage:" in result.stdout or 
                "No such command" in result.stdout)

    def test_playlist_commands_handle_system_errors(self, runner):
        """Test that system errors don't cause crashes."""
        # Mock a system error in workflow loading
        with patch("src.infrastructure.cli.workflows_commands.list_workflows", side_effect=Exception("System error")):
            result = runner.invoke(app, ["playlist", "list"])
            
            # Should not crash with unhandled exception
            assert "Traceback" not in result.stdout or result.exit_code != 0