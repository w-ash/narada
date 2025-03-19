# Narada Likes Synchronization Guide

This guide explains how to use Narada to synchronize "liked" tracks between different music services, with Narada serving as the source of truth.

## Overview

Narada allows you to:

1. Import liked tracks from Spotify into the local Narada database
2. Export liked tracks from Narada to Last.fm as "loved" tracks
3. Maintain synchronization over time

The system uses checkpoints to track progress, allowing operations to be resumed if interrupted, and employs an intelligent matching system to ensure tracks are properly identified across services with different metadata structures.

## Prerequisites

Before using the likes synchronization features, ensure:

1. You have configured API keys for the services you wish to synchronize
2. You've initialized the database with `narada init-db`
3. You've verified service connections with `narada status`

## Command Usage

### Importing Liked Tracks from Spotify

```bash
narada import-spotify-likes [options]
```

This command fetches tracks you've saved/liked on Spotify and imports them into the Narada database, preserving their like status. 

#### Options

- `--limit`, `-l`: Maximum number of tracks to import (default: all)
- `--batch-size`, `-b`: Number of tracks to fetch per API request (default: 50)
- `--user-id`, `-u`: User ID for checkpoint tracking (default: "default")

#### Example

```bash
# Import all liked tracks from Spotify using batches of 20
narada import-spotify-likes --batch-size 20

# Import only the most recent 100 liked tracks
narada import-spotify-likes --limit 100
```

### Exporting Liked Tracks to Last.fm

```bash
narada export-likes-to-lastfm [options]
```

This command identifies tracks that are liked in Narada but not yet loved on Last.fm, and marks them as loved on Last.fm.

#### Options

- `--limit`, `-l`: Maximum number of tracks to export (default: all)
- `--batch-size`, `-b`: Number of tracks to process in each batch (default: 20)
- `--user-id`, `-u`: User ID for checkpoint tracking (default: "default")

#### Example

```bash
# Export all liked tracks to Last.fm
narada export-likes-to-lastfm

# Export up to 50 liked tracks to Last.fm in small batches
narada export-likes-to-lastfm --limit 50 --batch-size 10
```

## Architecture

The likes synchronization system uses several key components:

1. **Service Layer**:
   - `like_sync.py`: High-level operations for syncing likes
   - `like_operations.py`: Reusable components for track likes

2. **Repository Layer**:
   - `track_sync.py`: Track like repository for persistence

3. **Connector Layer**:
   - `spotify.py`: Interface to Spotify API with `get_liked_tracks()` method
   - `lastfm.py`: Interface to Last.fm API with `love_track()` method

4. **Supporting Components**:
   - `matcher.py`: Entity resolution for cross-service matching
   - Checkpoint tracking for resumable operations

## Common Scenarios

### Complete Synchronization

To fully synchronize your likes between Spotify and Last.fm:

```bash
# Step 1: Import likes from Spotify
narada import-spotify-likes

# Step 2: Export likes to Last.fm
narada export-likes-to-lastfm
```

### Incremental Updates

After the initial synchronization, you can run the same commands periodically to keep the services in sync. The system tracks what has already been synchronized, so it will only process new changes.

## Troubleshooting

### Missing Track Matches

Some tracks might not be exported due to poor matches between services. This typically happens when:

1. Track metadata differs significantly between services
2. One service doesn't have a particular track in its database
3. Identification data (ISRC, MBID) is missing

For tracks that aren't automatically matched, you can:
- Wait for future improvements to the matcher
- Manually love the tracks on Last.fm

### Rate Limiting

If you encounter rate limiting issues:
- Reduce the batch size (`--batch-size` option)
- Retry the operation after a waiting period

### Resuming Interrupted Operations

If an operation is interrupted, simply run the same command again. The checkpoint system will resume from where it left off.