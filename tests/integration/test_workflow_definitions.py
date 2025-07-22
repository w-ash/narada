"""Integration tests for workflow definition validation."""

import json
from pathlib import Path

import pytest


class TestWorkflowDefinitionValidation:
    """Test validation of workflow definition structure and content."""

    @pytest.fixture
    def workflow_definitions_path(self):
        """Get path to workflow definitions directory."""
        return (
            Path(__file__).parent.parent.parent / "src" / "application" / "workflows" / "definitions"
        )

    def test_workflow_definitions_directory_exists(self, workflow_definitions_path):
        """Test that workflow definitions directory exists."""
        assert workflow_definitions_path.exists(), (
            "Workflow definitions directory not found"
        )
        assert workflow_definitions_path.is_dir(), (
            "Workflow definitions path is not a directory"
        )

    def test_workflow_definitions_valid_json(self, workflow_definitions_path):
        """Test that all workflow definitions are valid JSON."""
        for json_file in workflow_definitions_path.glob("*.json"):
            with open(json_file) as f:
                try:
                    json.load(f)
                except json.JSONDecodeError as e:
                    pytest.fail(f"Invalid JSON in {json_file.name}: {e}")

    def test_workflow_definitions_required_fields(self, workflow_definitions_path):
        """Test that workflow definitions have required fields."""
        required_fields = ["name", "tasks"]

        for json_file in workflow_definitions_path.glob("*.json"):
            with open(json_file) as f:
                definition = json.load(f)

            for field in required_fields:
                assert field in definition, (
                    f"Missing required field '{field}' in {json_file.name}"
                )

    def test_workflow_task_structure(self, workflow_definitions_path):
        """Test that workflow tasks have proper structure."""
        for json_file in workflow_definitions_path.glob("*.json"):
            with open(json_file) as f:
                definition = json.load(f)

            tasks = definition.get("tasks", [])
            assert len(tasks) > 0, f"No tasks defined in {json_file.name}"

            for task in tasks:
                task_id = task.get("id", "unknown")
                # Each task should have required fields
                assert "id" in task, f"Task missing id in {json_file.name}"
                assert "type" in task, (
                    f"Task '{task_id}' missing type in {json_file.name}"
                )

                # Types are namespaced like "source.spotify_playlist"
                task_type = task["type"]
                assert "." in task_type, (
                    f"Task type should be namespaced: {task_type} in {json_file.name}"
                )

    def test_workflow_dependency_validation(self, workflow_definitions_path):
        """Test that workflow dependencies reference existing tasks."""
        for json_file in workflow_definitions_path.glob("*.json"):
            with open(json_file) as f:
                definition = json.load(f)

            tasks = definition.get("tasks", [])
            task_ids = {task["id"] for task in tasks}

            for task in tasks:
                task_id = task.get("id", "unknown")
                dependencies = task.get("upstream", [])
                for dependency in dependencies:
                    assert dependency in task_ids, (
                        f"Task '{task_id}' depends on non-existent task '{dependency}' in {json_file.name}"
                    )

    def test_workflow_no_circular_dependencies(self, workflow_definitions_path):
        """Test that workflows don't have circular dependencies."""
        for json_file in workflow_definitions_path.glob("*.json"):
            with open(json_file) as f:
                definition = json.load(f)

            # Build dependency graph
            tasks = definition.get("tasks", [])
            dependencies = {}

            for task in tasks:
                task_id = task["id"]
                dependencies[task_id] = task.get("upstream", [])

            # Check for circular dependencies using topological sort
            def has_circular_dependency(deps):
                visited = set()
                rec_stack = set()

                def dfs(node):
                    if node in rec_stack:
                        return True  # Circular dependency found
                    if node in visited:
                        return False

                    visited.add(node)
                    rec_stack.add(node)

                    for neighbor in deps.get(node, []):
                        if dfs(neighbor):
                            return True

                    rec_stack.remove(node)
                    return False

                return any(task not in visited and dfs(task) for task in deps)

            assert not has_circular_dependency(dependencies), (
                f"Circular dependency detected in {json_file.name}"
            )
