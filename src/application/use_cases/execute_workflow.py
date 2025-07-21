"""WorkflowExecutor use case following Clean Architecture patterns.

This module implements workflow execution as a proper use case that manages
infrastructure concerns (database sessions) through the workflow context.
It provides a clean interface for workflow execution without direct session management.
"""

from datetime import UTC, datetime
from typing import Any

from attrs import define

from src.config import get_logger
from src.domain.entities.operations import WorkflowResult

logger = get_logger(__name__)


@define(frozen=True, slots=True)
class WorkflowCommand:
    """Command for workflow execution with rich context."""

    workflow_def: dict[str, Any]
    parameters: dict[str, Any]

    def validate(self) -> bool:
        """Validate command business rules."""
        if not self.workflow_def:
            return False
        return "tasks" in self.workflow_def


@define(frozen=True, slots=True)
class WorkflowExecutionResult:
    """Result of workflow execution with operational metadata."""

    context: dict[str, Any]
    workflow_result: WorkflowResult
    execution_time_ms: int
    success: bool
    error_message: str | None = None


class WorkflowExecutor:
    """Use case for workflow execution with Clean Architecture compliance.

    This use case coordinates workflow execution and provides a clean interface
    for different presentation layers (CLI, API, etc.). It delegates to the
    workflow engine while managing the overall execution lifecycle.
    """

    async def execute(self, command: WorkflowCommand) -> WorkflowExecutionResult:
        """Execute workflow with proper lifecycle management.

        Args:
            command: Workflow execution command

        Returns:
            Result with execution context and metadata

        Raises:
            ValueError: If command validation fails
        """
        if not command.validate():
            raise ValueError(
                "Invalid workflow command: failed business rule validation"
            )

        start_time = datetime.now(UTC)

        try:
            # Import here to avoid circular imports
            from src.application.workflows.prefect import run_workflow

            # Execute workflow - context provides proper session management
            context, workflow_result = await run_workflow(
                command.workflow_def, **command.parameters
            )

            # Calculate execution time
            end_time = datetime.now(UTC)
            execution_time_ms = int((end_time - start_time).total_seconds() * 1000)

            return WorkflowExecutionResult(
                context=context,
                workflow_result=workflow_result,
                execution_time_ms=execution_time_ms,
                success=True,
            )

        except Exception as e:
            logger.exception(f"Workflow execution failed: {e}")
            end_time = datetime.now(UTC)
            execution_time_ms = int((end_time - start_time).total_seconds() * 1000)

            return WorkflowExecutionResult(
                context={},
                workflow_result=WorkflowResult(
                    workflow_name=command.workflow_def.get("name", "unknown"),
                    success=False,
                    tracks_processed=0,
                    playlists_created=0,
                    execution_time_seconds=execution_time_ms / 1000,
                    error_message=str(e),
                ),
                execution_time_ms=execution_time_ms,
                success=False,
                error_message=str(e),
            )


# Convenience function for single workflow execution
async def execute_workflow_use_case(
    workflow_def: dict, **parameters
) -> WorkflowExecutionResult:
    """Execute workflow through the use case pattern.

    This function provides a clean interface for workflow execution
    that can be used by different presentation layers.

    Args:
        workflow_def: Workflow definition
        **parameters: Dynamic parameters for workflow

    Returns:
        Workflow execution result
    """
    command = WorkflowCommand(workflow_def=workflow_def, parameters=parameters)

    executor = WorkflowExecutor()
    return await executor.execute(command)
