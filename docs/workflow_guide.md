# Narada Workflow Architecture Guide

## Core Concepts

Narada's workflow architecture enables declarative transformation pipelines through a clean separation of node definition from execution logic. This architectural pattern has proven successful in production systems at scale, allowing non-technical users to build sophisticated workflows while maintaining a lean, maintainable codebase.

### Architectural Principles

1. **Separation of Concerns** - Workflow definitions describe *what* should happen, not *how* it happens
2. **Compositional Design** - Simple nodes combine to create complex behaviors
3. **Directed Acyclic Graphs** - Tasks execute in dependency order without circular references
4. **Immutable Data Flow** - Each transformation produces new state rather than mutating existing state
5. **Standardized Interfaces** - Nodes follow consistent contracts for composability
6. **Registry-Based Discovery** - Transform implementations are registered in a central registry for maintainability

## Workflow JSON Structure

A workflow is defined in JSON as a directed acyclic graph (DAG) of tasks:

```json
{
  "id": "workflow_id",
  "name": "Human-Readable Name",
  "description": "Workflow purpose description",
  "version": "1.0",
  "tasks": [
    {
      "id": "task_unique_id",
      "type": "node.type",
      "config": {
        "key": "value"
      },
      "upstream": ["dependency_task_id"]
    }
  ]
}
```

### Key Elements

- **id**: Unique identifier for the workflow
- **name**: Human-readable workflow name
- **description**: Purpose and behavior description
- **version**: Semantic version for tracking changes
- **tasks**: Array of task definitions that form the execution graph

### Task Definition

- **id**: Unique identifier within this workflow
- **type**: Node type that implements the behavior
- **config**: Node-specific configuration
- **upstream**: Array of task IDs that must complete before this task executes

## Node Reference

### Source Nodes

| Node Type | Description | Configuration |
|----------------|-------------|--------------|
| `source.spotify_playlist` | Fetches a playlist from Spotify | `playlist_id`: Spotify playlist ID |

### Enricher Nodes

| Node Type | Description | Configuration |
|----------------|-------------|--------------|
| `enricher.resolve_lastfm` | Resolves tracks to Last.fm and fetches play counts | `username`: Optional Last.fm username<br>`batch_size`: Optional batch size for requests<br>`concurrency`: Optional concurrency limit |

### Filter Nodes

| Node Type | Description | Configuration |
|----------------|-------------|--------------|
| `filter.deduplicate` | Removes duplicate tracks | (No configuration required) |
| `filter.by_release_date` | Filters tracks by release date | `max_age_days`: Maximum age in days<br>`min_age_days`: Minimum age in days |
| `filter.by_tracks` | Excludes tracks from input that are present in exclusion source | `exclusion_source`: Task ID of exclusion source |
| `filter.by_artists` | Excludes tracks whose artists appear in exclusion source | `exclusion_source`: Task ID of exclusion source<br>`exclude_all_artists`: Boolean, if true, excludes tracks if any artist is present in the exclusion source |

### Sorter Nodes

| Node Type | Description | Configuration |
|----------------|-------------|--------------|
| `sorter.by_user_plays` | Sorts tracks by user play counts | `reverse`: Boolean to reverse sort order<br>`min_confidence`: Minimum match confidence threshold |
| `sorter.by_spotify_popularity` | Sorts tracks by Spotify popularity | `reverse`: Boolean to reverse sort order |

### Selector Nodes

| Node Type | Description | Configuration |
|----------------|-------------|--------------|
| `selector.limit_tracks` | Limits playlist to specified number of tracks | `count`: Maximum number of tracks<br>`method`: Selection method (`first`, `last`, or `random`) |

### Combiner Nodes

| Node Type | Description | Configuration |
|----------------|-------------|--------------|
| `combiner.merge_playlists` | Combines multiple playlists into one | `sources`: Array of task IDs to combine |
| `combiner.concatenate_playlists` | Joins playlists in specified order | `order`: Array of task IDs in desired concatenation order |
| `combiner.interleave_playlists` | Interleaves tracks from multiple playlists | `sources`: Array of task IDs to interleave |

### Destination Nodes

| Node Type | Description | Configuration |
|----------------|-------------|--------------|
| `destination.create_internal_playlist` | Creates a playlist in internal database | `name`: Name for the playlist<br>`description`: Optional description |
| `destination.create_spotify_playlist` | Creates a new Spotify playlist | `name`: Name for the new playlist<br>`description`: Optional description |
| `destination.update_spotify_playlist` | Updates an existing Spotify playlist | `playlist_id`: Spotify playlist ID<br>`append`: Boolean, if true, append tracks rather than replace |

## Workflow Patterns

### Multi-Source Aggregation

This pattern combines tracks from multiple sources:

```json
{
  "tasks": [
    { "id": "source1", "type": "source.spotify_playlist", "config": {"playlist_id": "id1"} },
    { "id": "source2", "type": "source.spotify_playlist", "config": {"playlist_id": "id2"} },
    { "id": "combine", "type": "combiner.merge_playlists", "config": {"sources": ["source1", "source2"]}, "upstream": ["source1", "source2"] }
  ]
}
```

### Filter Chain

This pattern applies multiple sequential filters:

```json
{
  "tasks": [
    { "id": "source", "type": "source.spotify_playlist", "config": {"playlist_id": "id"} },
    { "id": "filter1", "type": "filter.by_release_date", "config": {"max_age_days": 90}, "upstream": ["source"] },
    { "id": "filter2", "type": "filter.not_in_playlist", "config": {"reference": "exclude_source"}, "upstream": ["filter1", "exclude_source"] }
  ]
}
```

### Enrichment and Transformation

This pattern enhances tracks with external data before transformation:

```json
{
  "tasks": [
    { "id": "source", "type": "source.spotify_playlist", "config": {"playlist_id": "id"} },
    { "id": "enrich", "type": "enricher.resolve_lastfm", "upstream": ["source"] },
    { "id": "transform", "type": "sorter.by_user_plays", "config": {"reverse": true}, "upstream": ["enrich"] }
  ]
}
```

## Best Practices

1. **Explicit Dependencies** - Always specify upstream tasks even when seemingly obvious
2. **Task Naming** - Use descriptive IDs that reflect purpose, not implementation
3. **Configuration Validation** - Include sensible defaults where possible
4. **Workflow Decomposition** - Break complex workflows into logical groupings of tasks
5. **Error Handling** - Design for graceful degradation when nodes fail
6. **Idempotent Design** - Workflows should produce the same result when executed multiple times

## Extending the System

The node-based architecture allows for system extension through the transform registry:

1. Add transform implementations to the `TRANSFORM_REGISTRY` in node_factories.py
2. Register the node with appropriate metadata in workflow_nodes.py
3. Document the node's purpose and configuration
4. Create workflows that leverage the new node

This extensibility model enables continuous evolution without increasing architectural complexity.

## Example: Discovery Mix Workflow

```json
{
  "id": "discovery_mix",
  "name": "New Release Discovery Mix",
  "description": "Create a playlist of recent tracks sorted by play count",
  "version": "1.0",
  "tasks": [
    {
      "id": "source",
      "type": "source.spotify_playlist",
      "config": {
        "playlist_id": "37i9dQZEVXcDXjmJJAvgkA"
      }
    },
    {
      "id": "filter_date",
      "type": "filter.by_release_date",
      "config": {
        "max_age_days": 90
      },
      "upstream": ["source"]
    },
    {
      "id": "resolve",
      "type": "enricher.resolve_lastfm",
      "config": {},
      "upstream": ["filter_date"]
    },
    {
      "id": "sort",
      "type": "sorter.by_user_plays",
      "config": {
        "reverse": true,
        "min_confidence": 50
      },
      "upstream": ["resolve"]
    },
    {
      "id": "limit",
      "type": "selector.limit_tracks",
      "config": {
        "count": 50,
        "method": "first"
      },
      "upstream": ["sort"]
    },
    {
      "id": "destination",
      "type": "destination.create_spotify_playlist",
      "config": {
        "name": "Discovery Mix (90 days)",
        "description": "Recent releases sorted by play count"
      },
      "upstream": ["limit"]
    }
  ]
}
```

## Implementation Architecture

The workflow system architecture consists of three key components:

1. **Node Registry** - Central registration point for all node types
2. **Transform Registry** - Maps node categories and types to their implementations
3. **Node Factories** - Creates node functions with standardized interfaces

This layered approach separates node definition from implementation details, allowing for clean extension and maintenance of the workflow system.