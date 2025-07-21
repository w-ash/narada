"""Async helpers for CLI commands to eliminate duplication."""

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from functools import wraps
from typing import Any, cast

from rich.console import Console

from src.application.utilities.progress_integration import DatabaseProgressContext
from src.domain.entities import OperationResult
from src.infrastructure.cli.ui import command_error_handler

console = Console()


def async_db_operation(
    progress_text: str = "Processing...",
    success_text: str = "Operation completed!",
    display_title: str | None = None,
    next_step_message: str | None = None,
) -> Callable[
    [Callable[..., Awaitable[OperationResult]]],
    Callable[..., Awaitable[OperationResult]],
]:
    """Decorator for async operations that need database access.

    Now uses the DatabaseProgressContext for session-per-operation pattern.

    Args:
        progress_text: Text to show during operation
        success_text: Text to show on success
        display_title: Title for result display
        next_step_message: Optional next step hint
    """

    def decorator(
        func: Callable[..., Awaitable[OperationResult]],
    ) -> Callable[..., Awaitable[OperationResult]]:
        @command_error_handler
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> OperationResult:
            # Use DatabaseProgressContext for session-per-operation pattern
            async with DatabaseProgressContext(
                description=progress_text,
                success_text=success_text,
                display_title=display_title,
                next_step_message=next_step_message,
            ) as progress:
                # Execute the function with fresh repositories
                return await progress.run_with_repositories(func, *args, **kwargs)

        return wrapper

    return decorator


def async_operation(
    progress_text: str = "Processing...",
    success_text: str = "Operation completed!",
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., None]]:
    """Decorator for simple async operations without database access.

    Now uses the unified progress system for consistent experience.

    Args:
        progress_text: Text to show during operation
        success_text: Text to show on success
    """

    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., None]:
        @command_error_handler
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> None:
            # Import here to avoid circular imports
            from src.application.utilities.progress_integration import with_progress

            # Apply progress decorator and execute
            progress_func = with_progress(progress_text, success_text=success_text)(
                func
            )
            result = progress_func(*args, **kwargs)
            # Ensure we handle the async result properly
            if asyncio.iscoroutine(result):
                # Cast to proper coroutine type for asyncio.run
                asyncio.run(result)  # type: ignore[arg-type]
                return None
            return None

        return wrapper

    return decorator


def interactive_async_operation() -> Callable[
    [Callable[..., Awaitable[Any]]], Callable[..., None]
]:
    """Decorator for interactive async operations with custom progress handling.

    For operations that manage their own progress display (like workflows).

    Args:
        initial_text: Initial progress text
    """

    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., None]:
        @command_error_handler
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> None:
            coro = func(*args, **kwargs)
            return asyncio.run(cast("Coroutine[Any, Any, Any]", coro))

        return wrapper

    return decorator
