"""Narada music integration platform."""

from importlib.metadata import version

__version__ = version("narada")
__author__ = "Ash Wright"
__license__ = "MIT"

# Expose key interfaces
from narada.cli import app, main
from narada.config import get_logger, resilient_operation

__all__ = [
    "app",
    "main",
    "get_logger",
    "resilient_operation",
]
