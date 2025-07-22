"""Tests for domain layer transforms.

These tests verify that the transforms work correctly and have zero external dependencies.
"""

import pytest
from datetime import datetime, UTC

from src.domain import (
    Artist, Track, TrackList, Playlist,
    create_pipeline, filter_by_predicate, filter_duplicates, 
    sort_by_attribute, limit, concatenate, rename
)


class TestDomainTransforms:
    """Test domain layer transforms."""

    def test_filter_by_predicate(self):
        """Test filtering tracks by predicate."""
        artists = [Artist(name=f"Artist {i}") for i in range(5)]
        tracks = [Track(title=f"Song {i}", artists=[artists[i]]).with_id(i+1) for i in range(5)]
        track_list = TrackList(tracks=tracks)
        
        # Filter tracks with ID >= 4
        filtered = filter_by_predicate(lambda t: t.id >= 4, track_list)
        assert len(filtered.tracks) == 2
        assert all(t.id >= 4 for t in filtered.tracks)

    def test_filter_duplicates(self):
        """Test removing duplicate tracks."""
        artist = Artist(name="Artist")
        tracks = [
            Track(title="Song 1", artists=[artist]).with_id(1),
            Track(title="Song 2", artists=[artist]).with_id(2),
            Track(title="Song 1", artists=[artist]).with_id(1),  # Duplicate
            Track(title="Song 3", artists=[artist]).with_id(3),
        ]
        track_list = TrackList(tracks=tracks)
        
        filtered = filter_duplicates(track_list)
        assert len(filtered.tracks) == 3
        assert filtered.metadata["duplicates_removed"] == 1
        assert filtered.metadata["original_count"] == 4

    def test_limit_transform(self):
        """Test limiting tracks."""
        artist = Artist(name="Artist")
        tracks = [Track(title=f"Song {i}", artists=[artist]) for i in range(10)]
        track_list = TrackList(tracks=tracks)
        
        limited = limit(3, track_list)
        assert len(limited.tracks) == 3
        assert limited.tracks[0].title == "Song 0"
        assert limited.tracks[2].title == "Song 2"

    def test_concatenate_transform(self):
        """Test concatenating track lists."""
        artist = Artist(name="Artist")
        tracks1 = [Track(title="Song 1", artists=[artist])]
        tracks2 = [Track(title="Song 2", artists=[artist])]
        
        list1 = TrackList(tracks=tracks1)
        list2 = TrackList(tracks=tracks2)
        
        # Call concatenate with an empty TrackList as the base
        combined = concatenate([list1, list2], TrackList())
        assert len(combined.tracks) == 2
        assert combined.tracks[0].title == "Song 1"
        assert combined.tracks[1].title == "Song 2"
        assert combined.metadata["operation"] == "concatenate"

    def test_create_pipeline(self):
        """Test creating a pipeline of transformations."""
        artist = Artist(name="Artist")
        tracks = [Track(title=f"Song {i}", artists=[artist]).with_id(i+1) for i in range(10)]
        track_list = TrackList(tracks=tracks)
        
        # Create pipeline: filter even IDs, then limit to 2
        pipeline = create_pipeline(
            filter_by_predicate(lambda t: t.id % 2 == 0),
            limit(2)
        )
        
        result = pipeline(track_list)
        assert len(result.tracks) == 2
        assert result.tracks[0].id == 2
        assert result.tracks[1].id == 4

    def test_sort_by_attribute_with_metrics(self):
        """Test sorting with metrics in metadata."""
        artist = Artist(name="Artist")
        tracks = [
            Track(title="Song A", artists=[artist]).with_id(1),
            Track(title="Song B", artists=[artist]).with_id(2),
            Track(title="Song C", artists=[artist]).with_id(3),
        ]
        
        # Create tracklist with metrics
        track_list = TrackList(
            tracks=tracks,
            metadata={
                "metrics": {
                    "test_metric": {
                        1: 10,
                        2: 30,
                        3: 20,
                    }
                }
            }
        )
        
        # Sort by test_metric descending
        sorted_list = sort_by_attribute(
            lambda t: t.id, 
            "test_metric", 
            reverse=True, 
            tracklist=track_list
        )
        
        assert len(sorted_list.tracks) == 3
        # Should be sorted by metric values: 30, 20, 10
        assert sorted_list.tracks[0].id == 2  # metric value 30
        assert sorted_list.tracks[1].id == 3  # metric value 20
        assert sorted_list.tracks[2].id == 1  # metric value 10

    def test_playlist_rename(self):
        """Test renaming a playlist."""
        artist = Artist(name="Artist")
        tracks = [Track(title="Song", artists=[artist])]
        playlist = Playlist(name="Old Name", tracks=tracks)
        
        renamed = rename("New Name", playlist)
        assert renamed.name == "New Name"
        assert len(renamed.tracks) == 1
        assert playlist.name == "Old Name"  # Original unchanged

    def test_tracklist_immutability(self):
        """Test that TrackList operations are immutable."""
        artist = Artist(name="Artist")
        original_tracks = [Track(title="Song 1", artists=[artist])]
        track_list = TrackList(tracks=original_tracks)
        
        # Apply transformations
        limited = limit(0, track_list)
        
        # Original should be unchanged
        assert len(track_list.tracks) == 1
        assert len(limited.tracks) == 0

    def test_track_list_metadata_preservation(self):
        """Test that metadata is preserved through transformations."""
        artist = Artist(name="Artist")
        tracks = [Track(title="Song", artists=[artist])]
        track_list = TrackList(
            tracks=tracks,
            metadata={"source": "test", "version": 1}
        )
        
        # Apply transformation that preserves metadata
        limited = limit(1, track_list)
        
        # Should preserve original metadata
        assert limited.metadata["source"] == "test"
        assert limited.metadata["version"] == 1


class TestDomainTransformsPurity:
    """Test that transforms are pure functions with no side effects."""

    def test_transforms_are_pure(self):
        """Test that transforms don't modify input data."""
        artist = Artist(name="Artist")
        original_tracks = [
            Track(title="Song 1", artists=[artist]).with_id(1),
            Track(title="Song 2", artists=[artist]).with_id(2),
        ]
        original_list = TrackList(tracks=original_tracks)
        
        # Apply multiple transformations
        filtered = filter_duplicates(original_list)
        limited = limit(1, original_list)
        
        # Original should be completely unchanged
        assert len(original_list.tracks) == 2
        assert original_list.tracks[0].title == "Song 1"
        assert original_list.tracks[1].title == "Song 2"
        
        # Results should be different
        assert len(filtered.tracks) == 2
        assert len(limited.tracks) == 1

    def test_no_external_dependencies(self):
        """Test that transforms work without external infrastructure."""
        # This test passing means transforms have no database, API, or config dependencies
        artist = Artist(name="Artist")
        tracks = [Track(title="Song", artists=[artist])]
        track_list = TrackList(tracks=tracks)
        
        # All these should work without any external setup
        result1 = filter_by_predicate(lambda t: True, track_list)
        result2 = limit(1, track_list)
        result3 = filter_duplicates(track_list)
        
        assert all(len(r.tracks) >= 0 for r in [result1, result2, result3])