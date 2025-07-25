"""Match tracks use case for cross-service music identification.

This use case encapsulates the business process of matching tracks across
different music services while maintaining clean architecture boundaries.

REFACTORED: Now uses TrackIdentityUseCase for ruthlessly DRY architecture.
"""

from typing import Any

from src.domain.entities import TrackList
from src.domain.matching.types import MatchResultsById
from src.domain.repositories import UnitOfWorkProtocol

from .resolve_track_identity import (
    ResolveTrackIdentityCommand,
    ResolveTrackIdentityUseCase,
)


class MatchTracksUseCase:
    """Orchestrates track matching business process with validation.

    This use case delegates to ResolveTrackIdentityUseCase for all track identity resolution,
    following Clean Architecture with ruthlessly DRY principles and UnitOfWork pattern.
    
    Migrated to UnitOfWork pattern for pure Clean Architecture compliance:
    - No constructor dependencies (pure domain layer)
    - Explicit transaction control through UnitOfWork parameter
    - Simplified testing with single UnitOfWork mock
    """

    async def execute(
        self,
        track_list: TrackList,
        connector: str,
        connector_instance: Any,
        uow: UnitOfWorkProtocol,
        max_age_hours: float | None = None,
        **additional_options: Any,
    ) -> MatchResultsById:
        """Execute track matching with business validation.

        Args:
            track_list: Tracks to match against external service.
            connector: Target service name ("lastfm", "spotify", "musicbrainz").
            connector_instance: Service connector implementation.
            uow: UnitOfWork for transaction management and repository access.
            max_age_hours: Maximum age of cached data in hours. If None, uses cached data regardless of age.
            **additional_options: Options forwarded to infrastructure.

        Returns:
            Track IDs mapped to MatchResult objects.

        Raises:
            ValueError: Business rule violations.
            Exception: Unrecoverable infrastructure errors.
        """
        # Business rule validation
        if not track_list:
            raise ValueError("TrackList cannot be None")

        if not track_list.tracks:
            return {}

        if not connector:
            raise ValueError("Connector name cannot be empty")

        if not connector_instance:
            raise ValueError("Connector instance cannot be None")

        # Delegate to ResolveTrackIdentityUseCase (Clean Architecture + DRY)
        # Share the same UnitOfWork transaction for consistency
        identity_command = ResolveTrackIdentityCommand(
            tracklist=track_list,
            connector=connector,
            connector_instance=connector_instance,
            additional_options=additional_options
        )
        
        identity_use_case = ResolveTrackIdentityUseCase()
        result = await identity_use_case.execute(identity_command, uow)
        
        if result.errors:
            # Log errors but don't raise (backward compatibility)
            from src.config import get_logger
            logger = get_logger(__name__)
            logger.warning(f"Track matching had errors: {result.errors}")
        
        return result.identity_mappings


# Convenience function that matches the original API for backward compatibility
async def match_tracks(
    track_list: TrackList,
    connector: str,
    connector_instance: Any,
    max_age_hours: float | None = None,
    **additional_options: Any,
) -> MatchResultsById:
    """Match tracks to external service (convenience function).

    REFACTORED: Now uses UnitOfWork pattern for Clean Architecture compliance.

    Args:
        track_list: Tracks to match.
        connector: Target service name.
        connector_instance: Service connector implementation.
        max_age_hours: Maximum age of cached data in hours. If None, uses cached data regardless of age.
        **additional_options: Options forwarded to infrastructure.

    Returns:
        Track IDs mapped to MatchResult objects.
    """
    from src.infrastructure.persistence.database.db_connection import get_session
    from src.infrastructure.persistence.repositories.factories import get_unit_of_work
    
    async with get_session() as session:
        uow = get_unit_of_work(session)
        
        # Simple instantiation - no dependencies
        use_case = MatchTracksUseCase()
        
        return await use_case.execute(
            track_list=track_list,
            connector=connector,
            connector_instance=connector_instance,
            uow=uow,
            max_age_hours=max_age_hours,
            **additional_options,
        )
