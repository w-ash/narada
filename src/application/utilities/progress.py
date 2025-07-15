"""
Universal progress tracking abstraction for Narada.

Provides a DRY, type-safe progress tracking system that works across
CLI, workflows, and future web interfaces. Follows 2025 best practices
for async operations and Rich library integration.

Clean Architecture compliant - no external dependencies.
"""

from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from attrs import define, field


@define(frozen=True, slots=True)
class ProgressOperation:
    """Immutable progress operation descriptor."""

    operation_id: str = field(factory=lambda: str(uuid4()))
    description: str = "Processing..."
    total_items: int | None = None  # None = indeterminate/spinner mode
    current_items: int = 0
    start_time: datetime = field(factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(factory=dict)

    @property
    def is_indeterminate(self) -> bool:
        """True if this is an indeterminate (spinner-only) operation."""
        return self.total_items is None

    @property
    def progress_percentage(self) -> float:
        """Calculate progress percentage (0-100)."""
        if self.is_indeterminate or self.total_items == 0:
            return 0.0
        # Type guard: self.total_items is not None here due to checks above
        if self.total_items is None:
            return 0.0
        return min(100.0, (self.current_items / self.total_items) * 100)

    @property
    def is_complete(self) -> bool:
        """True if operation is complete."""
        if self.is_indeterminate:
            return False
        return self.current_items >= (self.total_items or 0)


class ProgressProvider(Protocol):
    """Protocol for progress display providers.

    Enables multiple implementations (Rich CLI, web UI, notifications)
    while maintaining consistent interface across the application.
    """

    def start_operation(self, operation: ProgressOperation) -> str:
        """Start tracking a new operation.

        Args:
            operation: Operation descriptor

        Returns:
            Operation ID for future updates
        """
        ...

    def update_progress(
        self,
        operation_id: str,
        current: int,
        total: int | None = None,
        description: str | None = None,
    ) -> None:
        """Update progress for an existing operation.

        Args:
            operation_id: ID returned from start_operation
            current: Current progress value
            total: Total items (can update from indeterminate to determinate)
            description: Optional description update
        """
        ...

    def set_description(self, operation_id: str, description: str) -> None:
        """Update operation description.

        Args:
            operation_id: Operation ID
            description: New description text
        """
        ...

    def complete_operation(self, operation_id: str) -> None:
        """Mark operation as complete and clean up.

        Args:
            operation_id: Operation ID to complete
        """
        ...

    def is_long_running_operation(self, operation: ProgressOperation) -> bool:
        """Determine if operation should show detailed progress.

        Args:
            operation: Operation to evaluate

        Returns:
            True if operation should show progress bar vs simple spinner
        """
        ...


class NoOpProgressProvider:
    """No-operation progress provider for headless/testing scenarios."""

    def start_operation(self, operation: ProgressOperation) -> str:
        return operation.operation_id

    def update_progress(
        self,
        operation_id: str,
        current: int,
        total: int | None = None,
        description: str | None = None,
    ) -> None:
        pass

    def set_description(self, operation_id: str, description: str) -> None:
        pass

    def complete_operation(self, operation_id: str) -> None:
        pass

    def is_long_running_operation(self, operation: ProgressOperation) -> bool:  # noqa: ARG002
        return False


# Global provider instance - can be swapped for different environments
_global_provider: ProgressProvider | None = None


def set_progress_provider(provider: ProgressProvider) -> None:
    """Set the global progress provider.

    Args:
        provider: Progress provider implementation
    """
    global _global_provider
    _global_provider = provider


def get_progress_provider() -> ProgressProvider:
    """Get current global progress provider.

    Returns:
        Current progress provider (defaults to NoOp if none set)
    """
    return _global_provider or NoOpProgressProvider()


def create_operation(
    description: str,
    total_items: int | None = None,
    **metadata: Any,
) -> ProgressOperation:
    """Create a new progress operation descriptor.

    Args:
        description: Human-readable operation description
        total_items: Total items to process (None for indeterminate)
        **metadata: Additional metadata for the operation

    Returns:
        New progress operation
    """
    return ProgressOperation(
        description=description,
        total_items=total_items,
        metadata=metadata,
    )
