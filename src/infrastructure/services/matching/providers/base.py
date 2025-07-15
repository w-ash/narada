"""Base provider protocol for track matching services.

This module defines the contract that all music service providers must implement
to participate in the track matching system.
"""

from typing import Any, Protocol

from src.domain.matching.types import MatchResultsById


class MatchProvider(Protocol):
    """Contract for music service providers to find track matches.
    
    Providers communicate with external APIs and transform responses into
    domain MatchResult objects.
    """

    async def find_potential_matches(
        self,
        tracks: list[Any],  # Track objects - avoiding import for simplicity
        **additional_options: Any,
    ) -> MatchResultsById:
        """Find matches for tracks in external service.
        
        Args:
            tracks: Internal Track objects to match
            **additional_options: Provider-specific options
            
        Returns:
            Track IDs mapped to MatchResult objects for successful matches only.
            
        Raises:
            Exception: Unrecoverable errors (network failures, auth issues).
            
        Note:
            Handle retries and rate limiting internally. Omit failed matches
            from results rather than raising exceptions.
        """
        ...

    @property
    def service_name(self) -> str:
        """Service identifier (e.g., 'spotify', 'lastfm')."""
        ...