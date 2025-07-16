# Narada Likes Synchronization Guide

This guide explains how to use Narada to synchronize "liked" tracks between different music services, with Narada serving as the source of truth for your music preferences.

## Overview

Narada's likes synchronization system enables you to:

1. **Import liked tracks from Spotify** into the local Narada database
2. **Export liked tracks from Narada to Last.fm** as "loved" tracks
3. **Maintain synchronization over time** with incremental updates
4. **Preserve complete track metadata** while handling cross-service differences

The system uses intelligent track matching and checkpoint tracking to ensure reliable, resumable operations that handle the complexities of cross-service synchronization.

## Prerequisites

Before using the likes synchronization features, ensure:

1. **Service Configuration**: Run `narada setup` to configure API keys and OAuth tokens
2. **Database Initialization**: Database is automatically created on first run
3. **Connection Verification**: Check service status with `narada status`

## Command Usage

### Importing Liked Tracks from Spotify

```bash
narada import-spotify-likes [OPTIONS]
```

This command fetches tracks you've saved/liked on Spotify and imports them into the Narada database, preserving their like status and complete metadata.

#### Options

- `--limit NUMBER`: Maximum number of tracks to import (default: no limit)
- `--batch-size NUMBER`: Number of tracks to process per batch (default: 100)
- `--user-id STRING`: Spotify user ID (default: current user)

#### Examples

```bash
# Import all liked tracks from Spotify
narada import-spotify-likes

# Import with custom batch size for slower connections
narada import-spotify-likes --batch-size 50

# Import only the most recent 500 liked tracks
narada import-spotify-likes --limit 500
```

#### What Happens During Import

1. **Fetch Liked Tracks**: Retrieves your saved tracks from Spotify
2. **Track Resolution**: Creates or updates tracks in the local database
3. **Metadata Storage**: Preserves complete Spotify metadata
4. **Like Status**: Marks tracks as liked in Narada
5. **Progress Tracking**: Shows real-time progress with Rich formatting
6. **Checkpoint Saving**: Enables resumable operations if interrupted

### Exporting Liked Tracks to Last.fm

```bash
narada export-likes-to-lastfm [OPTIONS]
```

This command identifies tracks that are liked in Narada but not yet loved on Last.fm, and marks them as loved on Last.fm through intelligent track matching.

#### Options

- `--limit NUMBER`: Maximum number of tracks to export (default: no limit)
- `--batch-size NUMBER`: Number of tracks to process per batch (default: 100)
- `--user-id STRING`: Last.fm username (default: configured user)

#### Examples

```bash
# Export all liked tracks to Last.fm
narada export-likes-to-lastfm

# Export with smaller batch size for API stability
narada export-likes-to-lastfm --batch-size 25

# Export only the first 100 tracks for testing
narada export-likes-to-lastfm --limit 100
```

#### What Happens During Export

1. **Track Matching**: Uses sophisticated algorithms to match tracks between services
2. **Confidence Scoring**: Ensures high-quality matches before export
3. **API Integration**: Marks tracks as "loved" on Last.fm
4. **Progress Tracking**: Shows matching success rates and export progress
5. **Error Handling**: Gracefully handles API limits and failures
6. **Checkpoint Saving**: Tracks export progress for resumability

## System Architecture

The likes synchronization system follows Clean Architecture principles with well-defined layers:

### Application Layer
- **Use Cases**: `ImportSpotifyLikesUseCase` and `ExportLikesToLastfmUseCase` orchestrate business logic
- **Services**: `LikeOperationService` provides reusable like management operations
- **Checkpoint Management**: Tracks sync progress for resumable operations

### Domain Layer
- **Entities**: `Track`, `TrackLike` represent core business objects
- **Matching Algorithms**: Sophisticated track matching with confidence scoring
- **Business Rules**: Like status validation and conflict resolution

### Infrastructure Layer
- **Connectors**: 
  - `SpotifyConnector`: OAuth integration with `get_liked_tracks()` method
  - `LastfmConnector`: API integration with `love_track()` method
- **Repositories**: `TrackRepository`, `TrackLikeRepository` for data persistence
- **CLI Commands**: Rich-formatted commands with progress tracking

### Key Design Patterns
- **Repository Pattern**: Consistent data access across services
- **Command Pattern**: Rich command objects with validation
- **Strategy Pattern**: Pluggable matching algorithms
- **Resilient Operations**: Automatic retry with exponential backoff

## Common Scenarios

### Initial Complete Synchronization

To fully synchronize your likes between Spotify and Last.fm for the first time:

```bash
# Step 1: Import all liked tracks from Spotify
narada import-spotify-likes

# Step 2: Export all liked tracks to Last.fm
narada export-likes-to-lastfm
```

**Expected Results**:
- All Spotify liked tracks imported to local database
- Tracks successfully matched to Last.fm marked as "loved"
- Progress tracking shows match success rates
- Checkpoint saved for future incremental updates

### Incremental Updates

After the initial synchronization, run the same commands periodically to keep services in sync:

```bash
# Run weekly or monthly to catch new likes
narada import-spotify-likes
narada export-likes-to-lastfm
```

The checkpoint system ensures only new changes are processed, making subsequent runs much faster.

### Large Library Synchronization

For very large music libraries, use batch sizing and limits:

```bash
# Import in smaller batches for stability
narada import-spotify-likes --batch-size 50

# Export in smaller batches with rate limiting consideration
narada export-likes-to-lastfm --batch-size 25
```

### Testing and Validation

To test the system before full synchronization:

```bash
# Test import with a small subset
narada import-spotify-likes --limit 100

# Test export with a small subset
narada export-likes-to-lastfm --limit 50

# Check results
narada status
```

## Track Matching System

### How Track Matching Works

Narada uses a sophisticated multi-stage matching process:

1. **Exact ID Matching**: Uses Spotify ID, ISRC, and MusicBrainz ID for deterministic matches
2. **Metadata Matching**: Fuzzy matching on artist names and track titles
3. **Confidence Scoring**: Each match receives a confidence score (0-100)
4. **Threshold Filtering**: Only high-confidence matches (typically >70) are exported

### Matching Success Rates

Typical matching success rates:
- **Spotify → Last.fm**: 85-95% for mainstream music
- **Older/Obscure Tracks**: 70-85% success rate
- **Classical/Non-English**: Variable, often 60-80%

### Improving Match Quality

To improve matching results:
- Ensure your Last.fm library is well-maintained
- Use the latest version of Narada with updated matching algorithms
- Consider manual intervention for important unmatched tracks

## Troubleshooting

### Missing Track Matches

**Symptoms**: Some tracks imported but not exported to Last.fm

**Causes**:
- Track metadata differs significantly between services
- Track not available in Last.fm database
- Missing identification data (ISRC, MusicBrainz ID)
- Confidence score below threshold

**Solutions**:
- Check match quality in operation output
- Manually love important tracks on Last.fm
- Wait for future matcher improvements

### Rate Limiting Issues

**Symptoms**: Operations slow down or fail with rate limit errors

**Solutions**:
```bash
# Reduce batch size
narada import-spotify-likes --batch-size 25
narada export-likes-to-lastfm --batch-size 10

# Wait and retry - the system includes automatic backoff
```

### Interrupted Operations

**Symptoms**: Command stops due to network issues or interruption

**Solutions**:
- Simply run the same command again
- The checkpoint system automatically resumes from where it left off
- No data loss or duplication will occur

### Authentication Issues

**Symptoms**: API errors related to authentication

**Solutions**:
```bash
# Check service status
narada status

# Reconfigure services if needed
narada setup
```

### Database Issues

**Symptoms**: Database errors or corruption

**Solutions**:
```bash
# Check database status
narada status

# Database is automatically created and maintained
# For serious issues, check logs and consider database reset
```

## Performance Optimization

### Batch Size Tuning

- **Import**: Start with default (100), reduce if experiencing timeouts
- **Export**: Start with default (100), reduce for API stability
- **Network Issues**: Use smaller batches (25-50) for reliability

### Monitoring Progress

The system provides real-time feedback:
- Progress bars show completion percentage
- Match success rates displayed during export
- Checkpoint information for resumability
- Error counts and retry attempts

### Resource Usage

- **Memory**: Minimal memory usage due to streaming operations
- **Network**: Respects API rate limits with automatic backoff
- **Storage**: Efficient database storage with indexing

## Related Documentation

- **[API.md](API.md)** - Complete CLI command reference including likes sync commands
- **[ARCHITECTURE.md](ARCHITECTURE.md)** - System architecture and design patterns used in likes sync
- **[DATABASE.md](DATABASE.md)** - Database schema for tracks, likes, and sync checkpoints
- **[DEVELOPMENT.md](DEVELOPMENT.md)** - Developer guide for extending the likes sync system
- **[workflow_guide.md](workflow_guide.md)** - Workflow system for advanced playlist operations
- **[BACKLOG.md](../BACKLOG.md)** - Future enhancements planned for likes synchronization