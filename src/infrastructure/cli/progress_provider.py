"""
Rich-based progress provider following 2025 CLI best practices.

Implements intelligent progress display with performance optimizations:
- Single shared Rich Progress instance for better performance
- Smart operation categorization (spinner vs progress bar)
- Batch updates to reduce I/O overhead
- Clean, accessible visual design
"""

from threading import Lock
import time
from typing import Any

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from src.application.utilities.progress import ProgressOperation


class RichProgressProvider:
    """Rich-based progress provider optimized for 2025 CLI standards.
    
    Features:
    - Single shared Progress instance for better performance
    - Intelligent display modes (spinner vs progress bar)
    - Batched updates to reduce terminal I/O
    - Clean formatting without redundant information
    - Thread-safe operation tracking
    """
    
    def __init__(self, console: Console | None = None):
        """Initialize the Rich progress provider.
        
        Args:
            console: Optional Rich Console instance (creates default if None)
        """
        self.console = console or Console()
        self._operations: dict[str, TaskID] = {}
        self._operation_metadata: dict[str, dict[str, Any]] = {}
        self._lock = Lock()
        self._last_update_time: dict[str, float] = {}
        
        # Single shared Progress instance following 2025 best practices
        # Removed redundant TextColumn that was causing "(0/None)" display
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),  # This already shows "N/M" format
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=self.console,
            transient=False,
        )
        self._progress_started = False
    
    def _ensure_progress_started(self) -> None:
        """Ensure Progress is started (lazy initialization)."""
        if not self._progress_started:
            self._progress.start()
            self._progress_started = True
    
    def _should_update_display(self, operation_id: str) -> bool:
        """Rate limit display updates to improve performance.
        
        Updates at most every 500ms per operation to reduce I/O overhead
        while maintaining responsive feel.
        
        Args:
            operation_id: Operation to check
            
        Returns:
            True if display should be updated
        """
        current_time = time.time()
        last_update = self._last_update_time.get(operation_id, 0)
        
        # Allow update if >500ms since last update
        if current_time - last_update > 0.5:
            self._last_update_time[operation_id] = current_time
            return True
        return False
    
    def start_operation(self, operation: ProgressOperation) -> str:
        """Start tracking a new operation with intelligent display mode."""
        with self._lock:
            self._ensure_progress_started()
            
            # Determine display mode based on operation characteristics
            if self.is_long_running_operation(operation):
                # Full progress bar for determinate long operations
                total = operation.total_items
                description = f"[cyan]{operation.description}[/cyan]"
            else:
                # Spinner mode for quick or indeterminate operations
                total = None
                description = f"[dim cyan]{operation.description}[/dim cyan]"
            
            # Create Rich task
            task_id = self._progress.add_task(
                description=description,
                total=total,
                completed=operation.current_items,
            )
            
            # Track operation
            self._operations[operation.operation_id] = task_id
            self._operation_metadata[operation.operation_id] = {
                "start_time": operation.start_time,
                "original_total": operation.total_items,
                "is_long_running": self.is_long_running_operation(operation),
            }
            
            return operation.operation_id
    
    def update_progress(
        self,
        operation_id: str,
        current: int,
        total: int | None = None,
        description: str | None = None,
    ) -> None:
        """Update progress with rate limiting for better performance."""
        if operation_id not in self._operations:
            return
        
        # Rate limit updates to improve performance
        if not self._should_update_display(operation_id):
            return
        
        with self._lock:
            task_id = self._operations[operation_id]
            metadata = self._operation_metadata[operation_id]
            
            # Handle total updates (indeterminate -> determinate transition)
            update_total = None
            if total is not None and total != metadata.get("original_total"):
                update_total = total
                metadata["original_total"] = total
                
                # Update to long-running mode if switching to determinate
                if not metadata["is_long_running"] and total > 100:
                    metadata["is_long_running"] = True
            
            # Handle description updates with proper styling
            update_description = None
            if description:
                is_long_running = metadata["is_long_running"]
                style = "cyan" if is_long_running else "dim cyan"
                update_description = f"[{style}]{description}[/{style}]"
            
            # Apply updates with explicit typing
            if update_description is not None:
                self._progress.update(
                    task_id,
                    completed=current,
                    total=update_total,
                    description=update_description,
                )
            else:
                self._progress.update(
                    task_id,
                    completed=current,
                    total=update_total,
                )
    
    def set_description(self, operation_id: str, description: str) -> None:
        """Update operation description with appropriate styling."""
        if operation_id not in self._operations:
            return
        
        with self._lock:
            task_id = self._operations[operation_id]
            metadata = self._operation_metadata[operation_id]
            
            # Apply styling based on operation type
            is_long_running = metadata["is_long_running"]
            style = "cyan" if is_long_running else "dim cyan"
            
            self._progress.update(
                task_id,
                description=f"[{style}]{description}[/{style}]"
            )
    
    def complete_operation(self, operation_id: str) -> None:
        """Mark operation as complete with success styling."""
        if operation_id not in self._operations:
            return
        
        with self._lock:
            task_id = self._operations[operation_id]
            
            # Get final description from current task
            task = self._progress.tasks[task_id]
            base_description = task.description
            
            # Remove styling markup for base description
            if "[cyan]" in base_description:
                base_description = base_description.replace("[cyan]", "").replace("[/cyan]", "")
            elif "[dim cyan]" in base_description:
                base_description = base_description.replace("[dim cyan]", "").replace("[/dim cyan]", "")
            
            # Update to completed state with success styling
            self._progress.update(
                task_id,
                description=f"[green]✓ {base_description}[/green]",
                completed=task.total or 100,
                total=task.total or 100,
            )
            
            # Clean up tracking
            del self._operations[operation_id]
            del self._operation_metadata[operation_id]
            self._last_update_time.pop(operation_id, None)
            
            # Auto-cleanup: stop progress if no active operations
            if not self._operations and self._progress_started:
                # Small delay to allow user to see completion
                import threading

                def delayed_stop():
                    time.sleep(0.5)
                    if not self._operations:  # Double-check no new operations started
                        self._progress.stop()
                        self._progress_started = False
                
                threading.Thread(target=delayed_stop, daemon=True).start()
    
    def is_long_running_operation(self, operation: ProgressOperation) -> bool:
        """Determine if operation should show detailed progress bar.
        
        Uses intelligent heuristics based on 2025 CLI best practices:
        - Operations with >100 items: Always show progress bar
        - Operations with totals 10-100: Show progress bar  
        - Indeterminate operations: Spinner only
        - Quick operations (<10 items): Spinner only
        
        Args:
            operation: Operation to evaluate
            
        Returns:
            True if should show progress bar, False for spinner only
        """
        # Indeterminate operations get spinner
        if operation.is_indeterminate:
            return False
        
        # Large operations always get progress bar
        if operation.total_items and operation.total_items >= 100:
            return True
        
        # Medium operations get progress bar, small operations get spinner
        return bool(operation.total_items and operation.total_items >= 10)
    
    def stop(self) -> None:
        """Stop the progress display and clean up resources."""
        with self._lock:
            if self._progress_started:
                self._progress.stop()
                self._progress_started = False
            
            # Clear all tracking data
            self._operations.clear()
            self._operation_metadata.clear()
            self._last_update_time.clear()
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit with cleanup."""
        self.stop()