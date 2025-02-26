"""Configuration management and logging setup for Narada.

Logging Key Functions:
-------------
get_logger(name: str) -> Logger
    Get a context-aware logger for your module
    Args: name - Usually __name__ from the calling module
    Usage: logger = get_logger(__name__)

log_startup_info() -> None
    Log system configuration and API status at startup
    Call once when application initializes

@resilient_operation(operation_name: str)
    Decorator for handling errors in external API calls
    Args: operation_name - Name for logging the operation
    Usage: @resilient_operation("spotify_sync")

Logging Quick Start:
-----------
1. Get a logger for your module:
    ```python
    from narada.config import get_logger

    logger = get_logger(__name__)
    ```

2. Log with structured context:
    ```python
    # Info with context
    logger.info("Starting sync", playlist_id=123)

    # Error with exception
    try:
        result = await api_call()
    except Exception as e:
        logger.exception("API error")
        raise
    ```

3. Handle external API calls:
    ```python
    @resilient_operation("spotify_api")
    async def fetch_playlist(playlist_id: str):
        return await spotify.get_playlist(playlist_id)
    ```

Best Practices:
-------------
1. Always get logger with module name:
   logger = get_logger(__name__)

2. Use structured logging:
   logger.info("Event", key1="value1")

3. Wrap external API calls:
   @resilient_operation()

4. Add context when needed:
   with logger.contextualize(operation="sync"):
       await task()

5. Call log_startup_info() on app init:
   if __name__ == "__main__":
       log_startup_info()
"""

import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv
from loguru import logger

# Load environment variables
load_dotenv()

# Module-level configuration dictionary
_config: Dict[str, Any] = {
    # Database settings
    "DATABASE_URL": os.getenv("DATABASE_URL", "sqlite+aiosqlite:///narada.db"),
    "DATABASE_ECHO": os.getenv("DATABASE_ECHO", "false").lower() == "true",
    "DATABASE_POOL_SIZE": int(os.getenv("DATABASE_POOL_SIZE", "5")),
    "DATABASE_MAX_OVERFLOW": int(os.getenv("DATABASE_MAX_OVERFLOW", "10")),
    "DATABASE_POOL_TIMEOUT": int(os.getenv("DATABASE_POOL_TIMEOUT", "30")),
    "DATABASE_POOL_RECYCLE": int(os.getenv("DATABASE_POOL_RECYCLE", "1800")),
    "DATABASE_CONNECT_RETRIES": int(os.getenv("DATABASE_CONNECT_RETRIES", "3")),
    "DATABASE_RETRY_INTERVAL": int(os.getenv("DATABASE_RETRY_INTERVAL", "5")),
    # Application settings
    "CONSOLE_LOG_LEVEL": os.getenv("CONSOLE_LOG_LEVEL", "INFO"),
    "FILE_LOG_LEVEL": os.getenv("FILE_LOG_LEVEL", "DEBUG"),
    "LOG_FILE": Path(os.getenv("LOG_FILE", "narada.log")),
    "DATA_DIR": Path(os.getenv("DATA_DIR", "data")),
}


# Create data directory if it doesn't exist
_config["DATA_DIR"].mkdir(exist_ok=True)


def get_config(key: str, default=None) -> Any:
    """Get configuration value by key with optional default."""
    return _config.get(key, default)


def setup_loguru_logger(verbose: bool = False) -> None:
    """Configure Loguru logger for the application."""
    # Remove default logger
    logger.remove()

    # Add contextual info to all log records
    logger.configure(extra={"service": "narada"})

    # Console handler - adjust level based on verbose flag
    console_level = "DEBUG" if verbose else _config["CONSOLE_LOG_LEVEL"]
    logger.add(
        sink=sys.stdout,
        level=console_level,
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:"
            "<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
        colorize=True,
        backtrace=verbose,  # Show more detail in verbose mode
        diagnose=verbose,  # Enable diagnostics in verbose mode
    )

    # File handler - detailed format with full debug info
    logger.add(
        sink=str(_config["LOG_FILE"]),  # Convert Path to string
        level=_config["FILE_LOG_LEVEL"],
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
            "{level: <8} | "
            "process:{process}:{thread} | "
            "{name}:{function}:{line} | "
            "({file}:{line}) | "
            "{message}"
            "\n{exception}"  # Add exception info on new line
        ),
        rotation="10 MB",  # Rotate at 10 MB
        retention="1 week",  # Keep logs for 1 week
        compression="zip",
        backtrace=True,  # Always show full traceback
        diagnose=True,  # Show variables in traceback
        enqueue=True,  # Thread-safe logging
        catch=True,  # Catch errors within logger
    )


def get_logger(name: str) -> Any:  # Use Any for Loguru logger type
    """Get a pre-configured logger instance for the given module.

    Args:
        name: Module name (typically __name__)

    Returns:
        Pre-configured Loguru logger instance with module context

    Example:
        ```python
        logger = get_logger(__name__)
        logger.info("Operation complete", operation="sync")
        ```

    Notes:
        - Returns a bound logger with structured context
        - Inherits global Loguru configuration
        - Thread-safe for async operations
    """
    return logger.bind(
        module=name,
        service="narada",
    )


async def log_startup_info() -> None:
    """Log application configuration on startup."""
    separator = "=" * 50

    # Startup banner and config details
    logger.info("")
    logger.info("<blue>{}</blue>", separator)
    logger.info("<yellow>🎵 Narada Music Integration Platform</yellow>")
    logger.info("<blue>{}</blue>", separator)
    logger.info("")
    logger.debug(
        "Configuration:",
        file_level=_config["FILE_LOG_LEVEL"],
        database=_config["DATABASE_URL"],
    )
    logger.info("")


# Add a centralized error handling decorator for service boundaries
def resilient_operation(operation_name=None):
    """Decorator for service boundary operations with standardized error handling.

    Use on external API calls and other boundary operations to centralize
    error handling and avoid repetitive try/except blocks.

    Example:
        @resilient_operation("spotify_playlist_fetch")
        async def get_spotify_playlist(playlist_id):
            # Implementation that can raise exceptions
    """

    def decorator(func):
        op_name = operation_name or func.__name__

        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                logger.exception(f"Error in {op_name}: {str(e)}")
                # Re-raise certain exceptions, swallow others based on type
                raise

        return wrapper

    return decorator


def configure_prefect_logging() -> None:
    """Configure Prefect to use our Loguru setup without changing our existing patterns."""

    # Create a simple handler that passes Prefect logs to Loguru
    class PrefectLoguruHandler(logging.Handler):
        def emit(self, record):
            # Get corresponding Loguru level
            level = logger.level(record.levelname).name

            # Extract message and maintain original format
            msg = self.format(record)

            # Pass to loguru with appropriate module context
            module_name = record.name
            logger.bind(module=module_name).log(level, msg)

    # Configure the Prefect logger
    prefect_logger = logging.getLogger("prefect")
    prefect_logger.handlers = [PrefectLoguruHandler()]
    prefect_logger.propagate = False
