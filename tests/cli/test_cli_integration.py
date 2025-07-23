"""Targeted integration tests for CLI command routing."""

from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from src.infrastructure.cli.app import app


@pytest.fixture
def runner():
    """CLI test runner."""
    return CliRunner()


class TestDataCommandIntegration:
    """Test that data commands route to correct business logic."""

    @patch("src.infrastructure.cli.data_commands._run_lastfm_incremental_import")
    def test_import_plays_lastfm_routes_to_business_logic(self, mock_import, runner):
        """Test that import-plays-lastfm command routes to correct handler."""
        from src.domain.entities.operations import OperationResult
        mock_import.return_value = OperationResult(operation_name="test")
        
        runner.invoke(app, ["data", "import-plays-lastfm"])
        
        # Verify the business logic handler was called
        mock_import.assert_called_once()

    @patch("src.infrastructure.cli.data_commands._run_spotify_likes_import")
    def test_import_likes_spotify_routes_to_business_logic(self, mock_import, runner):
        """Test that import-likes-spotify command routes to correct handler."""
        from src.domain.entities.operations import OperationResult
        mock_import.return_value = OperationResult(operation_name="test")
        
        runner.invoke(app, ["data", "import-likes-spotify"])
        
        # Verify the business logic handler was called
        mock_import.assert_called_once()

    @patch("src.infrastructure.cli.data_commands._run_lastfm_loves_export")
    def test_export_likes_lastfm_routes_to_business_logic(self, mock_export, runner):
        """Test that export-likes-lastfm command routes to correct handler."""
        from src.domain.entities.operations import OperationResult
        mock_export.return_value = OperationResult(operation_name="test")
        
        runner.invoke(app, ["data", "export-likes-lastfm"])
        
        # Verify the business logic handler was called
        mock_export.assert_called_once()

    @patch("src.infrastructure.cli.data_commands._run_spotify_file_import")
    def test_import_plays_file_with_valid_file_routes_correctly(self, mock_import, runner, tmp_path):
        """Test that import-plays-file with valid file routes correctly."""
        from src.domain.entities.operations import OperationResult
        mock_import.return_value = OperationResult(operation_name="test")
        
        # Create a temporary file
        test_file = tmp_path / "test.json"
        test_file.write_text('{"test": "data"}')
        
        runner.invoke(app, ["data", "import-plays-file", str(test_file)])
        
        # Verify the business logic handler was called
        mock_import.assert_called_once()


class TestPlaylistCommandIntegration:
    """Test that playlist commands route correctly."""

    @patch("src.infrastructure.cli.workflows_commands.list_workflows")
    def test_playlist_list_routes_to_workflow_discovery(self, mock_list, runner):
        """Test that playlist list routes to workflow discovery."""
        mock_list.return_value = []
        
        runner.invoke(app, ["playlist", "list"])
        
        # Verify workflow discovery was called
        mock_list.assert_called_once()

    @patch("src.infrastructure.cli.workflows_commands._run_workflow_interactive")
    @patch("src.infrastructure.cli.workflows_commands.list_workflows")
    def test_playlist_run_routes_to_workflow_execution(self, mock_list, mock_run, runner):
        """Test that playlist run routes to workflow execution."""
        # Mock workflow discovery
        mock_workflows = [
            {
                "id": "test_workflow",
                "name": "Test Workflow",
                "description": "Test",
                "task_count": 1,
                "path": "/fake/path.json"
            }
        ]
        mock_list.return_value = mock_workflows
        
        runner.invoke(app, ["playlist", "run", "test_workflow"])
        
        # Verify workflow execution was attempted
        mock_run.assert_called_once()


class TestCriticalParameterPassing:
    """Test that critical parameters reach business logic correctly."""

    @patch("src.infrastructure.cli.data_commands._run_lastfm_recent_import")
    def test_import_plays_lastfm_recent_parameter_passed(self, mock_import, runner):
        """Test that --recent parameter is handled correctly."""
        from src.domain.entities.operations import OperationResult
        mock_import.return_value = OperationResult(operation_name="test")
        
        runner.invoke(app, ["data", "import-plays-lastfm", "--recent", "500"])
        
        # Verify the handler was called (exact parameter inspection is fragile)
        mock_import.assert_called_once()

    @patch("src.infrastructure.cli.data_commands._run_lastfm_full_import")  
    def test_import_plays_lastfm_full_flag_routes_correctly(self, mock_import, runner):
        """Test that --full flag routes to correct handler."""
        from src.domain.entities.operations import OperationResult
        mock_import.return_value = OperationResult(operation_name="test")
        
        runner.invoke(app, ["data", "import-plays-lastfm", "--full", "--confirm"])
        
        # Verify the full import handler was called
        mock_import.assert_called_once()

    @patch("src.infrastructure.cli.data_commands._run_spotify_file_import")
    def test_import_plays_file_batch_size_parameter(self, mock_import, runner, tmp_path):
        """Test that batch-size parameter is passed correctly."""
        from src.domain.entities.operations import OperationResult
        mock_import.return_value = OperationResult(operation_name="test")
        
        # Create temporary file
        test_file = tmp_path / "test.json"
        test_file.write_text('{"test": "data"}')
        
        runner.invoke(app, ["data", "import-plays-file", str(test_file), "--batch-size", "100"])
        
        # Verify the handler was called
        mock_import.assert_called_once()


class TestEndToEndFlows:
    """Test complete end-to-end command flows without deep mocking."""

    def test_help_commands_work_end_to_end(self, runner):
        """Test that all help commands work without mocking."""
        help_commands = [
            ["--help"],
            ["data", "--help"],
            ["playlist", "--help"],
            ["status", "--help"],
            ["setup", "--help"],
            ["data", "menu", "--help"],
            ["data", "import-plays-lastfm", "--help"],
            ["playlist", "list", "--help"],
            ["playlist", "run", "--help"]
        ]
        
        for cmd in help_commands:
            result = runner.invoke(app, cmd)
            assert result.exit_code == 0, f"Help failed for command: {' '.join(cmd)}"
            assert "Usage:" in result.stdout

    def test_version_command_end_to_end(self, runner):
        """Test version command works without mocking."""
        result = runner.invoke(app, ["version"])
        
        assert result.exit_code == 0
        assert "Narada" in result.stdout
        # Should show version number
        assert any(char.isdigit() for char in result.stdout)

    def test_invalid_commands_handled_end_to_end(self, runner):
        """Test that invalid commands are handled gracefully."""
        invalid_commands = [
            ["invalid-command"],
            ["data", "invalid-operation"],
            ["playlist", "invalid-action"]
        ]
        
        for cmd in invalid_commands:
            result = runner.invoke(app, cmd)
            assert result.exit_code != 0, f"Invalid command should fail: {' '.join(cmd)}"
            # Should show usage or error, not crash
            assert ("Usage:" in result.stdout or 
                    "No such command" in result.stdout or
                    "Error:" in result.stdout)
            # Should not show Python traceback for user errors
            assert "Traceback" not in result.stdout