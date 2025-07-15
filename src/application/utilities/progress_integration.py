"""
Universal progress integration for Narada services and CLI operations.

Provides decorators and utilities for seamless progress tracking
across async operations, batch processing, and CLI commands.

Clean Architecture compliant - uses dependency injection for external concerns.
"""

import asyncio
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, ParamSpec, Protocol, TypeVar

from src.domain.entities.operations import OperationResult
from .progress import (
    ProgressProvider,
    create_operation,
    get_progress_provider,
    set_progress_provider,
)

T = TypeVar("T")
P = ParamSpec("P")
U = TypeVar("U")


# Protocols for dependency injection (Clean Architecture compliance)
class Console(Protocol):
    """Protocol for console output."""
    
    def print(self, text: str) -> None:
        """Print text to console."""
        ...




class RepositoryProvider(Protocol):
    """Protocol for repository access."""
    # Will be defined based on actual repository interface needs


class SessionProvider(Protocol):
    """Protocol for database session management."""
    
    async def __aenter__(self) -> Any:
        """Async context manager entry."""
        ...
    
    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        ...


class UIProvider(Protocol):
    """Protocol for UI operations."""
    
    def display_operation_result(
        self,
        result: OperationResult,
        title: str | None = None,
        next_step_message: str | None = None,
    ) -> None:
        """Display operation result."""
        ...


def with_progress(
    description: str,
    *,
    estimate_total: Callable[[Any], int] | None = None,
    extract_items: Callable[[Any], list[Any]] | None = None,
    success_text: str = "Operation completed!",
    console: Console | None = None,
    progress_provider_factory: Callable[[], ProgressProvider] | None = None,
) -> Callable[[Callable[P, Awaitable[U]]], Callable[P, Awaitable[U]]]:
    """Universal progress decorator for async operations.
    
    Automatically manages progress tracking for any async operation,
    with optional smart total estimation and item extraction.
    
    Args:
        description: Human-readable operation description
        estimate_total: Optional function to estimate total items from args
        extract_items: Optional function to extract items list from args
        success_text: Success message to display on completion
        console: Optional console for output (injected dependency)
        progress_provider_factory: Optional factory for progress provider
    
    Examples:
        @with_progress("Matching tracks to LastFM")
        async def match_tracks(tracks: list[Track]) -> MatchResults:
            # Progress automatically tracked
            
        @with_progress("Processing playlist", 
                      estimate_total=lambda playlist: len(playlist.tracks))
        async def process_playlist(playlist: Playlist) -> Result:
            # Total estimated from playlist size
    """
    def decorator(func: Callable[P, Awaitable[U]]) -> Callable[P, Awaitable[U]]:
        @wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> U:
            # Smart total estimation
            import contextlib
            total_items = None
            if estimate_total:
                with contextlib.suppress(Exception):
                    total_items = estimate_total(args[0] if args else None)
            elif extract_items:
                with contextlib.suppress(Exception):
                    items = extract_items(args[0] if args else None)
                    total_items = len(items) if items else None
            
            # Create and start operation
            operation = create_operation(description, total_items)
            
            # Use injected progress provider or get global one
            if progress_provider_factory:
                provider = progress_provider_factory()
                set_progress_provider(provider)
            else:
                provider = get_progress_provider()
            
            operation_id = provider.start_operation(operation)
            
            try:
                # Execute with progress context
                result = await func(*args, **kwargs)
                
                # Mark as complete
                provider.complete_operation(operation_id)
                
                # Show success message if console available
                if console:
                    console.print(f"[green]✓ {success_text}[/green]")
                
                return result
                
            except Exception:
                # Clean up on failure
                provider.complete_operation(operation_id)
                raise
        
        @wraps(func)  
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            # Handle sync calls by wrapping in asyncio.run
            return asyncio.run(async_wrapper(*args, **kwargs))
        
        # Return appropriate wrapper based on function signature
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


def with_db_progress(
    description: str,
    success_text: str = "Operation completed!",
    display_title: str | None = None,
    next_step_message: str | None = None,
    console: Console | None = None,
    session_factory: Callable[[], SessionProvider] | None = None,
    repository_factory: Callable[[Any], RepositoryProvider] | None = None,
    ui_provider: UIProvider | None = None,
) -> Callable[[Callable[..., Awaitable[OperationResult]]], Callable[..., OperationResult]]:
    """Progress decorator for database operations with result display.
    
    Combines progress tracking with database session management
    and result display following Clean Architecture patterns.
    
    Args:
        description: Operation description
        success_text: Success message
        display_title: Optional title for result display
        next_step_message: Optional next step hint
        console: Console for output (injected dependency)
        session_factory: Factory for database sessions (injected dependency)
        repository_factory: Factory for repositories (injected dependency)
        ui_provider: UI provider for result display (injected dependency)
    """
    def decorator(func: Callable[..., Awaitable[OperationResult]]) -> Callable[..., OperationResult]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> OperationResult:
            async def run_with_session_and_progress() -> OperationResult:
                if not session_factory:
                    raise ValueError("session_factory is required for db_progress decorator")
                if not repository_factory:
                    raise ValueError("repository_factory is required for db_progress decorator")
                
                async with session_factory() as session:
                    repositories = repository_factory(session)
                    kwargs['repositories'] = repositories
                    
                    # Create and start progress operation
                    operation = create_operation(description)
                    provider = get_progress_provider()
                    operation_id = provider.start_operation(operation)
                    
                    try:
                        result = await func(*args, **kwargs)
                        provider.complete_operation(operation_id)
                        return result
                    except Exception:
                        provider.complete_operation(operation_id)
                        raise
            
            # Execute with progress
            result = asyncio.run(run_with_session_and_progress())
            
            # Display success and results with injected dependencies
            if console:
                console.print(f"[green]✓ {success_text}[/green]")
            
            if ui_provider:
                ui_provider.display_operation_result(
                    result=result,
                    title=display_title,
                    next_step_message=next_step_message,
                )
            
            return result
        
        return wrapper
    return decorator


def batch_progress_wrapper(
    items: list[Any],
    process_func: Callable,
    *,
    operation_description: str = "Processing items",
    batch_size: int = 50,
    progress_provider: ProgressProvider | None = None,
) -> Callable[[], Awaitable[dict[int, Any]]]:
    """Create a progress-aware batch processing wrapper.
    
    Replaces existing process_in_batches function with unified progress.
    
    Args:
        items: Items to process
        process_func: Async function to process batches
        operation_description: Description for progress display
        batch_size: Size of each batch
        progress_provider: Optional progress provider (injected dependency)
        
    Returns:
        Async function that processes items with progress tracking
    """
    async def process_with_progress() -> dict[int, Any]:
        if not items:
            return {}
        
        # Create progress operation
        operation = create_operation(operation_description, len(items))
        provider = progress_provider or get_progress_provider()
        operation_id = provider.start_operation(operation)
        
        try:
            results = {}
            processed_items = 0
            
            # Process in batches
            for i in range(0, len(items), batch_size):
                batch = items[i:i + batch_size]
                batch_num = (i // batch_size) + 1
                total_batches = (len(items) + batch_size - 1) // batch_size
                
                # Update progress description
                description = f"{operation_description} (batch {batch_num}/{total_batches})"
                provider.set_description(operation_id, description)
                
                # Process batch
                batch_results = await process_func(batch)
                if batch_results:
                    results.update(batch_results)
                
                processed_items += len(batch)
                provider.update_progress(operation_id, processed_items)
            
            provider.complete_operation(operation_id)
            return results
            
        except Exception:
            provider.complete_operation(operation_id)
            raise
    
    return process_with_progress