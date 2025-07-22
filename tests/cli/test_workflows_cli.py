"""Tests for workflow CLI commands."""

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
def sample_workflow_definition():
    """Sample workflow definition for testing."""
    return {
        "id": "test_workflow",
        "name": "Test Workflow",
        "description": "A test workflow for CLI testing",
        "version": "1.0",
        "tasks": [
            {
                "id": "source_task",
                "type": "source.spotify_playlist",
                "config": {"playlist_id": "test123"}
            },
            {
                "id": "filter_task", 
                "type": "filter.deduplicate",
                "config": {},
                "upstream": ["source_task"]
            }
        ]
    }


@pytest.fixture 
def mock_workflow_definitions_dir(tmp_path, sample_workflow_definition):
    """Create temporary workflow definitions directory."""
    definitions_dir = tmp_path / "definitions"
    definitions_dir.mkdir()
    
    # Create sample workflow file
    workflow_file = definitions_dir / "test_workflow.json"
    with open(workflow_file, 'w') as f:
        json.dump(sample_workflow_definition, f)
        
    return definitions_dir


def test_list_workflows_function_exists():
    """Test that list_workflows function can be imported."""
    # Should now succeed - function exists
    from src.infrastructure.cli.workflows_commands import list_workflows
    assert callable(list_workflows)


def test_initialize_workflow_system_function_exists():
    """Test that initialize_workflow_system function can be imported.""" 
    # Should now succeed - function exists
    from src.infrastructure.cli.workflows_commands import initialize_workflow_system
    assert callable(initialize_workflow_system)


def test_workflows_list_command_shows_discovered_workflows(runner, mock_workflow_definitions_dir):
    """Test that workflows list command discovers and displays workflows."""
    # Mock the path resolution inside the list_workflows function
    with patch('src.infrastructure.cli.workflows_commands.list_workflows') as mock_list:
        # Configure mock to return our test workflow
        mock_list.return_value = [
            {
                "id": "test_workflow",
                "name": "Test Workflow", 
                "description": "A test workflow for CLI testing",
                "task_count": 2,
                "path": str(mock_workflow_definitions_dir / "test_workflow.json")
            }
        ]
        
        result = runner.invoke(app, ["playlist", "list"])
        
        # Should succeed and show workflow information
        assert result.exit_code == 0
        assert "Test Workflow" in result.stdout
        assert "test_workflow" in result.stdout
        assert "A test workflow for CLI testing" in result.stdout


def test_workflows_list_command_handles_empty_directory(runner, tmp_path):
    """Test that workflows list handles empty definitions directory gracefully."""
    # Mock list_workflows to return empty list
    with patch('src.infrastructure.cli.workflows_commands.list_workflows') as mock_list:
        mock_list.return_value = []
        
        result = runner.invoke(app, ["playlist", "list"])
        
        # Should succeed but show no workflows message
        assert result.exit_code == 0
        assert "No workflows found" in result.stdout


def test_workflow_discovery_parses_json_correctly(mock_workflow_definitions_dir, sample_workflow_definition):
    """Test that workflow discovery correctly parses JSON workflow definitions."""
    # Test the actual list_workflows function by mocking the definitions path directly
    from src.infrastructure.cli.workflows_commands import list_workflows
    
    # Create the test workflow file path
    test_workflow_file = mock_workflow_definitions_dir / "test_workflow.json"
    
    # Mock the Path construction and definitions_path to return our test directory
    with patch('src.infrastructure.cli.workflows_commands.Path') as mock_path_class:
        # Set up the path chain: Path(__file__).parent.parent.parent / "application" / "workflows" / "definitions"
        mock_current_file = mock_path_class.return_value
        mock_definitions_path = mock_current_file.parent.parent.parent.__truediv__.return_value.__truediv__.return_value.__truediv__.return_value
        
        # Mock the definitions path to exist and glob to return our test file
        mock_definitions_path.exists.return_value = True
        mock_definitions_path.glob.return_value = [test_workflow_file]
        
        workflows = list_workflows()
        
        # Should find our test workflow
        assert len(workflows) == 1
        workflow = workflows[0]
        assert workflow["id"] == "test_workflow"
        assert workflow["name"] == "Test Workflow" 
        assert workflow["description"] == "A test workflow for CLI testing"
        assert workflow["task_count"] == 2


def test_workflow_system_initialization():
    """Test that workflow system initializes correctly."""
    from src.infrastructure.cli.workflows_commands import initialize_workflow_system
    
    # Should return success and message
    success, message = initialize_workflow_system()
    assert isinstance(success, bool)
    assert isinstance(message, str)
    assert len(message) > 0