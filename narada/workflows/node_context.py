"""Context management for node operations.

Provides specialized extraction patterns for workflow operations,
implementing efficient path-based access to nested domain structures.
This module decouples data access patterns from orchestration logic.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from functools import cached_property
from typing import Any, Self

from narada.core.protocols import Track

# Domain types
type TrackList = list[Track]
type TaskID = str
type DataPath = str | list[str]
type ContextData = dict[str, Any]


@dataclass(frozen=True)
class Context:
    """Immutable extraction context with path-based access patterns.

    Encapsulates data extraction strategies for nested workflow data,
    providing a consistent interface for accessing domain objects.
    """

    data: ContextData

    def extract(self, path: DataPath) -> Any:
        """Extract value from nested data structure using path notation.

        Args:
            path: Dot notation string or list of path segments

        Returns:
            Extracted value or None if path doesn't exist

        Example:
            >>> ctx.extract("results.spotify.tracks")
            [{"title": "Song1", ...}, {"title": "Song2", ...}]
        """
        segments = path.split(".") if isinstance(path, str) else path

        # Use walrus operator with pattern matching for elegant traversal
        if value := self.data:
            for segment in segments:
                match value:
                    case dict() if segment in value:
                        value = value[segment]
                    case _:
                        return None
            return value
        return None

    def extract_tracklist(self) -> TrackList:
        """Extract primary tracklist from context.

        Returns:
            List of track objects from primary result
        """
        match self.data:
            case {"result": {"tracks": tracks}} if isinstance(tracks, list):
                return tracks
            case {"tracks": tracks} if isinstance(tracks, list):
                return tracks
            case _:
                return []

    def extract_task_result(self, task_id: TaskID) -> Any:
        """Extract specific task result from the context.

        Args:
            task_id: Identifier of the task to extract

        Returns:
            Task result or None if not found
        """
        return self.extract(f"task_results.{task_id}")

    @cached_property
    def metadata(self) -> dict[str, Any]:
        """Extract and cache metadata from context.

        Returns:
            Consolidated metadata dictionary
        """
        return self.extract("metadata") or {}

    def collect_tracklists(self, task_ids: Sequence[TaskID]) -> list[TrackList]:
        """Collect tracklists from multiple task results.

        Args:
            task_ids: Sequence of task IDs to collect tracklists from

        Returns:
            List of tracklists from specified tasks
        """
        return [
            tracks
            for task_id in task_ids
            if (result := self.extract_task_result(task_id))
            and (tracks := self._extract_tracks_from_result(result))
        ]

    def create_child(self, data: ContextData) -> Self:
        """Create a child context with new data, inheriting parent context.

        Args:
            data: New data to merge with existing context

        Returns:
            New context instance with merged data
        """
        return type(self)({**self.data, **data})

    def _extract_tracks_from_result(self, result: Any) -> TrackList:
        """Extract tracks from a task result using pattern matching.

        Args:
            result: Task result to extract tracks from

        Returns:
            List of track objects or empty list if not found
        """
        match result:
            case {"tracks": tracks} if isinstance(tracks, list):
                return tracks
            case {"result": {"tracks": tracks}} if isinstance(tracks, list):
                return tracks
            case list() if all(isinstance(item, dict) for item in result):
                return result
            case _:
                return []
