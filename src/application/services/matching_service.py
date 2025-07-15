"""High-level matching orchestration service.

This service provides orchestration for track matching operations,
coordinating between domain matching algorithms and infrastructure connectors.

Clean Architecture compliant - uses dependency injection for external concerns.
"""

from collections.abc import Callable
from typing import Any, Protocol, TypeVar

from src.application.utilities.batching import BatchProcessor
from src.application.utilities.progress import create_operation, get_progress_provider
from src.domain.entities.track import Track, TrackList
from src.domain.matching.algorithms import calculate_confidence
from src.domain.matching.types import ConfidenceEvidence, MatchResult


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


class ConfigProvider(Protocol):
    """Protocol for configuration access."""
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value."""
        ...


class RepositoryProvider(Protocol):
    """Protocol for repository access."""
    # Will be defined based on actual repository interface needs


class ConnectorProvider(Protocol):
    """Protocol for external service connectors."""
    
    async def search_tracks(self, tracks: list[Track], **kwargs: Any) -> list[dict[str, Any]]:
        """Search for tracks in external service."""
        ...
    
    def get_batch_size(self) -> int:
        """Get optimal batch size for this connector."""
        ...


T = TypeVar("T")

# Type aliases for clarity
TracksById = dict[int, Track]
MatchResultsById = dict[int, MatchResult]


class MatchingService:
    """High-level orchestration service for track matching operations.
    
    Coordinates between domain matching algorithms and infrastructure connectors
    to provide unified track matching across multiple music services.
    
    Clean Architecture compliant - uses dependency injection for external concerns.
    """
    
    def __init__(
        self,
        logger: Logger | None = None,
        config: ConfigProvider | None = None,
        batch_processor: BatchProcessor | None = None,
    ):
        """Initialize with injected dependencies.
        
        Args:
            logger: Logging service
            config: Configuration provider
            batch_processor: Batch processing utility
        """
        self.logger = logger
        self.config = config
        self.batch_processor = batch_processor or BatchProcessor()
        self._connectors: dict[str, ConnectorProvider] = {}
    
    def register_connector(self, service_name: str, connector: ConnectorProvider) -> None:
        """Register a service connector.
        
        Args:
            service_name: Name of the service (e.g., "spotify", "lastfm")
            connector: Connector implementation
        """
        self._connectors[service_name] = connector
    
    async def match_tracks(
        self,
        tracks: TrackList,
        service_name: str,
        *,
        confidence_threshold: float = 80.0,
        batch_size: int | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> MatchResultsById:
        """Match tracks against external service.
        
        Args:
            tracks: TrackList to match
            service_name: Name of service to match against
            confidence_threshold: Minimum confidence threshold
            batch_size: Override batch size for processing
            progress_callback: Progress callback function
            
        Returns:
            Dictionary mapping track indices to match results
            
        Raises:
            ValueError: If service connector is not registered
        """
        if service_name not in self._connectors:
            available = ", ".join(self._connectors.keys())
            raise ValueError(
                f"Connector for '{service_name}' not registered. "
                f"Available connectors: {available}"
            )
        
        connector = self._connectors[service_name]
        
        if self.logger:
            self.logger.info(
                f"Starting track matching against {service_name}",
                track_count=len(tracks.tracks),
                confidence_threshold=confidence_threshold,
            )
        
        # Convert TrackList to list for batch processing
        track_list = list(tracks.tracks)
        
        if not track_list:
            if self.logger:
                self.logger.info("No tracks to match")
            return {}
        
        # Create match strategy
        strategy = self.batch_processor.create_match_strategy(
            connector=connector,
            confidence_threshold=confidence_threshold,
            connector_type=service_name,
            batch_size=batch_size,
            processor_func=self._process_match_batch,
        )
        
        # Process with batch processor
        batch_result = await self.batch_processor.process_with_strategy(
            items=track_list,
            strategy=strategy,
            progress_callback=progress_callback,
        )
        
        # Convert batch results to match results
        match_results = {}
        track_index = 0
        
        for batch in batch_result.batch_results:
            for result in batch:
                if result.get("status") == "matched":
                    match_results[track_index] = MatchResult(
                        track=track_list[track_index],
                        success=True,
                        connector_id=result.get("service_data", {}).get("id", ""),
                        confidence=int(result.get("confidence", 0.0)),
                        match_method=result.get("method", "search"),
                        service_data=result.get("service_data", {}),
                        evidence=result.get("evidence", ConfidenceEvidence(
                            base_score=0,
                            title_similarity=0.0,
                            artist_similarity=0.0,
                        )),
                    )
                track_index += 1
        
        if self.logger:
            self.logger.info(
                f"Completed track matching against {service_name}",
                matches_found=len(match_results),
                success_rate=batch_result.success_rate,
            )
        
        return match_results
    
    async def _process_match_batch(
        self,
        tracks: list[Track],
        connector: ConnectorProvider,
    ) -> list[dict[str, Any]]:
        """Process a batch of tracks for matching.
        
        Args:
            tracks: Batch of tracks to match
            connector: Service connector
            
        Returns:
            List of match results
        """
        try:
            # Search tracks in external service
            search_results = await connector.search_tracks(tracks)
            
            results = []
            for i, track in enumerate(tracks):
                if i < len(search_results):
                    service_data = search_results[i]
                    
                    # Calculate confidence using domain algorithm
                    confidence, evidence = calculate_confidence(
                        internal_track_data={
                            "title": track.title,
                            "artists": [a.name for a in track.artists],
                        },
                        service_track_data=service_data,
                        match_method="search",
                    )
                    
                    results.append({
                        "status": "matched",
                        "confidence": confidence,
                        "service_data": service_data,
                        "evidence": evidence,
                        "method": "search",
                    })
                else:
                    results.append({
                        "status": "no_match",
                        "confidence": 0.0,
                    })
            
            return results
            
        except Exception as e:
            if self.logger:
                self.logger.exception(f"Error in match batch processing: {e}")
            # Return error results for all tracks in batch
            return [
                {"status": "error", "error": str(e)}
                for _ in tracks
            ]
    
    async def process_in_batches(
        self,
        items: list[Any],
        process_func: Callable,
        *,
        batch_size: int | None = None,
        operation_name: str = "batch_process",
        connector_name: str | None = None,
    ) -> dict[int, Any]:
        """Legacy wrapper for unified progress system compatibility.
        
        Maintains API compatibility while using the new unified batch processor.
        
        Args:
            items: Items to process
            process_func: Processing function
            batch_size: Override batch size
            operation_name: Operation description
            connector_name: Name of connector (for batch size config)
            
        Returns:
            Dictionary of results by index
        """
        if not items:
            if self.logger:
                self.logger.info(f"No items to process for {operation_name}")
            return {}
        
        # Get appropriate batch size based on connector config
        if not batch_size:
            if connector_name and self.config:
                config_key = f"{connector_name.upper()}_API_BATCH_SIZE"
                batch_size = self.config.get(
                    config_key, 
                    self.config.get("DEFAULT_API_BATCH_SIZE", 50)
                )
            elif self.config:
                batch_size = self.config.get("DEFAULT_API_BATCH_SIZE", 50)
            else:
                batch_size = 50
        
        # Ensure batch_size is an int for type checking
        if not isinstance(batch_size, int):
            raise ValueError(f"batch_size must be int, got {type(batch_size)}")
        
        # Create operation and track progress
        operation = create_operation(operation_name, len(items))
        provider = get_progress_provider()
        operation_id = provider.start_operation(operation)
        
        try:
            results = {}
            processed_items = 0
            
            # Process in batches
            for i in range(0, len(items), batch_size):
                batch = items[i:i + batch_size]
                batch_num = (i // batch_size) + 1
                total_batches = (len(items) + batch_size - 1) // batch_size
                
                # Update progress
                description = f"{operation_name} (batch {batch_num}/{total_batches})"
                provider.set_description(operation_id, description)
                
                # Process batch
                batch_results = await process_func(batch)
                if batch_results:
                    # Convert list results to indexed results
                    for j, result in enumerate(batch_results):
                        results[i + j] = result
                
                processed_items += len(batch)
                provider.update_progress(operation_id, processed_items)
            
            provider.complete_operation(operation_id)
            return results
            
        except Exception:
            provider.complete_operation(operation_id)
            raise


# Factory function for creating configured matching service
def create_matching_service(
    logger: Logger | None = None,
    config: ConfigProvider | None = None,
    batch_processor: BatchProcessor | None = None,
) -> MatchingService:
    """Create configured matching service.
    
    Args:
        logger: Logging service
        config: Configuration provider
        batch_processor: Batch processing utility
        
    Returns:
        Configured matching service
    """
    return MatchingService(
        logger=logger,
        config=config,
        batch_processor=batch_processor,
    )