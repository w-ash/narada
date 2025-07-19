"""Context management for node operations.

Provides specialized extraction patterns for workflow operations,
implementing efficient path-based access to nested domain structures.
This module decouples data access patterns from orchestration logic.
"""

from dataclasses import dataclass
from typing import Any

from src.config import get_logger
from src.domain.entities.track import TrackList

logger = get_logger(__name__)

# Domain types
type TaskID = str
type DataPath = str | list[str]
type ContextData = dict[str, Any]


@dataclass(frozen=True)
class NodeContext:
    """Context extractor with path-based access."""

    data: dict

    def __init__(self, data: dict) -> None:
        object.__setattr__(self, "data", data)

    def get(self, path: str, default: Any = None) -> Any:
        """Get value from nested context using dot notation."""
        parts = path.split(".")
        current = self.data
        for part in parts:
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        return current

    def extract_tracklist(self) -> TrackList:
        """Extract primary tracklist from context.

        Supports both workflow contexts (with upstream_task_id) and direct contexts
        (with tracklist key) for testing compatibility.
        """
        # Check for workflow context with upstream task
        if "upstream_task_id" in self.data:
            upstream_id = self.data["upstream_task_id"]
            if upstream_id in self.data and "tracklist" in self.data[upstream_id]:
                return self.data[upstream_id]["tracklist"]

        # Check for direct tracklist (testing/simple contexts)
        if "tracklist" in self.data:
            tracklist = self.data["tracklist"]
            if isinstance(tracklist, TrackList):
                return tracklist

        raise ValueError(
            "Missing required tracklist from upstream node or direct context"
        )

    def collect_tracklists(self, task_ids: list[str]) -> list[TrackList]:
        """Collect tracklists from multiple task results."""
        tracklists = []
        for task_id in task_ids:
            if task_id not in self.data:
                logger.warning(f"Task ID not found in context: {task_id}")
                continue

            task_result = self.data[task_id]
            if not isinstance(task_result, dict):
                logger.warning(f"Invalid task result for {task_id}: not a dictionary")
                continue

            tracklist = task_result.get("tracklist")
            if not isinstance(tracklist, TrackList):
                logger.warning(
                    f"Missing or invalid tracklist in task result: {task_id}",
                )
                continue

            tracklists.append(tracklist)

        if not tracklists:
            # This should raise an exception rather than just logging
            raise ValueError(f"No valid tracklists found in upstream tasks: {task_ids}")

        return tracklists
