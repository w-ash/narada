"""Configuration management for Narada.

Handles environment variables, logging setup, and application settings.
"""

import os
import sys
from enum import StrEnum, auto
from pathlib import Path
from typing import Self  # Python 3.11+ self-type annotation

from dotenv import load_dotenv
from loguru import logger

# Load environment variables
load_dotenv()


class LogLevel(StrEnum):
    """Log levels supported by the application."""

    DEBUG = auto()
    INFO = auto()
    WARNING = auto()
    ERROR = auto()
    CRITICAL = auto()


class Config:
    """Application configuration container."""

    # Singleton pattern using 3.11+ typing
    _instance: Self | None = None

    # API credentials
    SPOTIFY_CLIENT_ID: str = os.getenv("SPOTIFY_CLIENT_ID", "")
    SPOTIFY_CLIENT_SECRET: str = os.getenv("SPOTIFY_CLIENT_SECRET", "")
    LASTFM_API_KEY: str = os.getenv("LASTFM_API_KEY", "")
    LASTFM_API_SECRET: str = os.getenv("LASTFM_API_SECRET", "")
    LASTFM_USERNAME: str = os.getenv("LASTFM_USERNAME", "")

    # Database settings
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///narada.db")

    # Application settings
    LOG_LEVEL: LogLevel = LogLevel(os.getenv("LOG_LEVEL", "INFO"))
    LOG_FILE: Path = Path(os.getenv("LOG_FILE", "narada.log"))
    DATA_DIR: Path = Path(os.getenv("DATA_DIR", "data"))

    def __new__(cls) -> Self:
        """Singleton implementation using Python 3.11+ Self type."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            # Create data directory if it doesn't exist
            cls.DATA_DIR.mkdir(exist_ok=True)
        return cls._instance


# Module-level singleton instance - Python 3.9+ pattern
config = Config()


def setup_logging() -> None:
    """Configure Loguru logger for the application.

    Sets up console and file logging with appropriate formatting.
    """
    # Remove default handler
    logger.remove()

    # Console handler - clean format for normal use
    logger.add(
        sys.stdout,
        level=config.LOG_LEVEL,
        format="<level>{level: <8}</level> | <green>{time:YYYY-MM-DD HH:mm:ss}</green> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
        colorize=True,
    )

    # File handler - more detailed for debugging
    logger.add(
        config.LOG_FILE,
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
        rotation="10 MB",
        retention="1 week",
        compression="zip",
    )

    # Add exception context handler - Python 3.10+ pattern
    logger.add(
        lambda msg: print(msg, file=sys.stderr),
        level="ERROR",
        format="{message}",
        filter=lambda record: record["exception"] is not None,
        backtrace=True,
        diagnose=True,
    )


def log_startup_info() -> None:
    """Log application configuration on startup."""
    logger.info("Starting Narada Music Integration Platform")
    logger.debug(f"Log level: {config.LOG_LEVEL}")
    logger.debug(f"Database URL: {config.DATABASE_URL}")
    logger.debug(f"Data directory: {config.DATA_DIR}")

    if not (spotify_configured := bool(config.SPOTIFY_CLIENT_ID)):
        logger.warning("Spotify API not configured")
    else:
        logger.debug("Spotify API configured")

    if not (lastfm_configured := bool(config.LASTFM_API_KEY)):
        logger.warning("Last.fm API not configured")
    else:
        logger.debug("Last.fm API configured")
