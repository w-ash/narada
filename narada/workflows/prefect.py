"""
Prefect v3 integration layer for workflow execution.

This module provides a thin adapter between Narada's node system
and Prefect's execution engine, enabling declarative workflows to be
executed with enterprise-grade reliability.
"""

from collections.abc import Callable
import datetime
from typing import Any, NotRequired, TypedDict

from prefect import flow, task
from prefect.logging import get_run_logger

from narada.config import configure_prefect_logging, get_logger
from narada.workflows.node_registry import get_node

# Initialize Prefect logging to use our Loguru setup
configure_prefect_logging()

# Normal module-level logger using our existing pattern
logger = get_logger(__name__)

# --- Progress callbacks ---

_progress_callbacks: list[Callable] = []


def register_progress_callback(callback: Callable) -> None:
    """Register a callback to receive workflow progress events."""
    _progress_callbacks.append(callback)


def emit_progress_event(event_type: str, event_data: dict[str, Any]) -> None:
    """Emit a progress event to all registered callbacks."""
    for callback in _progress_callbacks:
        try:
            callback(event_type, event_data)
        except Exception as e:
            logger.warning(f"Progress callback error: {e}")


# --- Node execution ---


class TaskResult(TypedDict):
    """Type definition for task results."""

    success: bool
    result: Any
    error: NotRequired[str]


@task(
    retries=3,
    retry_delay_seconds=30,
    tags=["node"],
)
async def execute_node(node_type: str, context: dict, config: dict) -> dict:
    """Execute a single workflow node as a Prefect task."""
    # Use Prefect's run logger to get task context
    task_logger = get_run_logger()

    # Log node execution
    task_logger.info(f"Executing node: {node_type}")

    # Get node implementation
    node_func, _ = get_node(node_type)

    try:
        # Execute node with direct configuration
        # No template resolution - config passes through unchanged
        result = await node_func(context, config)
        task_logger.info(f"Node completed successfully: {node_type}")
        return result

    except Exception as e:
        task_logger.exception(f"Node failed: {e} (type: {node_type})")
        raise


# --- Flow building ---


def generate_flow_run_name(flow_name: str) -> str:
    """Generate a dynamic flow run name with a timestamp."""
    return (
        f"{flow_name}-{datetime.datetime.now(datetime.UTC).strftime('%Y%m%d-%H%M%S')}"
    )


def build_flow(workflow_def: dict) -> Any:
    """Build an executable Prefect flow from a workflow definition."""

    # Extract workflow metadata
    flow_name = workflow_def.get("name", "unnamed_workflow")
    flow_description = workflow_def.get("description", "")
    tasks = workflow_def.get("tasks", [])

    # Create a topological sort of tasks based on dependencies
    def topological_sort(tasks):
        """Sort tasks to ensure dependencies execute first."""
        # Create a dependency graph
        graph = {task["id"]: task.get("upstream", []) for task in tasks}

        # Find execution order
        visited = set()
        result = []

        def visit(node_id):
            if node_id in visited:
                return
            visited.add(node_id)
            for dep in graph[node_id]:
                visit(dep)
            result.append(next(t for t in tasks if t["id"] == node_id))

        for task_id in graph:
            visit(task_id)

        return result

    # Sort tasks in execution order
    sorted_tasks = topological_sort(tasks)

    @flow(
        name=flow_name,
        description=flow_description,
        flow_run_name=generate_flow_run_name(flow_name),
    )
    async def workflow_flow(**parameters):
        """Dynamically generated Prefect flow from workflow definition."""
        # Use Prefect's run logger to get flow context
        flow_logger = get_run_logger()
        flow_logger.info("Starting workflow")

        # Initialize execution context with parameters
        context = {"parameters": parameters}
        task_results = {}

        # Execute tasks in dependency order
        for task_def in sorted_tasks:
            task_id = task_def["id"]
            node_type = task_def["type"]

            # Emit task started event
            emit_progress_event(
                "task_started",
                {"task_id": task_id, "task_name": task_id, "task_type": node_type},
            )

            # Log the task start
            flow_logger.info(f"Starting task: {task_id} (type: {node_type})")

            # Resolve configuration with current context
            config = task_def.get("config", {})

            # Create task-specific context with upstream results
            task_context = context.copy()

            if task_def.get("upstream"):
                if len(task_def["upstream"]) == 1:
                    # Single upstream case
                    task_context["upstream_task_id"] = task_def["upstream"][0]
                else:
                    # Multiple upstream case - first one is primary by convention
                    # (unless config specifies a primary_input)
                    primary_input = config.get("primary_input")
                    if primary_input and primary_input in task_def["upstream"]:
                        task_context["upstream_task_id"] = primary_input
                    else:
                        task_context["upstream_task_id"] = task_def["upstream"][0]

                # Add all upstream tasks as a list for nodes that need multiple inputs
                task_context["upstream_task_ids"] = task_def["upstream"]

                # Copy upstream task results into context
                for upstream_id in task_def["upstream"]:
                    if upstream_id in task_results:
                        task_context[upstream_id] = task_results[upstream_id]

            # Execute node as a task
            result = await execute_node(node_type, task_context, config)

            # Store result in context and task_results
            context[task_id] = result
            task_results[task_id] = result

            # Also store in context under node-specified result key if present
            if result_key := task_def.get("result_key"):
                flow_logger.debug(f"Storing result under key: {result_key}")
                context[result_key] = result

            # Emit task completed event
            emit_progress_event(
                "task_completed",
                {
                    "task_id": task_id,
                    "task_name": task_id,
                    "task_type": node_type,
                    "result": result,
                },
            )

        flow_logger.info("Workflow completed successfully")
        return context

    # Return the decorated flow function
    return workflow_flow


# --- Workflow execution ---


async def run_workflow(workflow_def: dict, **parameters) -> dict:
    """Run a workflow with the given parameters."""
    # Use module logger for code outside of tasks/flows
    workflow_name = workflow_def.get("name", "unnamed")
    logger.info(f"Running workflow: {workflow_name}")

    # Build the flow
    workflow = build_flow(workflow_def)

    # Execute the flow - consider passing deployment-specific parameters if needed
    result = await workflow(**parameters)

    # Log completion
    logger.info(f"Workflow execution complete: {workflow_name}")

    return result
