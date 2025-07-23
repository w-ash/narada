"""Tests for TrackIdentityResolver service."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.domain.entities import Artist, Track, TrackList
from src.domain.matching.types import MatchResult
from src.infrastructure.persistence.repositories.track import TrackRepositories
from src.infrastructure.services.track_identity_resolver import TrackIdentityResolver


@pytest.fixture
def mock_track_repos():
    """Create mock track repositories."""
    repos = Mock(spec=TrackRepositories)
    repos.connector = AsyncMock()
    repos.core = AsyncMock()
    return repos


@pytest.fixture
def identity_resolver(mock_track_repos):
    """Create TrackIdentityResolver instance."""
    return TrackIdentityResolver(mock_track_repos)


@pytest.fixture
def sample_tracklist():
    """Create sample tracklist for testing."""
    tracks = [
        Track(id=1, title="Home", artists=[Artist(name="Mac DeMarco")]),
        Track(id=2, title="Falling", artists=[Artist(name="Chris Lake")]),
        Track(id=3, title="Unknown", artists=[Artist(name="Unknown Artist")]),
    ]
    return TrackList(tracks=tracks)


class TestTrackIdentityResolver:
    """Test cases for TrackIdentityResolver service."""

    @pytest.mark.asyncio
    async def test_resolve_track_identities_with_existing_mappings(
        self, identity_resolver, mock_track_repos, sample_tracklist
    ):
        """Test resolving identities when mappings already exist."""
        # Setup: Mock existing mappings for tracks 1 and 2
        existing_mappings = {
            1: {"lastfm": "https://www.last.fm/music/mac+demarco/_/home"},
            2: {"lastfm": "https://www.last.fm/music/chris+lake/_/falling"},
        }
        mock_track_repos.connector.get_connector_mappings.return_value = existing_mappings

        # Setup: Mock tracks by ID lookup (needed for building MatchResult)
        mock_track_repos.core.find_tracks_by_ids.return_value = {
            1: sample_tracklist.tracks[0],
            2: sample_tracklist.tracks[1],
        }

        # Setup: Mock mapping info (needed for confidence/method/evidence)
        mock_track_repos.connector.get_mapping_info.return_value = {
            "confidence": 100,
            "match_method": "existing_mapping",
            "confidence_evidence": {},
        }

        # Setup: Mock provider (should not be called for existing mappings)
        mock_connector_instance = Mock()
        mock_provider = Mock()
        mock_provider.find_potential_matches = AsyncMock(return_value={})

        # Execute
        with patch(
            "src.infrastructure.services.track_identity_resolver.create_provider",
            return_value=mock_provider
        ):
            result = await identity_resolver.resolve_track_identities(
                sample_tracklist, "lastfm", mock_connector_instance
            )

        # Verify
        assert len(result) == 2  # Only tracks 1 and 2 have existing mappings
        
        # Check existing mappings were converted to MatchResult
        assert result[1].success is True
        assert result[1].connector_id == "https://www.last.fm/music/mac+demarco/_/home"
        assert result[1].track.id == 1
        assert result[1].confidence == 100
        
        assert result[2].success is True
        assert result[2].connector_id == "https://www.last.fm/music/chris+lake/_/falling"
        assert result[2].track.id == 2
        assert result[2].confidence == 100

        # Track 3 should have been sent to provider for new matching
        provider_call_tracks = mock_provider.find_potential_matches.call_args[0][0]
        assert len(provider_call_tracks) == 1
        assert provider_call_tracks[0].id == 3

    @pytest.mark.asyncio
    async def test_resolve_track_identities_no_existing_mappings(
        self, identity_resolver, mock_track_repos, sample_tracklist
    ):
        """Test resolving identities when no mappings exist."""
        # Setup: No existing mappings
        mock_track_repos.connector.get_connector_mappings.return_value = {}

        # Setup: Mock provider to return new matches
        mock_connector_instance = Mock()
        mock_provider = Mock()
        new_matches = {
            1: MatchResult(
                track=sample_tracklist.tracks[0],
                success=True,
                connector_id="https://www.last.fm/music/mac+demarco/_/home",
                confidence=95,
                match_method="artist_title",
                service_data={"title": "Home", "artist": "Mac DeMarco"},
                evidence={"score": 0.95}
            ),
            2: MatchResult(
                track=sample_tracklist.tracks[1],
                success=True,
                connector_id="https://www.last.fm/music/chris+lake/_/falling",
                confidence=90,
                match_method="artist_title",
                service_data={"title": "Falling", "artist": "Chris Lake"},
                evidence={"score": 0.90}
            ),
        }
        mock_provider.find_potential_matches = AsyncMock(return_value=new_matches)

        # Execute
        with patch(
            "src.infrastructure.services.track_identity_resolver.create_provider",
            return_value=mock_provider
        ):
            result = await identity_resolver.resolve_track_identities(
                sample_tracklist, "lastfm", mock_connector_instance
            )

        # Verify
        assert len(result) == 2  # Only successful matches returned
        assert result[1].success is True
        assert result[1].confidence == 95
        assert result[2].success is True
        assert result[2].confidence == 90

        # All tracks should have been sent to provider
        provider_call_tracks = mock_provider.find_potential_matches.call_args[0][0]
        assert len(provider_call_tracks) == 3

    @pytest.mark.asyncio
    async def test_resolve_track_identities_mixed_scenario(
        self, identity_resolver, mock_track_repos, sample_tracklist
    ):
        """Test resolving identities with mix of existing and new mappings."""
        # Setup: Existing mapping for track 1 only
        existing_mappings = {
            1: {"lastfm": "https://www.last.fm/music/mac+demarco/_/home"},
        }
        mock_track_repos.connector.get_connector_mappings.return_value = existing_mappings

        # Setup: Mock tracks by ID lookup for existing mapping
        mock_track_repos.core.find_tracks_by_ids.return_value = {
            1: sample_tracklist.tracks[0],
        }

        # Setup: Mock mapping info for existing mapping
        mock_track_repos.connector.get_mapping_info.return_value = {
            "confidence": 100,
            "match_method": "existing_mapping",
            "confidence_evidence": {},
        }

        # Setup: Provider returns match for track 2, fails for track 3
        mock_connector_instance = Mock()
        mock_provider = Mock()
        new_matches = {
            2: MatchResult(
                track=sample_tracklist.tracks[1],
                success=True,
                connector_id="https://www.last.fm/music/chris+lake/_/falling",
                confidence=85,
                match_method="artist_title",
                service_data={"title": "Falling", "artist": "Chris Lake"},
                evidence={"score": 0.85}
            ),
            # Track 3 not in results (failed to match)
        }
        mock_provider.find_potential_matches = AsyncMock(return_value=new_matches)

        # Execute
        with patch(
            "src.infrastructure.services.track_identity_resolver.create_provider",
            return_value=mock_provider
        ):
            result = await identity_resolver.resolve_track_identities(
                sample_tracklist, "lastfm", mock_connector_instance
            )

        # Verify
        assert len(result) == 2  # Tracks 1 and 2 successful, track 3 failed

        # Track 1: From existing mapping
        assert result[1].success is True
        assert result[1].connector_id == "https://www.last.fm/music/mac+demarco/_/home"
        assert result[1].confidence == 100  # Existing mappings get 100% confidence

        # Track 2: From new provider match
        assert result[2].success is True
        assert result[2].connector_id == "https://www.last.fm/music/chris+lake/_/falling"
        assert result[2].confidence == 85

        # Track 3: Not in results (failed to match)
        assert 3 not in result

        # Provider should only be called with tracks 2 and 3 (not existing track 1)
        provider_call_tracks = mock_provider.find_potential_matches.call_args[0][0]
        track_ids = [t.id for t in provider_call_tracks]
        assert sorted(track_ids) == [2, 3]

    @pytest.mark.asyncio
    async def test_resolve_track_identities_empty_tracklist(
        self, identity_resolver, mock_track_repos
    ):
        """Test resolving identities with empty tracklist."""
        empty_tracklist = TrackList(tracks=[])
        mock_connector_instance = Mock()

        result = await identity_resolver.resolve_track_identities(
            empty_tracklist, "lastfm", mock_connector_instance
        )

        assert result == {}
        mock_track_repos.connector.get_connector_mappings.assert_not_called()

    @pytest.mark.asyncio
    async def test_resolve_track_identities_provider_exception(
        self, identity_resolver, mock_track_repos, sample_tracklist
    ):
        """Test handling of provider exceptions."""
        # Setup: No existing mappings, provider raises exception
        mock_track_repos.connector.get_connector_mappings.return_value = {}
        
        mock_connector_instance = Mock()
        mock_provider = Mock()
        mock_provider.find_potential_matches = AsyncMock(
            side_effect=Exception("API connection failed")
        )

        # Execute - exception should propagate (no exception handling in service)
        with patch(
            "src.infrastructure.services.track_identity_resolver.create_provider",
            return_value=mock_provider
        ), pytest.raises(Exception, match="API connection failed"):
            await identity_resolver.resolve_track_identities(
                sample_tracklist, "lastfm", mock_connector_instance
            )

    @pytest.mark.asyncio
    async def test_resolve_track_identities_tracks_without_ids(
        self, identity_resolver, mock_track_repos
    ):
        """Test resolving identities for tracks without database IDs."""
        # Create tracks without IDs
        tracks_no_ids = [
            Track(title="Home", artists=[Artist(name="Mac DeMarco")]),
            Track(title="Falling", artists=[Artist(name="Chris Lake")]),
        ]
        tracklist = TrackList(tracks=tracks_no_ids)
        mock_connector_instance = Mock()

        result = await identity_resolver.resolve_track_identities(
            tracklist, "lastfm", mock_connector_instance
        )

        # Should return empty since tracks need IDs for identity resolution
        assert result == {}
        mock_track_repos.connector.get_connector_mappings.assert_not_called()