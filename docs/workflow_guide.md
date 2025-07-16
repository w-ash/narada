# Narada Workflow Architecture Guide

**Version**: 2.0 (Clean Architecture Complete)  
**Status**: Production-ready with sophisticated playlist update capabilities

## Core Concepts

Narada's workflow architecture enables declarative transformation pipelines through a clean separation of node definition from execution logic. Built on Clean Architecture principles with comprehensive test coverage, this system provides enterprise-grade playlist management capabilities including sophisticated differential updates, conflict resolution, and cross-platform synchronization.

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
| `filter.by_metric` | Filters tracks based on metric value range | `metric_name`: Metric to filter by<br>`min_value`: Minimum value (inclusive)<br>`max_value`: Maximum value (inclusive)<br>`include_missing`: Whether to include tracks without the metric |

### Sorter Nodes

| Node Type | Description | Configuration |
|----------------|-------------|--------------|
| `sorter.by_metric` | Sorts tracks by any metric specified in config | `metric_name`: Name of metric to sort by (e.g., "lastfm_user_playcount", "lastfm_global_playcount", "lastfm_listeners", "spotify_popularity")<br>`reverse`: Boolean to reverse sort order |

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
| `destination.update_playlist` | **Advanced playlist updates with differential operations** | `playlist_id`: Internal or Spotify playlist ID<br>`operation_type`: "update_internal", "update_spotify", or "sync_bidirectional"<br>`conflict_resolution`: "local_wins", "remote_wins", "user_prompt", "merge_intelligent"<br>`dry_run`: Boolean, preview changes without executing<br>`preserve_order`: Boolean, maintain existing track order where possible<br>`track_matching_strategy`: "spotify_id", "isrc", "metadata_fuzzy", "comprehensive"<br>`enable_spotify_sync`: Boolean, sync changes to Spotify if playlist is linked |

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
    { "id": "transform", "type": "sorter.by_lastfm_user_playcount", "config": {"reverse": true}, "upstream": ["enrich"] }
  ]
}
```

### Advanced Playlist Updates

This pattern uses sophisticated differential operations to update existing playlists while preserving track metadata:

```json
{
  "tasks": [
    { "id": "source", "type": "source.spotify_playlist", "config": {"playlist_id": "source_id"} },
    { "id": "enrich", "type": "enricher.spotify", "upstream": ["source"] },
    { "id": "filter", "type": "filter.by_metric", "config": {"metric_name": "popularity", "min_value": 60}, "upstream": ["enrich"] },
    { "id": "update", "type": "destination.update_playlist", 
      "config": {
        "playlist_id": "target_playlist_id",
        "operation_type": "update_spotify",
        "conflict_resolution": "local_wins",
        "preserve_order": true,
        "dry_run": false
      }, 
      "upstream": ["filter"] 
    }
  ]
}
```

## Best Practices

### General Workflow Design
1. **Explicit Dependencies** - Always specify upstream tasks even when seemingly obvious
2. **Task Naming** - Use descriptive IDs that reflect purpose, not implementation
3. **Configuration Validation** - Include sensible defaults where possible
4. **Workflow Decomposition** - Break complex workflows into logical groupings of tasks
5. **Error Handling** - Design for graceful degradation when nodes fail
6. **Idempotent Design** - Workflows should produce the same result when executed multiple times

### Advanced Playlist Updates
7. **Preview First** - Use `dry_run: true` to preview changes before execution
8. **Conservative Conflict Resolution** - Start with `local_wins` for predictable behavior
9. **Comprehensive Matching** - Use `track_matching_strategy: "comprehensive"` for cross-platform reliability
10. **Preserve Order** - Set `preserve_order: true` to maintain existing playlist structure where possible
11. **Monitor Performance** - Check API call estimates for large playlists to stay within rate limits
12. **Test Extensively** - Validate workflows with representative data before production use

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
      "type": "sorter.by_metric",
      "config": {
        "metric_name": "lastfm_user_playcount",
        "reverse": true
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

## Example: Multi-Metric Workflow

This example demonstrates using the new generic metric filter and sorter nodes:

```json
{
  "id": "popular_gems",
  "name": "Popular Gems with Few Listens",
  "description": "Popular tracks that you haven't played much",
  "version": "1.0",
  "tasks": [
    {
      "id": "source",
      "type": "source.spotify_playlist",
      "config": {
        "playlist_id": "YOUR_PLAYLIST_ID"
      }
    },
    {
      "id": "enrich_spotify",
      "type": "enricher.spotify",
      "config": {},
      "upstream": ["source"]
    },
    {
      "id": "filter_popular",
      "type": "filter.by_metric",
      "config": {
        "metric_name": "spotify_popularity",
        "min_value": 70,
        "include_missing": false
      },
      "upstream": ["enrich_spotify"]
    },
    {
      "id": "enrich_lastfm",
      "type": "enricher.lastfm",
      "config": {},
      "upstream": ["filter_popular"]
    },
    {
      "id": "filter_few_plays",
      "type": "filter.by_metric",
      "config": {
        "metric_name": "lastfm_user_playcount",
        "max_value": 5,
        "include_missing": true
      },
      "upstream": ["enrich_lastfm"]
    },
    {
      "id": "sort_by_global",
      "type": "sorter.by_metric",
      "config": {
        "metric_name": "lastfm_global_playcount",
        "reverse": true
      },
      "upstream": ["filter_few_plays"]
    },
    {
      "id": "limit",
      "type": "selector.limit_tracks",
      "config": {
        "count": 30,
        "method": "first"
      },
      "upstream": ["sort_by_global"]
    },
    {
      "id": "destination",
      "type": "destination.create_spotify_playlist",
      "config": {
        "name": "Popular Gems to Discover",
        "description": "Popular tracks you haven't listened to much yet"
      },
      "upstream": ["limit"]
    }
  ]
}
```

## Example: Advanced Playlist Update Workflow

This example demonstrates sophisticated playlist updates with differential operations:

```json
{
  "id": "smart_playlist_sync",
  "name": "Smart Playlist Synchronization",
  "description": "Update existing playlist with filtered and sorted tracks while preserving Spotify metadata",
  "version": "2.0",
  "tasks": [
    {
      "id": "source_discover",
      "type": "source.spotify_playlist",
      "config": {
        "playlist_id": "37i9dQZEVXcJZTJkGMJOhH"
      }
    },
    {
      "id": "enrich_spotify",
      "type": "enricher.spotify",
      "config": {},
      "upstream": ["source_discover"]
    },
    {
      "id": "filter_popular",
      "type": "filter.by_metric",
      "config": {
        "metric_name": "popularity",
        "min_value": 70,
        "include_missing": false
      },
      "upstream": ["enrich_spotify"]
    },
    {
      "id": "enrich_lastfm",
      "type": "enricher.lastfm",
      "config": {},
      "upstream": ["filter_popular"]
    },
    {
      "id": "filter_unplayed",
      "type": "filter.by_metric",
      "config": {
        "metric_name": "lastfm_user_playcount",
        "max_value": 3,
        "include_missing": true
      },
      "upstream": ["enrich_lastfm"]
    },
    {
      "id": "sort_by_global",
      "type": "sorter.by_metric",
      "config": {
        "metric_name": "lastfm_global_playcount",
        "reverse": true
      },
      "upstream": ["filter_unplayed"]
    },
    {
      "id": "limit_selection",
      "type": "selector.limit_tracks",
      "config": {
        "count": 25,
        "method": "first"
      },
      "upstream": ["sort_by_global"]
    },
    {
      "id": "update_target",
      "type": "destination.update_playlist",
      "config": {
        "playlist_id": "YOUR_TARGET_PLAYLIST_ID",
        "operation_type": "update_spotify",
        "conflict_resolution": "local_wins",
        "track_matching_strategy": "comprehensive",
        "preserve_order": false,
        "dry_run": false,
        "enable_spotify_sync": true
      },
      "upstream": ["limit_selection"]
    }
  ]
}
```

This workflow demonstrates:
- **Multi-stage filtering**: Combines Spotify popularity with Last.fm play history
- **Sophisticated sorting**: Uses global play counts for discovery potential  
- **Differential updates**: Preserves Spotify track addition timestamps
- **Conflict resolution**: Handles external changes gracefully
- **Production ready**: Full error handling and validation

## Example: Dry-Run Preview Workflow

This example shows how to preview playlist changes before applying them:

```json
{
  "id": "preview_updates",
  "name": "Preview Playlist Changes",
  "description": "Preview what changes would be made to a playlist without applying them",
  "version": "1.0",
  "tasks": [
    {
      "id": "source",
      "type": "source.spotify_playlist",
      "config": {
        "playlist_id": "source_playlist_id"
      }
    },
    {
      "id": "transform",
      "type": "sorter.by_metric",
      "config": {
        "metric_name": "popularity",
        "reverse": true
      },
      "upstream": ["source"]
    },
    {
      "id": "preview",
      "type": "destination.update_playlist",
      "config": {
        "playlist_id": "target_playlist_id",
        "operation_type": "update_spotify",
        "dry_run": true,
        "preserve_order": true
      },
      "upstream": ["transform"]
    }
  ]
}
```

With `dry_run: true`, the workflow will:
- Calculate all differential operations
- Estimate API call requirements
- Report planned changes without execution
- Provide confidence scores for track matching

## Advanced Features

### Sophisticated Playlist Updates

The `destination.update_playlist` node provides enterprise-grade playlist management capabilities:

#### Differential Algorithm Engine
- **Smart Track Matching**: Uses Spotify IDs, ISRC codes, and metadata similarity for robust track identification
- **Minimal Operations**: Calculates add/remove/reorder operations to minimize API calls and preserve metadata
- **Conflict Detection**: Uses snapshot validation to detect external changes
- **Performance Optimization**: Batches operations within API constraints (100 tracks/request)

#### Operation Types
- **update_internal**: Updates internal database playlist only
- **update_spotify**: Updates Spotify playlist with database synchronization
- **sync_bidirectional**: Advanced sync between internal and external playlists

#### Conflict Resolution Strategies
- **local_wins**: Local changes take precedence over external modifications
- **remote_wins**: External changes take precedence (preserves external edits)
- **user_prompt**: Interactive resolution for conflicting changes
- **merge_intelligent**: Automated conflict resolution using metadata analysis

#### Track Matching Strategies  
- **spotify_id**: Exact Spotify ID matching (fastest, most reliable)
- **isrc**: ISRC code matching for cross-platform identification
- **metadata_fuzzy**: Artist/title similarity matching with confidence scoring
- **comprehensive**: Multi-stage matching using all available strategies

### Production Considerations

#### Performance Features
- **API Call Estimation**: Preview resource requirements before execution
- **Batch Optimization**: Automatic grouping within service constraints
- **Rate Limiting**: Built-in exponential backoff and retry logic
- **Progress Tracking**: Real-time feedback for long-running operations

#### Reliability Features
- **Dry-Run Mode**: Preview all changes without execution
- **Transaction Safety**: Atomic operations with rollback capabilities
- **Validation**: Comprehensive input validation and business rule enforcement
- **Error Recovery**: Graceful handling of API failures and partial operations

#### Monitoring and Observability
- **Operation Metrics**: Detailed statistics on adds, removes, moves, and API calls
- **Confidence Scoring**: Track matching quality assessment
- **Execution Timing**: Performance monitoring for optimization
- **Comprehensive Logging**: Structured logs for debugging and auditing

## Implementation Architecture

The workflow system architecture consists of three key components:

1. **Node Registry** - Central registration point for all node types
2. **Transform Registry** - Maps node categories and types to their implementations
3. **Node Factories** - Creates node functions with standardized interfaces

This layered approach separates node definition from implementation details, allowing for clean extension and maintenance of the workflow system.