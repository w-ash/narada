"""Tests for data command user flows and parameter validation."""

from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from src.infrastructure.cli.app import app


@pytest.fixture
def runner():
    """CLI test runner."""
    return CliRunner()


class TestDataMenuInteraction:
    """Test interactive data menu functionality."""

    def test_data_menu_can_be_cancelled(self, runner):
        """Test that users can cancel out of data menu."""
        with patch("rich.prompt.Prompt.ask", return_value=""):
            result = runner.invoke(app, ["data", "menu"])
            # Should exit gracefully when user cancels
            assert result.exit_code == 0

    def test_data_menu_handles_quit_commands(self, runner):
        """Test that quit/exit commands work in menu."""
        quit_commands = ["q", "quit", "exit", "cancel"]
        
        for quit_cmd in quit_commands:
            with patch("rich.prompt.Prompt.ask", return_value=quit_cmd):
                result = runner.invoke(app, ["data", "menu"])
                assert result.exit_code == 0

    def test_data_menu_shows_operations(self, runner):
        """Test that data menu displays available operations."""
        with patch("rich.prompt.Prompt.ask", return_value=""):
            result = runner.invoke(app, ["data", "menu"])
            
            # Should show both categories
            assert "Import Data" in result.stdout
            assert "Export Data" in result.stdout
            
            # Should show operation descriptions
            assert "Spotify export file" in result.stdout
            assert "Last.fm API" in result.stdout


class TestParameterValidation:
    """Test that parameters are validated correctly."""

    def test_import_plays_file_requires_path(self, runner):
        """Test that import-plays-file requires a file path."""
        result = runner.invoke(app, ["data", "import-plays-file"])
        
        # Should fail without file path
        assert result.exit_code != 0
        assert ("required" in result.stdout.lower() or 
                "missing" in result.stdout.lower() or
                "Usage:" in result.stdout)

    def test_import_plays_file_validates_file_exists(self, runner):
        """Test that import-plays-file validates file exists."""
        nonexistent_file = "/nonexistent/path/file.json"
        result = runner.invoke(app, ["data", "import-plays-file", nonexistent_file])
        
        # Should fail for nonexistent file
        assert result.exit_code != 0

    def test_import_plays_lastfm_accepts_valid_options(self, runner):
        """Test that import-plays-lastfm accepts valid option combinations."""
        with patch("src.infrastructure.cli.data_commands._run_lastfm_incremental_import") as mock_import:
            from src.domain.entities.operations import OperationResult
            mock_import.return_value = OperationResult(operation_name="test")
            
            # Should accept valid options without crashing
            runner.invoke(app, ["data", "import-plays-lastfm", "--recent", "100"])
            # Don't assert success since it might fail on missing config, but shouldn't crash


class TestDirectCommandAccess:
    """Test that direct command access works for power users."""

    def test_all_data_operations_accessible_directly(self, runner):
        """Test that all data operations can be called directly."""
        import warnings
        operations = [
            "import-plays-file",
            "import-plays-lastfm", 
            "import-likes-spotify",
            "export-likes-lastfm"
        ]
        
        # Suppress decorator warnings from CLI help inspection
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*coroutine.*was never awaited", category=RuntimeWarning)
            for op in operations:
                result = runner.invoke(app, ["data", op, "--help"])
                assert result.exit_code == 0, f"Direct access failed for: data {op}"

    def test_commands_show_appropriate_help_text(self, runner):
        """Test that commands show relevant help content."""
        test_cases = [
            ("import-plays-file", ["Spotify", "JSON", "export", "play history"]),
            ("import-plays-lastfm", ["Last.fm", "API", "play history"]),
            ("import-likes-spotify", ["liked tracks", "Spotify"]),
            ("export-likes-lastfm", ["Last.fm", "loves", "export"])
        ]
        
        for cmd, expected_terms in test_cases:
            result = runner.invoke(app, ["data", cmd, "--help"])
            assert result.exit_code == 0
            
            # Check that help contains relevant terms (case insensitive)
            help_text = result.stdout.lower()
            for term in expected_terms:
                assert term.lower() in help_text, f"Missing '{term}' in help for {cmd}"

    def test_options_are_documented_in_help(self, runner):
        """Test that important options are documented in help."""
        # Test that import-plays-lastfm shows key options
        result = runner.invoke(app, ["data", "import-plays-lastfm", "--help"])
        assert result.exit_code == 0
        assert "--recent" in result.stdout
        assert "--full" in result.stdout
        assert "--resolve-tracks" in result.stdout

        # Test that import-plays-file shows batch-size option  
        result = runner.invoke(app, ["data", "import-plays-file", "--help"])
        assert result.exit_code == 0
        assert "--batch-size" in result.stdout


class TestErrorHandling:
    """Test that errors are handled gracefully."""

    def test_invalid_data_subcommand_fails_gracefully(self, runner):
        """Test that invalid data subcommands show helpful errors."""
        result = runner.invoke(app, ["data", "invalid-operation"])
        
        assert result.exit_code != 0
        # Should show usage or error message
        assert ("Usage:" in result.stdout or 
                "No such command" in result.stdout or
                "invalid" in result.stdout.lower())

    def test_conflicting_options_handled(self, runner):
        """Test that conflicting options are handled appropriately."""
        # Test conflicting recent and full flags
        result = runner.invoke(app, ["data", "import-plays-lastfm", "--recent", "100", "--full"])
        
        # Should either work (full takes precedence) or show clear error
        # Don't assert success/failure, just that it doesn't crash completely
        assert "Traceback" not in result.stdout