"""Import orchestrator service providing unified interface for all import operations.

This service handles all business logic, validation, progress reporting, and error handling
that was previously scattered across CLI commands. The CLI layer becomes pure parameter
mapping to this orchestrated interface.

Clean Architecture compliant - uses dependency injection for infrastructure concerns.
"""

from pathlib import Path
from typing import Any, Literal, Protocol

from src.domain.entities.operations import OperationResult


# Protocols for dependency injection (Clean Architecture compliance)
class Logger(Protocol):
    """Protocol for logging."""
    
    def info(self, message: str, **kwargs: Any) -> None:
        """Log info message."""
        ...
    
    def debug(self, message: str, **kwargs: Any) -> None:
        """Log debug message."""
        ...
    
    def exception(self, message: str, **kwargs: Any) -> None:
        """Log exception message."""
        ...


class RepositoryProvider(Protocol):
    """Protocol for repository access."""
    # Will be defined based on actual repository interface needs


class ImportServiceProvider(Protocol):
    """Protocol for specific import service implementations."""
    
    async def import_recent_plays_with_resolution(
        self,
        limit: int,
        resolve_tracks: bool = False,
        **kwargs: Any
    ) -> OperationResult:
        """Import recent plays with optional track resolution."""
        ...
    
    async def import_plays_from_file(
        self,
        file_path: Path,
        **kwargs: Any
    ) -> OperationResult:
        """Import plays from file."""
        ...


class ProgressDecorator(Protocol):
    """Protocol for progress decoration."""
    
    def __call__(
        self,
        description: str,
        success_text: str = "Operation completed!",
        display_title: str | None = None,
        next_step_message: str | None = None,
    ) -> Any:
        """Apply progress decoration to function."""
        ...


ServiceType = Literal["lastfm", "spotify"]
ImportMode = Literal["recent", "incremental", "full", "file"]


class ImportOrchestrator:
    """Unified orchestrator for all import operations.
    
    Centralizes business logic, validation, and progress handling that was
    previously duplicated across CLI commands. Provides a clean, consistent
    interface for the CLI layer.
    
    Clean Architecture compliant - uses dependency injection for external concerns.
    """
    
    def __init__(
        self,
        logger: Logger | None = None,
        lastfm_service: ImportServiceProvider | None = None,
        spotify_service: ImportServiceProvider | None = None,
        progress_decorator: ProgressDecorator | None = None,
    ):
        """Initialize with injected dependencies.
        
        Args:
            logger: Logging service
            lastfm_service: Last.fm import service implementation
            spotify_service: Spotify import service implementation
            progress_decorator: Progress decoration for operations
        """
        self.logger = logger
        self.lastfm_service = lastfm_service
        self.spotify_service = spotify_service
        self.progress_decorator = progress_decorator
        self._service_registry: dict[ServiceType, ImportServiceProvider] = {}
        
        if lastfm_service:
            self._service_registry["lastfm"] = lastfm_service
        if spotify_service:
            self._service_registry["spotify"] = spotify_service
    
    def register_service(self, service_type: ServiceType, service: ImportServiceProvider) -> None:
        """Register an import service implementation.
        
        Args:
            service_type: Type of service ("lastfm", "spotify")
            service: Service implementation
        """
        self._service_registry[service_type] = service
    
    async def import_plays(
        self,
        service_type: ServiceType,
        mode: ImportMode = "recent",
        *,
        limit: int = 1000,
        resolve_tracks: bool = False,
        file_path: Path | None = None,
        **kwargs: Any,
    ) -> OperationResult:
        """Universal import method for all services and modes.
        
        Args:
            service_type: Which service to use ("lastfm", "spotify")
            mode: Import mode ("recent", "incremental", "full", "file")
            limit: Number of items to import (for recent/incremental modes)
            resolve_tracks: Whether to resolve tracks to internal IDs
            file_path: Path to import file (for file mode)
            **kwargs: Additional service-specific parameters
            
        Returns:
            OperationResult with import statistics and details
            
        Raises:
            ValueError: If service is not registered or invalid parameters
            FileNotFoundError: If file_path is invalid for file mode
        """
        # Validate service is available
        if service_type not in self._service_registry:
            available = ", ".join(self._service_registry.keys())
            raise ValueError(
                f"Service '{service_type}' not available. "
                f"Available services: {available}"
            )
        
        service = self._service_registry[service_type]
        
        if self.logger:
            self.logger.info(
                f"Starting {service_type} import",
                mode=mode,
                limit=limit,
                resolve_tracks=resolve_tracks,
                **kwargs
            )
        
        # Route to appropriate import method based on mode
        try:
            if mode == "file":
                if not file_path:
                    raise ValueError("file_path is required for file import mode")
                
                if not file_path.exists():
                    raise FileNotFoundError(f"Import file not found: {file_path}")
                
                result = await service.import_plays_from_file(
                    file_path=file_path,
                    **kwargs
                )
            
            elif mode in ("recent", "incremental", "full"):
                # Map mode to limit parameter
                if mode == "full":
                    # Full history - use service-specific maximum
                    import_limit = None  # Let service decide
                elif mode == "incremental":
                    # Incremental - service should use checkpoints
                    import_limit = limit
                else:  # recent
                    import_limit = limit
                
                result = await service.import_recent_plays_with_resolution(
                    limit=import_limit or limit,
                    resolve_tracks=resolve_tracks,
                    mode=mode,
                    **kwargs
                )
            
            else:
                raise ValueError(f"Unknown import mode: {mode}")
            
            if self.logger:
                self.logger.info(
                    f"Completed {service_type} import",
                    mode=mode,
                    plays_processed=result.plays_processed,
                    execution_time=result.execution_time,
                )
            
            return result
            
        except Exception as e:
            if self.logger:
                self.logger.exception(f"Failed {service_type} import: {e}")
            raise


# Convenience functions for specific import types
async def import_lastfm_plays(
    mode: ImportMode = "recent",
    limit: int = 1000,
    resolve_tracks: bool = False,
    repositories: Any = None,
    **kwargs: Any,
) -> OperationResult:
    """Import Last.fm plays with default orchestrator.
    
    Args:
        mode: Import mode
        limit: Number of plays to import
        resolve_tracks: Whether to resolve tracks
        repositories: Repository provider (injected)
        **kwargs: Additional parameters
        
    Returns:
        Import result
    """
    # This would be injected by the infrastructure layer
    orchestrator = ImportOrchestrator()
    
    return await orchestrator.import_plays(
        service_type="lastfm",
        mode=mode,
        limit=limit,
        resolve_tracks=resolve_tracks,
        repositories=repositories,
        **kwargs
    )


async def import_spotify_plays(
    file_path: Path,
    repositories: Any = None,
    **kwargs: Any,
) -> OperationResult:
    """Import Spotify plays from JSON file.
    
    Args:
        file_path: Path to Spotify data export file
        repositories: Repository provider (injected)
        **kwargs: Additional parameters
        
    Returns:
        Import result
    """
    # This would be injected by the infrastructure layer
    orchestrator = ImportOrchestrator()
    
    return await orchestrator.import_plays(
        service_type="spotify",
        mode="file",
        file_path=file_path,
        repositories=repositories,
        **kwargs
    )


# Factory function for creating configured orchestrator
def create_import_orchestrator(
    logger: Logger | None = None,
    lastfm_service: ImportServiceProvider | None = None,
    spotify_service: ImportServiceProvider | None = None,
    progress_decorator: ProgressDecorator | None = None,
) -> ImportOrchestrator:
    """Create configured import orchestrator.
    
    Args:
        logger: Logging service
        lastfm_service: Last.fm service implementation
        spotify_service: Spotify service implementation
        progress_decorator: Progress decorator
        
    Returns:
        Configured orchestrator
    """
    return ImportOrchestrator(
        logger=logger,
        lastfm_service=lastfm_service,
        spotify_service=spotify_service,
        progress_decorator=progress_decorator,
    )