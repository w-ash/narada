"""
Prefect v3 integration layer for workflow execution.

This module provides a thin adapter between Narada's node system
and Prefect's execution engine, enabling declarative workflows to be
executed with enterprise-grade reliability.
"""

from collections.abc import Callable
import datetime
import re
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


# --- Template resolution ---


def resolve_templates(value: Any, context: dict) -> Any:
    """Recursively resolve template variables in configs.

    Templates use the format: {key.nested.path}
    """
    match value:
        case str() if "{" in value:
            # Find all template patterns {key.path}
            pattern = r"\{([\w\.]+)\}"

            def replace_match(match):
                path = match.group(1).split(".")
                current = context

                # Traverse the path to get the value
                try:
                    for key in path:
                        current = current[key]
                    return str(current)
                except (KeyError, TypeError):
                    # Return the original template if path not found
                    return match.group(0)

            # Replace all template patterns
            return re.sub(pattern, replace_match, value)
        case dict():
            # Recursively process dictionary values
            return {k: resolve_templates(v, context) for k, v in value.items()}
        case list():
            # Recursively process list items
            return [resolve_templates(item, context) for item in value]
        case _:
            # Return other values unchanged
            return value


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

    # Log with f-string instead of extra={}
    task_logger.info(f"Executing node: {node_type}")

    # Get node implementation, use _ to indicate unused variable
    node_func, _ = get_node(node_type)

    # Resolve template variables in config
    resolved_config = resolve_templates(config, context)

    try:
        # Execute the node
        result = await node_func(context, resolved_config)
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
        flow_run_name=generate_flow_run_name(
            flow_name,
        ),  # Dynamic flow run name with timestamp
    )
    async def workflow_flow(**parameters):
        """Dynamically generated Prefect flow from workflow definition."""
        # Use Prefect's run logger to get flow context
        flow_logger = get_run_logger()
        flow_logger.info("Starting workflow")

        # Initialize execution context with parameters
        context = {"parameters": parameters}

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

            # Execute node as a task - Prefect v3 automatically tracks dependencies
            result = await execute_node(node_type, context, config)

            # Store result in context with task ID as key
            context[task_id] = result

            # Also store in context under node-specified result key if present
            if result_key := task_def.get("result_key"):
                # Simplified logging with f-string
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
