"""Match tracks use case for cross-service music identification.

This use case encapsulates the business process of matching tracks across
different music services while maintaining clean architecture boundaries.
"""

from typing import Any

from src.domain.entities import TrackList
from src.domain.matching.types import MatchResultsById
from src.infrastructure.persistence.repositories.track import TrackRepositories
from src.infrastructure.services.matcher_service import MatcherService


class MatchTracksUseCase:
    """Orchestrates track matching business process with validation.

    Validates business rules, delegates to infrastructure services, and
    handles errors at the application boundary.
    """

    def __init__(self, track_repos: TrackRepositories) -> None:
        """Initialize with repository dependencies.

        Args:
            track_repos: Repository container for database operations.
        """
        self.track_repos = track_repos
        self.matcher_service = MatcherService(track_repos)

    async def execute(
        self,
        track_list: TrackList,
        connector: str,
        connector_instance: Any,
        **additional_options: Any,
    ) -> MatchResultsById:
        """Execute track matching with business validation.

        Args:
            track_list: Tracks to match against external service.
            connector: Target service name ("lastfm", "spotify", "musicbrainz").
            connector_instance: Service connector implementation.
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

        # Validate connector is supported
        from src.infrastructure.services.matching.providers import (
            get_available_providers,
        )

        available_providers = get_available_providers()
        if connector not in available_providers:
            available = ", ".join(available_providers)
            raise ValueError(
                f"Unsupported connector: {connector}. Available: {available}"
            )

        # Delegate to infrastructure service for execution
        return await self.matcher_service.match_tracks(
            track_list=track_list,
            connector=connector,
            connector_instance=connector_instance,
            **additional_options,
        )


# Convenience function that matches the original API for backward compatibility
async def match_tracks(
    track_list: TrackList,
    connector: str,
    connector_instance: Any,
    track_repos: TrackRepositories,
    **additional_options: Any,
) -> MatchResultsById:
    """Match tracks to external service (legacy API compatibility).

    Args:
        track_list: Tracks to match.
        connector: Target service name.
        connector_instance: Service connector implementation.
        track_repos: Repository container.
        **additional_options: Options forwarded to providers.

    Returns:
        Track IDs mapped to MatchResult objects.
    """
    use_case = MatchTracksUseCase(track_repos)
    return await use_case.execute(
        track_list=track_list,
        connector=connector,
        connector_instance=connector_instance,
        **additional_options,
    )
