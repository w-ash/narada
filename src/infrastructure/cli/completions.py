"""Minimal autocompletion functions for Narada CLI."""

import json
from pathlib import Path


def _get_workflow_definitions_path() -> Path:
    """Get the path to workflow definitions directory."""
    current_file = Path(__file__)
    return current_file.parent.parent / "workflows" / "definitions"


def complete_workflow_names(incomplete: str) -> list[str]:
    """Complete workflow names from definitions directory."""
    try:
        definitions_path = _get_workflow_definitions_path()

        if not definitions_path.exists():
            return []

        workflow_names = []
        for json_file in definitions_path.glob("*.json"):
            try:
                with open(json_file) as f:
                    definition = json.load(f)
                workflow_id = definition.get("id", json_file.stem)
                if workflow_id.startswith(incomplete):
                    workflow_names.append(workflow_id)
            except (OSError, json.JSONDecodeError):
                continue

        return sorted(workflow_names)

    except Exception:
        return []
