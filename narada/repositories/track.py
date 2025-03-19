"""Track repository implementation for database operations.

This module provides a unified API for track operations by combining
functionality from the core track repository and sync repository.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from narada.repositories.track_core import TrackRepository
from narada.repositories.track_sync import TrackSyncRepository


class UnifiedTrackRepository:
    """Combined repository that provides access to all track operations."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize all repositories with the provided session."""
        self.core = TrackRepository(session)
        self.sync = TrackSyncRepository(session)
        self.session = session
        
    # Re-export core track operations
    async def get_track(self, *args, **kwargs):
        """Get track by any identifier type."""
        return await self.core.get_track(*args, **kwargs)
        
    async def find_track(self, *args, **kwargs):
        """Find track by identifier, returning None if not found."""
        return await self.core.find_track(*args, **kwargs)
        
    async def save_track(self, *args, **kwargs):
        """Save track and mappings efficiently."""
        return await self.core.save_track(*args, **kwargs)
        
    async def get_connector_mappings(self, *args, **kwargs):
        """Get mappings between tracks and external connectors."""
        return await self.core.get_connector_mappings(*args, **kwargs)
        
    async def get_track_metrics(self, *args, **kwargs):
        """Get cached metrics with TTL awareness."""
        return await self.core.get_track_metrics(*args, **kwargs)
        
    async def get_connector_metadata(self, *args, **kwargs):
        """Get metadata from connector tracks."""
        return await self.core.get_connector_metadata(*args, **kwargs)
        
    async def save_track_metrics(self, *args, **kwargs):
        """Save metrics for multiple tracks efficiently."""
        return await self.core.save_track_metrics(*args, **kwargs)
        
    async def get_or_create(self, *args, **kwargs):
        """Find a track by attributes or create it if it doesn't exist."""
        return await self.core.get_or_create(*args, **kwargs)
        
    async def save_mapping_confidence_evidence(self, *args, **kwargs):
        """Save confidence evidence to the track_mapping record."""
        return await self.core.save_mapping_confidence_evidence(*args, **kwargs)
        
    async def get_mapping_confidence_evidence(self, *args, **kwargs):
        """Get confidence evidence from a track_mapping record."""
        return await self.core.get_mapping_confidence_evidence(*args, **kwargs)
    
    # Re-export sync operations
    async def get_track_likes(self, *args, **kwargs):
        """Get likes for a track across services."""
        return await self.sync.get_track_likes(*args, **kwargs)
        
    async def save_track_like(self, *args, **kwargs):
        """Save a track like for a service."""
        return await self.sync.save_track_like(*args, **kwargs)
        
    async def delete_track_like(self, *args, **kwargs):
        """Remove a track like status for a service."""
        return await self.sync.delete_track_like(*args, **kwargs)
        
    async def get_sync_checkpoint(self, *args, **kwargs):
        """Get synchronization checkpoint for incremental operations."""
        return await self.sync.get_sync_checkpoint(*args, **kwargs)
        
    async def save_sync_checkpoint(self, *args, **kwargs):
        """Save or update a sync checkpoint."""
        return await self.sync.save_sync_checkpoint(*args, **kwargs)


# Note: TrackRepository from track_core.py is still available for direct use
# but the UnifiedTrackRepository should be preferred for most operations