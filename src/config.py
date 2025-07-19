"""Configuration management and logging setup for Narada.

This module provides centralized configuration management and structured logging
setup for the Narada music integration platform.

Key Components:
--------------
- Configuration management with environment variable support
- Structured logging with Loguru
- Error handling decorators for external API calls
- Startup information logging

Public API:
----------
get_config(key: str, default=None) -> Any
    Get configuration value by key with optional default

get_logger(name: str) -> Logger
    Get a context-aware logger for your module
    Args: name - Usually __name__ from the calling module
    Usage: logger = get_logger(__name__)

setup_loguru_logger(verbose: bool = False) -> None
    Configure Loguru logger for the application

log_startup_info() -> None
    Log system configuration and API status at startup
    Call once when application initializes

@resilient_operation(operation_name: str)
    Decorator for handling errors in external API calls
    Args: operation_name - Name for logging the operation
    Usage: @resilient_operation("spotify_sync")

configure_prefect_logging() -> None
    Configure Prefect to use our Loguru setup

Quick Start:
-----------
1. Get a logger for your module:
    ```python
    from src.config import get_logger
    logger = get_logger(__name__)
    ```

2. Log with structured context:
    ```python
    logger.info("Starting sync", playlist_id=123)
    ```

3. Handle external API calls:
    ```python
    @resilient_operation("spotify_api")
    async def fetch_playlist(playlist_id: str):
        return await spotify.get_playlist(playlist_id)
    ```

4. Get configuration values:
    ```python
    from src.config import get_config
    batch_size = get_config("LASTFM_API_BATCH_SIZE", 50)
    ```
"""

# =============================================================================
# IMPORTS
# =============================================================================

import logging
import os
from pathlib import Path
import sys
from typing import Any

from dotenv import load_dotenv
from loguru import logger

# =============================================================================
# ENVIRONMENT SETUP
# =============================================================================

# Load environment variables
load_dotenv()

# =============================================================================
# CONFIGURATION CONSTANTS
# =============================================================================

# Default values for common settings
DEFAULT_BATCH_SIZE = 50
DEFAULT_CONCURRENCY = 5
DEFAULT_RETRY_COUNT = 3
DEFAULT_RETRY_BASE_DELAY = 1.0
DEFAULT_RETRY_MAX_DELAY = 30.0
DEFAULT_REQUEST_DELAY = 0.2

# =============================================================================
# CONFIGURATION DICTIONARY
# =============================================================================

_config: dict[str, Any] = {
    # -------------------------------------------------------------------------
    # Database Configuration
    # -------------------------------------------------------------------------
    "DATABASE_URL": os.getenv("DATABASE_URL", "sqlite+aiosqlite:///narada.db"),
    "DATABASE_ECHO": os.getenv("DATABASE_ECHO", "false").lower() == "true",
    "DATABASE_POOL_SIZE": int(os.getenv("DATABASE_POOL_SIZE", "5")),
    "DATABASE_MAX_OVERFLOW": int(os.getenv("DATABASE_MAX_OVERFLOW", "10")),
    "DATABASE_POOL_TIMEOUT": int(os.getenv("DATABASE_POOL_TIMEOUT", "30")),
    "DATABASE_POOL_RECYCLE": int(os.getenv("DATABASE_POOL_RECYCLE", "1800")),
    "DATABASE_CONNECT_RETRIES": int(os.getenv("DATABASE_CONNECT_RETRIES", "3")),
    "DATABASE_RETRY_INTERVAL": int(os.getenv("DATABASE_RETRY_INTERVAL", "5")),
    # -------------------------------------------------------------------------
    # Application Configuration
    # -------------------------------------------------------------------------
    "CONSOLE_LOG_LEVEL": os.getenv("CONSOLE_LOG_LEVEL", "INFO"),
    "FILE_LOG_LEVEL": os.getenv("FILE_LOG_LEVEL", "DEBUG"),
    "LOG_FILE": Path(os.getenv("LOG_FILE", "narada.log")),
    "DATA_DIR": Path(os.getenv("DATA_DIR", "data")),
    "LOG_REAL_TIME_DEBUG": os.getenv("LOG_REAL_TIME_DEBUG", "True").lower() == "true",
    # -------------------------------------------------------------------------
    # Batch Processing Configuration
    # -------------------------------------------------------------------------
    "BATCH_PROGRESS_LOG_FREQUENCY": int(
        os.getenv("BATCH_PROGRESS_LOG_FREQUENCY", "10")
    ),
    "TRACK_BATCH_RETRY_COUNT": int(os.getenv("TRACK_BATCH_RETRY_COUNT", "3")),
    "TRACK_BATCH_RETRY_DELAY": int(os.getenv("TRACK_BATCH_RETRY_DELAY", "5")),
    # -------------------------------------------------------------------------
    # Global API Defaults
    # -------------------------------------------------------------------------
    "DEFAULT_API_BATCH_SIZE": int(
        os.getenv("DEFAULT_API_BATCH_SIZE", str(DEFAULT_BATCH_SIZE))
    ),
    "DEFAULT_API_CONCURRENCY": int(
        os.getenv("DEFAULT_API_CONCURRENCY", str(DEFAULT_CONCURRENCY))
    ),
    "DEFAULT_API_RETRY_COUNT": int(
        os.getenv("DEFAULT_API_RETRY_COUNT", str(DEFAULT_RETRY_COUNT))
    ),
    "DEFAULT_API_RETRY_BASE_DELAY": float(
        os.getenv("DEFAULT_API_RETRY_BASE_DELAY", str(DEFAULT_RETRY_BASE_DELAY))
    ),
    "DEFAULT_API_RETRY_MAX_DELAY": float(
        os.getenv("DEFAULT_API_RETRY_MAX_DELAY", str(DEFAULT_RETRY_MAX_DELAY))
    ),
    "DEFAULT_API_REQUEST_DELAY": float(
        os.getenv("DEFAULT_API_REQUEST_DELAY", str(DEFAULT_REQUEST_DELAY))
    ),
    # -------------------------------------------------------------------------
    # LastFM API Configuration (optimized for 5 req/sec rate limit)
    # -------------------------------------------------------------------------
    "LASTFM_API_BATCH_SIZE": int(
        os.getenv("LASTFM_API_BATCH_SIZE", str(DEFAULT_BATCH_SIZE))
    ),
    "LASTFM_API_CONCURRENCY": int(
        os.getenv("LASTFM_API_CONCURRENCY", "50")
    ),  # Higher for LastFM
    "LASTFM_API_RETRY_COUNT": int(os.getenv("LASTFM_API_RETRY_COUNT", "2")),
    "LASTFM_API_RETRY_BASE_DELAY": float(
        os.getenv("LASTFM_API_RETRY_BASE_DELAY", "0.4")
    ),
    "LASTFM_API_RETRY_MAX_DELAY": float(os.getenv("LASTFM_API_RETRY_MAX_DELAY", "5.0")),
    "LASTFM_API_REQUEST_DELAY": float(os.getenv("LASTFM_API_REQUEST_DELAY", "0.15")),
    "LASTFM_ENRICHER_BATCH_SIZE": int(
        os.getenv("LASTFM_ENRICHER_BATCH_SIZE", str(DEFAULT_BATCH_SIZE))
    ),
    "LASTFM_ENRICHER_CONCURRENCY": int(
        os.getenv("LASTFM_ENRICHER_CONCURRENCY", str(DEFAULT_CONCURRENCY))
    ),
    # -------------------------------------------------------------------------
    # Spotify API Configuration
    # -------------------------------------------------------------------------
    "SPOTIFY_API_BATCH_SIZE": int(
        os.getenv("SPOTIFY_API_BATCH_SIZE", str(DEFAULT_BATCH_SIZE))
    ),
    "SPOTIFY_API_CONCURRENCY": int(
        os.getenv("SPOTIFY_API_CONCURRENCY", str(DEFAULT_CONCURRENCY))
    ),
    "SPOTIFY_API_RETRY_COUNT": int(
        os.getenv("SPOTIFY_API_RETRY_COUNT", str(DEFAULT_RETRY_COUNT))
    ),
    "SPOTIFY_API_RETRY_BASE_DELAY": float(
        os.getenv("SPOTIFY_API_RETRY_BASE_DELAY", "0.5")
    ),
    "SPOTIFY_API_RETRY_MAX_DELAY": float(
        os.getenv("SPOTIFY_API_RETRY_MAX_DELAY", str(DEFAULT_RETRY_MAX_DELAY))
    ),
    "SPOTIFY_API_REQUEST_DELAY": float(os.getenv("SPOTIFY_API_REQUEST_DELAY", "0.1")),
    # -------------------------------------------------------------------------
    # MusicBrainz API Configuration
    # -------------------------------------------------------------------------
    "MUSICBRAINZ_API_BATCH_SIZE": int(
        os.getenv("MUSICBRAINZ_API_BATCH_SIZE", str(DEFAULT_BATCH_SIZE))
    ),
    "MUSICBRAINZ_API_CONCURRENCY": int(
        os.getenv("MUSICBRAINZ_API_CONCURRENCY", str(DEFAULT_CONCURRENCY))
    ),
    "MUSICBRAINZ_API_RETRY_COUNT": int(
        os.getenv("MUSICBRAINZ_API_RETRY_COUNT", str(DEFAULT_RETRY_COUNT))
    ),
    "MUSICBRAINZ_API_RETRY_BASE_DELAY": float(
        os.getenv("MUSICBRAINZ_API_RETRY_BASE_DELAY", str(DEFAULT_RETRY_BASE_DELAY))
    ),
    "MUSICBRAINZ_API_RETRY_MAX_DELAY": float(
        os.getenv("MUSICBRAINZ_API_RETRY_MAX_DELAY", str(DEFAULT_RETRY_MAX_DELAY))
    ),
    "MUSICBRAINZ_API_REQUEST_DELAY": float(
        os.getenv("MUSICBRAINZ_API_REQUEST_DELAY", str(DEFAULT_REQUEST_DELAY))
    ),
    # -------------------------------------------------------------------------
    # Data Freshness Configuration (in hours)
    # -------------------------------------------------------------------------
    "ENRICHER_DATA_FRESHNESS_LASTFM": float(
        os.getenv("ENRICHER_DATA_FRESHNESS_LASTFM", "1.0")
    ),  # 1 hour
    "ENRICHER_DATA_FRESHNESS_SPOTIFY": float(
        os.getenv("ENRICHER_DATA_FRESHNESS_SPOTIFY", "24.0")
    ),  # 24 hours
    "ENRICHER_DATA_FRESHNESS_MUSICBRAINZ": float(
        os.getenv("ENRICHER_DATA_FRESHNESS_MUSICBRAINZ", "168.0")
    ),  # 1 week
}


# =============================================================================
# INITIALIZATION
# =============================================================================

# Create data directory if it doesn't exist
_config["DATA_DIR"].mkdir(exist_ok=True)

# =============================================================================
# CONFIGURATION ACCESS FUNCTIONS
# =============================================================================


def get_config(key: str, default=None) -> Any:
    """Get configuration value by key with optional default.

    Args:
        key: Configuration key to retrieve
        default: Default value if key not found

    Returns:
        Configuration value or default

    Example:
        >>> batch_size = get_config("LASTFM_API_BATCH_SIZE", 50)
    """
    return _config.get(key, default)


# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================


def setup_loguru_logger(verbose: bool = False) -> None:
    """Configure Loguru logger for the application.

    Args:
        verbose: Enable verbose logging with debug level and detailed tracebacks

    Note:
        - Removes default logger and sets up console and file handlers
        - Console format is colorized and simplified
        - File format includes full structured information
        - Log rotation and retention are automatically managed
    """
    # -------------------------------------------------------------------------
    # Setup
    # -------------------------------------------------------------------------
    # Remove default logger
    logger.remove()

    # Create log directory structure
    log_file_path = Path(_config["LOG_FILE"])
    log_dir = log_file_path.parent
    log_dir.mkdir(parents=True, exist_ok=True)

    # Add contextual info to all log records
    logger.configure(extra={"service": "narada", "module": "root"})

    # -------------------------------------------------------------------------
    # Console Handler
    # -------------------------------------------------------------------------
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

    # -------------------------------------------------------------------------
    # File Handler
    # -------------------------------------------------------------------------
    # File handler - detailed format with full debug info
    # Use real-time logging for performance debugging if enabled
    enqueue_logs = not _config["LOG_REAL_TIME_DEBUG"]
    logger.add(
        sink=str(_config["LOG_FILE"]),  # Convert Path to string
        level=_config["FILE_LOG_LEVEL"],
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {process}:{thread} | {extra[service]} | {extra[module]} | {name}:{function}:{line} | {message}",
        rotation="10 MB",  # Rotate at 10 MB
        retention="1 week",  # Keep logs for 1 week
        compression="zip",
        backtrace=True,  # Always show full traceback
        diagnose=True,  # Show variables in traceback
        enqueue=enqueue_logs,  # Disable buffering for real-time debugging
        catch=True,  # Catch errors within logger
        serialize=True,  # Enable JSON structured logging
    )


# =============================================================================
# LOGGER FACTORY
# =============================================================================


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


# =============================================================================
# STARTUP LOGGING
# =============================================================================


async def log_startup_info() -> None:  # noqa: RUF029
    """Log application configuration on startup.

    Displays a startup banner and logs all configuration values at debug level.
    Should be called once during application initialization.

    Example:
        >>> await log_startup_info()
    """
    local_logger = get_logger(__name__)  # Get a properly bound logger
    separator = "=" * 50

    # Startup banner and config details
    local_logger.info("")
    local_logger.info("{}", separator, markup=True)
    local_logger.info("🎵 Narada Music Integration Platform", markup=True)
    local_logger.info("{}", separator, markup=True)
    local_logger.info("")

    # Log configuration details in a more readable format
    local_logger.debug("Configuration:")
    for key, value in _config.items():
        if isinstance(value, Path):
            value = str(value)
        local_logger.debug("  {}: {}", key, value)
    local_logger.info("")


# =============================================================================
# ERROR HANDLING DECORATORS
# =============================================================================


def resilient_operation(operation_name=None):
    """Decorator for service boundary operations with standardized error handling.

    Use on external API calls and other boundary operations to centralize
    error handling and avoid repetitive try/except blocks.

    Args:
        operation_name: Optional name for the operation (defaults to function name)

    Returns:
        Decorated function with error handling

    Example:
        >>> @resilient_operation("spotify_playlist_fetch")
        >>> async def get_spotify_playlist(playlist_id):
        >>>     # Implementation that can raise exceptions
        >>>     return await spotify.get_playlist(playlist_id)
    """

    def decorator(func):
        op_name = operation_name or func.__name__

        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                logger.exception(f"Error in {op_name}: {e!s}")
                # Re-raise certain exceptions, swallow others based on type
                raise

        return wrapper

    return decorator


# =============================================================================
# THIRD-PARTY LOGGING INTEGRATION
# =============================================================================


def configure_prefect_logging() -> None:
    """Configure Prefect to use our Loguru setup without changing our existing patterns.

    Sets up a custom handler that forwards Prefect logs to Loguru while
    maintaining the existing logging configuration and patterns.

    Note:
        - Creates a bridge between Python's logging and Loguru
        - Preserves module context from original log records
        - Disables propagation to prevent duplicate logs
    """

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
