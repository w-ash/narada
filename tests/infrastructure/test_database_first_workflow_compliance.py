"""Tests for Database-First Workflow Architecture Compliance.

Validates the critical architectural constraint from ARCHITECTURE.md:
"All workflow operations work exclusively on database tracks (tracks table), 
never directly on external connector data."

This means tracks entering workflow operations MUST have database IDs.
"""

from unittest.mock import AsyncMock, Mock

import pytest

from src.domain.entities import Artist, Track, TrackList
from src.infrastructure.services.connector_metadata_manager import (
    ConnectorMetadataManager,
)
from src.infrastructure.services.track_identity_resolver import TrackIdentityResolver


class TestDatabaseFirstWorkflowCompliance:
    """Test database-first workflow requirements are enforced."""

    @pytest.mark.asyncio
    async def test_track_identity_resolver_requires_database_ids(self):
        """Test TrackIdentityResolver enforces database ID requirement."""
        # Setup: Mock repositories
        mock_repos = Mock()
        mock_repos.connector = AsyncMock()
        resolver = TrackIdentityResolver(mock_repos)
        
        # Setup: TracksLists with and without database IDs
        tracks_without_ids = TrackList(tracks=[
            Track(title="No ID Track 1", artists=[Artist(name="Artist 1")]),
            Track(title="No ID Track 2", artists=[Artist(name="Artist 2")])
        ])
        
        TrackList(tracks=[
            Track(id=1, title="ID Track 1", artists=[Artist(name="Artist 1")]),
            Track(id=2, title="ID Track 2", artists=[Artist(name="Artist 2")])
        ])
        
        mixed_tracks = TrackList(tracks=[
            Track(id=1, title="Has ID", artists=[Artist(name="Artist 1")]),
            Track(title="No ID", artists=[Artist(name="Artist 2")])  # No ID
        ])
        
        mock_connector = Mock()
        
        # Test 1: Tracks without IDs should return empty result
        result = await resolver.resolve_track_identities(
            tracks_without_ids, "lastfm", mock_connector
        )
        assert result == {}, "Tracks without database IDs should be rejected"
        
        # Test 2: Mixed tracks should only process tracks with IDs
        mock_repos.connector.get_connector_mappings.return_value = {}
        
        # Mock the provider to avoid external calls
        from unittest.mock import patch
        with patch('src.infrastructure.services.track_identity_resolver.create_provider') as mock_create_provider:
            mock_provider = Mock()
            mock_provider.find_potential_matches = AsyncMock(return_value={})
            mock_create_provider.return_value = mock_provider
            
            result = await resolver.resolve_track_identities(
                mixed_tracks, "lastfm", mock_connector
            )
            
            # Verify: Only tracks with IDs were processed
            mock_provider.find_potential_matches.assert_called_once()
            called_tracks = mock_provider.find_potential_matches.call_args[0][0]
            assert len(called_tracks) == 1, "Only tracks with database IDs should be processed"
            assert called_tracks[0].id == 1, "Only the track with ID should be processed"
        
        # Verify: get_connector_mappings was called with only track ID 1
        mock_repos.connector.get_connector_mappings.assert_called_once_with([1], "lastfm")

    @pytest.mark.asyncio
    async def test_connector_metadata_manager_expects_track_ids(self):
        """Test ConnectorMetadataManager expects tracks with database IDs."""
        # Setup: Mock repositories  
        mock_repos = Mock()
        mock_repos.connector = AsyncMock()
        manager = ConnectorMetadataManager(mock_repos)
        
        # Setup: Identity mappings (tracks already have IDs)
        from src.domain.matching.types import MatchResult
        identity_mappings = {
            1: MatchResult(
                track=Track(id=1, title="Track 1", artists=[Artist(name="Artist 1")]),
                success=True,
                connector_id="connector_id_1",
                confidence=100,
                match_method="existing",
                service_data={},
                evidence={}
            )
        }
        
        mock_connector = Mock()
        mock_connector.batch_get_track_info = AsyncMock(return_value={})
        mock_repos.connector.get_connector_mappings.return_value = {}
        
        # Execute: Should work with track IDs
        fresh_metadata, failed_track_ids = await manager.fetch_fresh_metadata(
            identity_mappings, "lastfm", mock_connector, [1]
        )
        
        # Verify: Operation succeeded (empty result due to no mappings, but no error)
        assert isinstance(fresh_metadata, dict)
        assert isinstance(failed_track_ids, set)
        
        # Verify: Repository was called with valid track IDs
        mock_repos.connector.get_connector_mappings.assert_called_once_with([1], "lastfm")

    @pytest.mark.asyncio 
    async def test_workflow_tracks_have_required_database_ids(self, persisted_tracks):
        """Test that workflow-ready tracks have required database IDs."""
        # Verify: All workflow tracks must have database IDs
        for track in persisted_tracks:
            assert track.id is not None, f"Workflow track {track.title} missing database ID"
            assert isinstance(track.id, int), f"Database ID must be integer, got {type(track.id)}"
            assert track.id > 0, f"Database ID must be positive, got {track.id}"

    def test_domain_track_architecture_compliance(self, persisted_track):
        """Test Track entity architecture compliance for workflow operations."""
        # Verify: Track entity structure supports workflow operations
        assert hasattr(persisted_track, 'id'), "Track must have id field"
        assert hasattr(persisted_track, 'connector_track_ids'), "Track must have connector mappings"
        assert hasattr(persisted_track, 'connector_metadata'), "Track must have connector metadata"
        
        # Verify: Required database ID for workflow compliance
        assert persisted_track.id is not None, "Workflow track must have database ID"
        assert isinstance(persisted_track.id, int), "Database ID must be integer"
        
        # Verify: Connector mappings are properly structured
        assert isinstance(persisted_track.connector_track_ids, dict), "Connector IDs must be dict"
        assert isinstance(persisted_track.connector_metadata, dict), "Connector metadata must be dict"

    def test_infrastructure_fixture_architecture_compliance(self, persisted_db_track):
        """Test DBTrack model architecture compliance."""
        # Verify: DBTrack has required fields for repository operations
        assert hasattr(persisted_db_track, 'id'), "DBTrack must have id field"
        assert hasattr(persisted_db_track, 'title'), "DBTrack must have title field"
        assert hasattr(persisted_db_track, 'artists'), "DBTrack must have artists field"
        
        # Verify: DBTrack has proper relationships loaded
        assert hasattr(persisted_db_track, 'mappings'), "DBTrack must have mappings relationship"
        assert hasattr(persisted_db_track, 'likes'), "DBTrack must have likes relationship"
        assert hasattr(persisted_db_track, 'metrics'), "DBTrack must have metrics relationship"
        
        # Verify: Relationships are initialized (not lazy-loaded)
        assert isinstance(persisted_db_track.mappings, list), "Mappings must be eagerly loaded"
        assert isinstance(persisted_db_track.likes, list), "Likes must be eagerly loaded"
        
        # Verify: Persisted track has database ID
        assert persisted_db_track.id is not None, "Persisted DBTrack must have database ID"

    def test_external_service_model_compliance(self, lastfm_track_info):
        """Test external service model architecture compliance.""" 
        # Verify: External service models are properly structured
        assert hasattr(lastfm_track_info, 'lastfm_title'), "LastFM model must have service-specific fields"
        assert hasattr(lastfm_track_info, 'lastfm_user_playcount'), "LastFM model must have playcount"
        
        # Verify: External models can be converted to metadata dicts
        from src.infrastructure.services.connector_metadata_manager import (
            ConnectorMetadataManager,
        )
        manager = ConnectorMetadataManager(Mock())
        
        # Test the conversion method works with attrs classes
        track_info_results = {1: lastfm_track_info}
        metadata_dict = manager._convert_track_info_results(track_info_results)
        
        assert isinstance(metadata_dict, dict), "Conversion must produce dict"
        assert 1 in metadata_dict, "Track ID must be preserved in conversion"
        track_metadata = metadata_dict[1]
        assert "lastfm_title" in track_metadata, "Service fields must be preserved"
        assert "lastfm_user_playcount" in track_metadata, "Playcount must be preserved"

    @pytest.mark.asyncio
    async def test_repository_conversion_architecture_compliance(self, persisted_db_track):
        """Test repository conversion follows Clean Architecture."""
        from src.infrastructure.persistence.repositories.track.mapper import TrackMapper
        
        # Execute: Convert database model to domain entity (using persisted track with ID)
        domain_track = await TrackMapper.to_domain(persisted_db_track)
        
        # Verify: Repository returns domain entities, not database models
        from src.domain.entities import Track
        from src.infrastructure.persistence.database.db_models import DBTrack
        
        assert isinstance(domain_track, Track), "Repository must return domain entities"
        assert not isinstance(domain_track, DBTrack), "Repository must not leak database models"
        
        # Verify: Domain entity has database ID for workflow compliance
        assert domain_track.id is not None, "Repository tracks must have database IDs"
        assert isinstance(domain_track.id, int), "Database ID must be integer"
        
        # Verify: Domain entity preserves connector information
        assert len(domain_track.connector_track_ids) > 0, "Connector mappings must be preserved"
        assert "db" in domain_track.connector_track_ids, "Database ID must be in connector mappings"

    def test_architecture_layer_entity_separation(self, persisted_track, persisted_db_track, lastfm_track_info):
        """Test that different architectural layers use appropriate entity types."""
        # Verify: Domain/Application layer uses Track entities
        from src.domain.entities import Track
        assert isinstance(persisted_track, Track), "Domain layer uses Track entities"
        
        # Verify: Infrastructure/Database layer uses DBTrack models
        from src.infrastructure.persistence.database.db_models import DBTrack
        assert isinstance(persisted_db_track, DBTrack), "Infrastructure layer uses DBTrack models"
        
        # Verify: External/Connector layer uses service-specific models
        from src.infrastructure.connectors.lastfm import LastFMTrackInfo
        assert isinstance(lastfm_track_info, LastFMTrackInfo), "Connector layer uses service models"
        
        # Verify: Each type serves its architectural purpose
        assert persisted_track.id is not None, "Domain tracks for workflows must have DB IDs"
        assert persisted_db_track.id is not None, "Database models must have primary keys"
        assert hasattr(lastfm_track_info, 'lastfm_user_playcount'), "Service models have service-specific data"