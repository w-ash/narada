"""Unit tests for BaseRepository bulk operations."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.persistence.database.db_models import DBTrack
from src.infrastructure.persistence.repositories.base_repo import BaseRepository


class TestBulkOperations:
    """Test bulk operations in BaseRepository."""

    @pytest.fixture
    def mock_mapper(self):
        """Mock mapper for repository."""
        mapper = MagicMock()
        mapper.to_domain = AsyncMock()
        mapper.to_database = AsyncMock()
        return mapper

    @pytest.fixture
    def repo(self, db_session, mock_mapper):
        """BaseRepository instance with mocked dependencies."""
        return BaseRepository(
            session=db_session,
            model_class=DBTrack,
            mapper=mock_mapper,
        )

    @pytest.mark.asyncio
    async def test_bulk_upsert_empty_list(self, repo):
        """Should handle empty list gracefully."""
        result = await repo.bulk_upsert([], lookup_keys=["id"])
        assert result == []

    @pytest.mark.asyncio
    async def test_bulk_update_empty_list(self, repo):
        """Should handle empty updates gracefully."""
        result = await repo.bulk_update([])
        assert result == 0

    @pytest.mark.asyncio
    async def test_bulk_delete_empty_list(self, repo):
        """Should handle empty delete list gracefully."""
        result = await repo.bulk_delete([])
        assert result == 0

    @pytest.mark.asyncio
    async def test_bulk_delete_with_ids(self, repo):
        """Should soft delete by default."""
        # Mock the database execution
        mock_result = MagicMock()
        mock_result.rowcount = 3
        repo.session.execute = AsyncMock(return_value=mock_result)
        repo.session.flush = AsyncMock()
        
        result = await repo.bulk_delete([1, 2, 3])
        
        assert result == 3
        repo.session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_bulk_delete_hard_delete(self, repo):
        """Should hard delete when requested."""
        # Mock the database execution
        mock_result = MagicMock()
        mock_result.rowcount = 2
        repo.session.execute = AsyncMock(return_value=mock_result)
        repo.session.flush = AsyncMock()
        
        result = await repo.bulk_delete([1, 2], hard_delete=True)
        
        assert result == 2
        repo.session.execute.assert_called_once()