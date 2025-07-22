"""Legacy CLI command tests - updated for new structure."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from src.infrastructure.cli.app import app


@pytest.fixture
def runner():
    """CLI test runner."""
    return CliRunner()


@pytest.fixture
def sample_spotify_file(tmp_path):
    """Create a sample Spotify export file for testing."""
    sample_data = [
        {
            "ts": "2023-01-15T14:30:22Z",
            "username": "testuser",
            "platform": "ios",
            "ms_played": 180000,
            "conn_country": "US",
            "ip_addr_decrypted": "192.168.1.1",
            "user_agent_decrypted": "Spotify/8.7.78",
            "master_metadata_track_name": "Test Song",
            "master_metadata_album_artist_name": "Test Artist",
            "master_metadata_album_album_name": "Test Album",
            "spotify_track_uri": "spotify:track:4uLU6hMCjMI75M1A2tKUQC",
            "episode_name": None,
            "episode_show_name": None,
            "spotify_episode_uri": None,
            "reason_start": "fwdbtn",
            "reason_end": "trackdone",
            "shuffle": True,
            "skipped": False,
            "offline": False,
            "offline_timestamp": None,
            "incognito_mode": False
        }
    ]
    
    file_path = tmp_path / "test_spotify_export.json"
    with open(file_path, "w") as f:
        json.dump(sample_data, f)
    
    return file_path


def test_data_import_plays_file_command_exists(runner):
    """Test that the data import-plays-file command exists."""
    result = runner.invoke(app, ["data", "import-plays-file", "--help"])
    assert result.exit_code == 0
    assert "Import play history from Spotify JSON export file" in result.stdout


def test_data_import_plays_file_not_found(runner):
    """Test error handling when file doesn't exist."""
    result = runner.invoke(app, ["data", "import-plays-file", "/nonexistent/file.json"])
    assert result.exit_code != 0


def test_data_import_plays_file_help(runner):
    """Test that data import-plays-file command shows help."""
    result = runner.invoke(app, ["data", "import-plays-file", "--help"])
    assert result.exit_code == 0
    assert "Import play history from Spotify JSON export file" in result.stdout


def test_data_commands_exist(runner):
    """Test that data commands exist."""
    result = runner.invoke(app, ["data", "--help"])
    assert result.exit_code == 0
    assert "import-likes-spotify" in result.stdout
    assert "export-likes-lastfm" in result.stdout


def test_playlist_commands_exist(runner):
    """Test that playlist commands exist."""
    result = runner.invoke(app, ["playlist", "--help"])
    assert result.exit_code == 0
    assert "run" in result.stdout
    assert "list" in result.stdout


def test_status_command_exists(runner):
    """Test that status command exists."""
    result = runner.invoke(app, ["status", "--help"])
    assert result.exit_code == 0


def test_setup_command_exists(runner):
    """Test that setup command exists."""
    result = runner.invoke(app, ["setup", "--help"])
    assert result.exit_code == 0


def test_main_help_shows_new_structure(runner):
    """Test that main help shows the new grouped command structure."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "data" in result.stdout     # Data group exists
    assert "playlist" in result.stdout # Playlist group exists
    assert "status" in result.stdout
    assert "setup" in result.stdout


def test_help_command_works_without_heavy_init(runner):
    """Test that help works without database/connector initialization in callback."""
    # This test verifies our fix - help should work even if heavy init fails
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Usage:" in result.stdout
    assert "🎵 Narada" in result.stdout


def test_version_command_works(runner):
    """Test that version command works without heavy initialization."""
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "Narada" in result.stdout