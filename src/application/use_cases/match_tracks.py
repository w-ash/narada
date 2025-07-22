"""Match tracks use case for cross-service music identification.

This use case encapsulates the business process of matching tracks across
different music services while maintaining clean architecture boundaries.
"""

from typing import Any

from src.domain.entities import TrackList
from src.domain.matching.types import MatchResultsById


class MatchTracksUseCase:
    """Orchestrates track matching business process with validation.

    Validates business rules, delegates to infrastructure services, and
    handles errors at the application boundary.

    Uses direct dependency injection for clean architecture compliance.
    """

    def __init__(
        self,
        track_repos: Any,  # TrackRepositories - avoiding circular import
        matcher_service: Any,  # MatcherService - avoiding circular import 
    ) -> None:
        """Initialize with injected dependencies.

        Args:
            track_repos: TrackRepositories instance for data access
            matcher_service: MatcherService instance for track resolution
        """
        self.track_repos = track_repos
        self.matcher_service = matcher_service

    async def execute(
        self,
        track_list: TrackList,
        connector: str,
        connector_instance: Any,
        max_age_hours: float | None = None,
        **additional_options: Any,
    ) -> MatchResultsById:
        """Execute track matching with business validation.

        Args:
            track_list: Tracks to match against external service.
            connector: Target service name ("lastfm", "spotify", "musicbrainz").
            connector_instance: Service connector implementation.
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

        # Use existing matcher service directly - this is the actual implementation
        # that has been working in the system
        return await self.matcher_service.match_tracks(
            track_list=track_list,
            connector=connector,
            connector_instance=connector_instance,
            max_age_hours=max_age_hours,
            **additional_options,
        )


# Convenience function that matches the original API for backward compatibility
async def match_tracks(
    track_list: TrackList,
    connector: str,
    connector_instance: Any,
    track_repos,  # Accept any repository type for backward compatibility
    max_age_hours: float | None = None,
    **additional_options: Any,
) -> MatchResultsById:
    """Match tracks to external service (convenience function).

    Args:
        track_list: Tracks to match.
        connector: Target service name.
        connector_instance: Service connector implementation.
        track_repos: TrackRepositories instance.
        max_age_hours: Maximum age of cached data in hours. If None, uses cached data regardless of age.
        **additional_options: Options forwarded to matcher service.

    Returns:
        Track IDs mapped to MatchResult objects.
    """
    from src.infrastructure.services.matcher_service import MatcherService

    # Use existing infrastructure directly - no provider wrapper needed
    matcher_service = MatcherService(track_repos)

    use_case = MatchTracksUseCase(track_repos, matcher_service)
    return await use_case.execute(
        track_list=track_list,
        connector=connector,
        connector_instance=connector_instance,
        max_age_hours=max_age_hours,
        **additional_options,
    )
