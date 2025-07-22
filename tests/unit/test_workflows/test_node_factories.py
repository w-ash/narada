"""Essential node factory tests."""

from src.application.workflows.node_factories import make_node


class TestNodeFactories:
    """Test node factories create callable functions."""
    
    def test_make_node_creates_functions(self):
        """Test make_node returns callable functions."""
        # Test with actual categories and types from transform registry
        node_configs = [
            ("filter", "deduplicate"),
            ("sorter", "by_metric"),
            ("selector", "limit_tracks")
        ]
        
        for category, node_type in node_configs:
            node_func = make_node(category, node_type)
            assert callable(node_func)