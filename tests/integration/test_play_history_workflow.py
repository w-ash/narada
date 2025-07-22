"""Integration test for play history workflow."""

import json
from pathlib import Path

import pytest

from src.application.workflows import validate_registry


class TestPlayHistoryWorkflowIntegration:
    """Test play history workflow integration."""

    def test_registry_validation_passes(self):
        """Test that registry validation passes with play history nodes."""
        success, message = validate_registry()
        assert success is True
        assert "19 nodes" in message

    @pytest.fixture
    def test_workflow(self):
        """Load test workflow definition."""
        workflow_path = Path(__file__).parent.parent.parent / "src/application/workflows/definitions/test_play_history.json"
        with open(workflow_path) as f:
            return json.load(f)

    def test_workflow_definition_is_valid(self, test_workflow):
        """Test that play history workflow definition is valid."""
        # Verify workflow structure
        assert test_workflow["id"] == "test_play_history"
        assert "tasks" in test_workflow
        assert len(test_workflow["tasks"]) == 5

        # Verify task types exist in registry
        task_types = [task["type"] for task in test_workflow["tasks"]]
        expected_types = [
            "source.spotify_playlist",
            "enricher.play_history", 
            "filter.by_play_history",
            "sorter.by_metric",
            "selector.limit_tracks"
        ]
        assert task_types == expected_types

    def test_workflow_task_dependencies(self, test_workflow):
        """Test that workflow task dependencies are correct."""
        tasks = {task["id"]: task for task in test_workflow["tasks"]}
        
        # Verify dependency chain
        assert "upstream" not in tasks["source_test_tracks"]
        assert tasks["enrich_play_history"]["upstream"] == ["source_test_tracks"]
        assert tasks["filter_recently_played_tracks"]["upstream"] == ["enrich_play_history"]
        assert tasks["sort_by_play_count"]["upstream"] == ["filter_recently_played_tracks"]
        assert tasks["limit_results"]["upstream"] == ["sort_by_play_count"]