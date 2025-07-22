"""Smoke tests for CLI command structure - high value, low maintenance."""

import pytest
from typer.testing import CliRunner

from src.infrastructure.cli.app import app


@pytest.fixture
def runner():
    """CLI test runner."""
    return CliRunner()


class TestCoreCommandStructure:
    """Test that core command structure exists and is accessible."""

    def test_main_help_shows_core_commands(self, runner):
        """Ensure main help shows the core command groups."""
        result = runner.invoke(app, ["--help"])
        
        assert result.exit_code == 0
        assert "data" in result.stdout
        assert "playlist" in result.stdout
        assert "status" in result.stdout
        assert "setup" in result.stdout

    def test_version_command_works(self, runner):
        """Ensure version command is accessible."""
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "Narada" in result.stdout

    def test_status_command_exists(self, runner):
        """Ensure status command is accessible."""
        result = runner.invoke(app, ["status", "--help"])
        assert result.exit_code == 0
        assert "connection status" in result.stdout.lower()

    def test_setup_command_exists(self, runner):
        """Ensure setup command is accessible.""" 
        result = runner.invoke(app, ["setup", "--help"])
        assert result.exit_code == 0


class TestDataCommandStructure:
    """Test that data command structure exists and is accessible."""

    def test_data_help_shows_subcommands(self, runner):
        """Ensure data help shows all subcommands."""
        result = runner.invoke(app, ["data", "--help"])
        
        assert result.exit_code == 0
        assert "import-plays-file" in result.stdout
        assert "import-plays-lastfm" in result.stdout
        assert "import-likes-spotify" in result.stdout
        assert "export-likes-lastfm" in result.stdout
        assert "menu" in result.stdout

    def test_data_subcommands_have_help(self, runner):
        """Ensure all data subcommands have accessible help."""
        subcommands = [
            "menu",
            "import-plays-file", 
            "import-plays-lastfm",
            "import-likes-spotify",
            "export-likes-lastfm"
        ]
        
        for cmd in subcommands:
            result = runner.invoke(app, ["data", cmd, "--help"])
            assert result.exit_code == 0, f"Help failed for: data {cmd}"

    def test_data_menu_command_exists(self, runner):
        """Ensure data menu command is accessible."""
        result = runner.invoke(app, ["data", "menu", "--help"])
        assert result.exit_code == 0
        assert "music data" in result.stdout.lower()


class TestPlaylistCommandStructure:
    """Test that playlist command structure exists and is accessible."""

    def test_playlist_help_shows_subcommands(self, runner):
        """Ensure playlist help shows workflow subcommands."""
        result = runner.invoke(app, ["playlist", "--help"])
        
        assert result.exit_code == 0
        assert "run" in result.stdout
        assert "list" in result.stdout

    def test_playlist_subcommands_have_help(self, runner):
        """Ensure playlist subcommands have accessible help."""
        subcommands = ["list", "run"]
        
        for cmd in subcommands:
            result = runner.invoke(app, ["playlist", cmd, "--help"])
            assert result.exit_code == 0, f"Help failed for: playlist {cmd}"

    def test_playlist_list_command_exists(self, runner):
        """Ensure playlist list command is accessible."""
        result = runner.invoke(app, ["playlist", "list", "--help"])
        assert result.exit_code == 0

    def test_playlist_run_command_exists(self, runner):
        """Ensure playlist run command is accessible."""
        result = runner.invoke(app, ["playlist", "run", "--help"])
        assert result.exit_code == 0


class TestCommandGroupConsistency:
    """Test that command groups follow consistent patterns."""

    def test_all_commands_have_help(self, runner):
        """Ensure all top-level commands respond to --help."""
        commands = ["data", "playlist", "status", "setup", "version"]
        
        for cmd in commands:
            result = runner.invoke(app, [cmd, "--help"])
            assert result.exit_code == 0, f"Help failed for: {cmd}"

    def test_invalid_commands_fail_gracefully(self, runner):
        """Ensure invalid commands show helpful error messages."""
        result = runner.invoke(app, ["nonexistent-command"])
        
        # Should fail but not crash
        assert result.exit_code != 0
        assert "Usage:" in result.stdout or "No such command" in result.stdout

    def test_no_args_shows_help(self, runner):
        """Ensure running narada with no args shows help."""
        result = runner.invoke(app, [])
        
        assert result.exit_code == 0
        assert "Usage:" in result.stdout
        assert "data" in result.stdout
        assert "playlist" in result.stdout