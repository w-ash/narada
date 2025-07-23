"""Tests for the node registry system."""


import pytest

from src.application.workflows.node_registry import (
    get_node,
    list_nodes,
    node,
)


class TestNodeRegistry:
    """Test the node registry functionality."""
    
    def test_register_node_decorator(self):
        """Test that nodes can be registered using the decorator."""
        # Create a mock function to register
        @node("test_source", category="source", description="Test source node")
        async def test_source_node(context, config):
            return {"data": "source_data"}
        
        # Verify the node was registered
        node_func, metadata = get_node("test_source")
        assert node_func is not None
        assert metadata is not None
        assert metadata["category"] == "source"
        assert metadata["id"] == "test_source"
        assert metadata["description"] == "Test source node"
    
    def test_register_node_with_description(self):
        """Test registering a node with description."""
        @node("test_enricher", category="enricher", description="Enriches tracks with metadata")
        async def test_enricher_node(context, config):
            return {"data": "enriched_data"}
        
        _node_func, metadata = get_node("test_enricher")
        assert metadata["description"] == "Enriches tracks with metadata"
    
    def test_register_node_with_parameters(self):
        """Test registering a node with input/output types."""
        @node("test_selector", category="selector", input_type="TrackList", output_type="TrackList")
        async def test_selector_node(context, config):
            return {"data": "selected_data"}
        
        _node_func, metadata = get_node("test_selector")
        assert metadata["input_type"] == "TrackList"
        assert metadata["output_type"] == "TrackList"
    
    def test_get_node_not_found(self):
        """Test getting non-existent node raises KeyError."""
        with pytest.raises(KeyError):
            get_node("non_existent_node")
    
    def test_list_nodes_by_type(self):
        """Test listing nodes filtered by type."""
        # Register some test nodes
        @node("test_filter_1", category="filter")
        async def filter_1(context, config):
            pass
        
        @node("test_filter_2", category="filter") 
        async def filter_2(context, config):
            pass
        
        @node("test_sorter", category="sorter")
        async def sorter(context, config):
            pass
        
        # Test listing all nodes
        all_nodes = list_nodes()
        node_ids = list(all_nodes.keys())
        
        assert "test_filter_1" in node_ids
        assert "test_filter_2" in node_ids
        assert "test_sorter" in node_ids
    
    def test_list_all_nodes(self):
        """Test listing all registered nodes."""
        # This will include nodes from other tests
        all_nodes = list_nodes()
        assert len(all_nodes) > 0
        
        # Verify we get metadata dictionaries
        for node_id, metadata in all_nodes.items():
            assert isinstance(node_id, str)
            assert isinstance(metadata, dict)
            assert "id" in metadata
            assert "category" in metadata
    
    def test_node_registry_singleton_behavior(self):
        """Test that the registry maintains state across calls."""
        # Register a unique node
        @node("singleton_test", category="destination")
        async def singleton_node(context, config):
            pass
        
        # Verify it's accessible from different calls
        node_func1, metadata1 = get_node("singleton_test")
        node_func2, _metadata2 = get_node("singleton_test")
        
        assert node_func1 is node_func2  # Same function reference
        assert metadata1["id"] == "singleton_test"


class TestNodeTypes:
    """Test the NodeType literal type."""
    
    def test_node_type_values(self):
        """Test that all expected node types are supported."""
        # NodeType is a literal type, so we test by using the values
        expected_types = [
            "source", "enricher", "filter", "sorter", 
            "selector", "combiner", "destination"
        ]
        
        # Test that we can create nodes with these types
        for node_type in expected_types:
            @node(f"test_{node_type}", category=node_type)
            async def test_node(context, config):
                pass
            
            # Should not raise an error
            _node_func, metadata = get_node(f"test_{node_type}")
            assert metadata["category"] == node_type


