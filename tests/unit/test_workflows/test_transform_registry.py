"""Tests for the transform registry system."""

from unittest.mock import MagicMock

from src.application.workflows.transform_registry import TRANSFORM_REGISTRY


class TestTransformRegistry:
    """Test the transform registry functionality."""
    
    def test_get_filter_transform(self):
        """Test getting a filter transform."""
        # Test basic filter transform retrieval from registry
        assert "filter" in TRANSFORM_REGISTRY
        assert "deduplicate" in TRANSFORM_REGISTRY["filter"]
        
        # Test that the transform factory is callable
        transform_factory = TRANSFORM_REGISTRY["filter"]["deduplicate"]
        assert callable(transform_factory)
        
        # Test creating transform with mock context and config
        mock_context = MagicMock()
        mock_config = {}
        transform = transform_factory(mock_context, mock_config)
        assert callable(transform)
    
    def test_get_sort_transform(self):
        """Test getting a sort transform."""
        # Test sort transform retrieval from registry
        assert "sorter" in TRANSFORM_REGISTRY
        assert "by_metric" in TRANSFORM_REGISTRY["sorter"]
        
        transform_factory = TRANSFORM_REGISTRY["sorter"]["by_metric"]
        assert callable(transform_factory)
        
        # Test creating transform with parameters
        mock_context = MagicMock()
        sort_config = {"metric_name": "spotify_popularity", "reverse": True}
        transform = transform_factory(mock_context, sort_config)
        assert callable(transform)
    
    def test_get_select_transform(self):
        """Test getting a select transform."""
        # Test selector transform retrieval from registry
        assert "selector" in TRANSFORM_REGISTRY
        assert "limit_tracks" in TRANSFORM_REGISTRY["selector"]
        
        transform_factory = TRANSFORM_REGISTRY["selector"]["limit_tracks"]
        assert callable(transform_factory)
        
        # Test creating transform with parameters
        mock_context = MagicMock()
        select_config = {"count": 10, "method": "first"}
        transform = transform_factory(mock_context, select_config)
        assert callable(transform)
    
    def test_get_combine_transform(self):
        """Test getting a combine transform."""
        # Test combiner transform retrieval from registry
        assert "combiner" in TRANSFORM_REGISTRY
        assert "merge_playlists" in TRANSFORM_REGISTRY["combiner"]
        
        transform_factory = TRANSFORM_REGISTRY["combiner"]["merge_playlists"]
        assert callable(transform_factory)
        
        # Test creating transform with parameters
        mock_context = MagicMock()
        mock_context.collect_tracklists.return_value = []
        combine_config = {"sources": ["source1", "source2"]}
        transform = transform_factory(mock_context, combine_config)
        assert callable(transform)
    
    def test_invalid_transform_type(self):
        """Test getting transform with invalid type."""
        # Test that invalid categories don't exist in registry
        assert "invalid_type" not in TRANSFORM_REGISTRY
    
    def test_invalid_transform_method(self):
        """Test getting transform with invalid method."""
        # Test that invalid methods don't exist in valid categories
        assert "invalid_method" not in TRANSFORM_REGISTRY["filter"]
    
    def test_transform_registry_structure(self):
        """Test the basic structure of the transform registry."""
        # Test that all expected categories exist
        expected_categories = ["filter", "sorter", "selector", "combiner"]
        
        for category in expected_categories:
            assert category in TRANSFORM_REGISTRY
            assert isinstance(TRANSFORM_REGISTRY[category], dict)
            
            # Test that each category has at least one transform
            assert len(TRANSFORM_REGISTRY[category]) > 0


