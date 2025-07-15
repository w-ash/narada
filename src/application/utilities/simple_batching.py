"""Simple batch processing utilities for matching operations.

This module provides lightweight batch processing functions that integrate
with the existing progress system, extracted from the original matcher.py.
"""

from collections.abc import Callable
from typing import Any

from src.application.utilities.progress_integration import batch_progress_wrapper
from src.infrastructure.config import get_config, get_logger

logger = get_logger(__name__)


async def process_in_batches(
    items: list[Any],
    process_func: Callable,
    *,
    batch_size: int | None = None,
    operation_name: str = "batch_process",
    connector: str | None = None,
) -> dict[int, Any]:
    """Legacy wrapper for unified progress system compatibility.

    Maintains API compatibility while using the new unified progress system.
    The progress_callback parameter is now bridged to the unified system.
    
    Args:
        items: List of items to process
        process_func: Function to process each batch
        batch_size: Optional batch size override
        operation_name: Name for progress reporting
        connector: Connector name for batch size configuration
        
    Returns:
        Dictionary mapping item IDs to results
    """
    if not items:
        logger.info(f"No items to process for {operation_name}")
        return {}

    # Get appropriate batch size based on connector config
    if connector and not batch_size:
        config_key = f"{connector.upper()}_API_BATCH_SIZE"
        batch_size = get_config(config_key, get_config("DEFAULT_API_BATCH_SIZE", 50))
    elif not batch_size:
        batch_size = get_config("DEFAULT_API_BATCH_SIZE", 50)

    # Use unified progress system
    process_with_progress = batch_progress_wrapper(
        items=items,
        process_func=process_func,
        operation_description=operation_name,
        batch_size=batch_size or 50,
    )

    return await process_with_progress()