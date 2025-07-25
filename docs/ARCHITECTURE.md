# Narada System Architecture

## System Overview

Narada is a personal music metadata hub that integrates Spotify, Last.fm, and MusicBrainz to give users ownership of their listening data while enabling powerful cross-service operations that no single platform provides.

### Core Problem

Music streaming services operate in silos. Users cannot:
- Sort a Spotify playlist by personal Last.fm play counts
- Sync likes between services through intelligent track matching
- Build sophisticated playlists using cross-service data
- Maintain ownership of their listening history and metadata

### Solution Architecture

By maintaining local representations of music entities with cross-service mappings, Narada enables features that transcend individual platform limitations. The system acts as an intelligent bridge between services, providing a unified view of personal music data.

## Clean Architecture Foundation

Narada implements Clean Architecture principles with strict dependency boundaries to ensure maintainability, testability, and adaptability.

### Dependency Flow

```
External Services → Infrastructure → Application → Domain
```

Dependencies only flow inward, creating a stable core surrounded by adaptable interfaces.

### Layer Responsibilities

#### Domain Layer (`src/domain/`)
- **Purpose**: Pure business logic with zero external dependencies
- **Contents**: Core entities, business rules, algorithms
- **Examples**: Track matching algorithms, confidence scoring, playlist transformations
- **Benefits**: Fast tests, pure functions, technology-agnostic

#### Application Layer (`src/application/`)
- **Purpose**: Use cases and business workflow orchestration
- **Contents**: Use case implementations, workflow definitions, business services
- **Examples**: ImportTracksUseCase, WorkflowExecutor, PlaylistOrchestrator
- **Benefits**: Testable business logic, clear boundaries, reusable components

#### Infrastructure Layer (`src/infrastructure/`)
- **Purpose**: External integrations and framework adapters
- **Contents**: Database repositories, API connectors, CLI commands
- **Examples**: SpotifyConnector, SQLAlchemyRepository, TyperCLI
- **Benefits**: Swappable implementations, isolated side effects

### Why Clean Architecture?

1. **Testability**: Business logic isolated from external dependencies
2. **Maintainability**: Clear separation of concerns prevents tangled code
3. **Adaptability**: Can add new interfaces (web, mobile) without changing core logic
4. **Development Speed**: New features built on stable foundations
5. **Technology Independence**: Core logic works with any database or API

## Key Architectural Patterns

### Repository Pattern
Centralizes data access with consistent async interfaces.

```python
# Domain interface
class TrackRepository(Protocol):
    async def get_by_spotify_ids(self, spotify_ids: list[str]) -> list[Track]:
        ...
    
    async def save_batch(self, tracks: list[Track]) -> list[Track]:
        ...

# Infrastructure implementation
class SQLAlchemyTrackRepository:
    async def get_by_spotify_ids(self, spotify_ids: list[str]) -> list[Track]:
        # Database-specific implementation
```

**Benefits**: Consistent data access, easy testing, swappable storage backends

### Command Pattern
Rich operation contexts with built-in validation.

```python
@dataclass
class UpdatePlaylistCommand:
    playlist_id: str
    tracks: list[Track]
    operation_type: OperationType
    conflict_resolution: ConflictStrategy
    
    def validate(self) -> None:
        # Validation logic
```

**Benefits**: Clear operation boundaries, validation encapsulation, audit trails

### Strategy Pattern
Pluggable algorithms for flexible behavior.

```python
class TrackMatchingStrategy(Protocol):
    async def match_tracks(self, tracks: list[Track]) -> list[MatchResult]:
        ...

class SpotifyTrackMatcher:
    async def match_tracks(self, tracks: list[Track]) -> list[MatchResult]:
        # Spotify-specific matching logic
```

**Benefits**: Algorithmic flexibility, easy testing, service extensibility

### Workflow Pattern
Declarative transformation pipelines.

```python
# JSON workflow definition
{
  "tasks": [
    {"type": "source.spotify_playlist", "config": {"playlist_id": "..."}},
    {"type": "enricher.lastfm", "upstream": ["source"]},
    {"type": "sorter.by_metric", "config": {"metric": "play_count"}, "upstream": ["enricher"]}
  ]
}
```

**Benefits**: Composable operations, visual workflow building, non-technical configuration

## Technology Stack

### Core Technology Decisions

#### Python 3.13+
**Why**: Pattern matching, enhanced typing, performance improvements
**Usage**: Modern language features throughout codebase
**Benefits**: Better type safety, cleaner code, future-proofing

#### SQLite + SQLAlchemy 2.0
**Why**: Zero configuration, atomic transactions, rich relationships
**Usage**: Local database with async ORM patterns and specialized session management
**Benefits**: No server setup, data integrity, complex queries, concurrent operation support

#### Prefect (Workflow Engine)
**Why**: Robust execution, minimal overhead, progress tracking
**Usage**: Workflow orchestration with embedded mode
**Benefits**: Retry logic, error handling, real-time feedback

#### Typer + Rich (CLI)
**Why**: Type-safe CLI with beautiful output
**Usage**: Command-line interface with rich formatting
**Benefits**: Auto-completion, validation, professional UX

#### attrs (Domain Models)
**Why**: Immutable objects with minimal boilerplate
**Usage**: Domain entities and value objects
**Benefits**: Immutability, type safety, clean constructors

### Supporting Technologies

| Technology | Purpose | Rationale |
|------------|---------|-----------|
| **spotipy** | Spotify API integration | OAuth handling, rate limiting, well-maintained |
| **pylast** | Last.fm API integration | Comprehensive API coverage, stable interface |
| **musicbrainzngs** | MusicBrainz integration | Official client, proper rate limiting |
| **httpx** | HTTP client | Async-first, modern API, excellent performance |
| **backoff** | Retry logic | Declarative retry patterns, exponential backoff |
| **rapidfuzz** | String matching | High-performance fuzzy matching for track resolution |
| **toolz** | Functional utilities | Functional composition, efficient data processing |
| **loguru** | Logging | Context-aware logging, minimal configuration |

## Core System Components

### Track Resolution Engine

**Challenge**: Music services use inconsistent track identifiers
**Solution**: Multi-stage resolution with confidence scoring

```
Stage 1: Deterministic ID Matching (Spotify ID → ISRC → MusicBrainz ID)
Stage 2: Metadata Similarity Matching (Artist/Title fuzzy matching)
Stage 3: Graceful Degradation (Preserve all data, even unmatched)
```

**Benefits**: 
- 90% exact match rate with deterministic IDs
- Handles real-world data inconsistencies
- Preserves complete data for manual review

### Playlist Transformation System

**Challenge**: Static playlist management lacks sophisticated operations
**Solution**: Declarative workflow system with composable nodes

```
Source → Enricher → Filter → Sorter → Selector → Destination
```

**Node Categories**:
- **Sources**: Spotify playlists, albums, user libraries
- **Enrichers**: Last.fm play counts, MusicBrainz metadata
- **Filters**: Release date, play count, artist exclusions
- **Sorters**: Any metric, multiple criteria
- **Selectors**: First/last N, random sampling
- **Destinations**: Spotify playlist creation/updates

### Differential Playlist Updates

**Challenge**: Naive playlist replacement loses metadata and is inefficient
**Solution**: Intelligent differential algorithm

```
Calculate: Minimal add/remove/reorder operations
Preserve: Existing track order where possible
Handle: Concurrent external changes through conflict resolution
Optimize: API usage through batching and sequencing
```

**Benefits**:
- Preserves Spotify track addition timestamps
- Reduces API calls by 60-80%
- Handles external playlist changes gracefully
- Provides dry-run capability for preview

### Cross-Service Synchronization

**Challenge**: Services don't communicate with each other
**Solution**: Narada as intelligent intermediary

```
Service A → Narada (Resolution) → Service B
```

**Synchronization Types**:
- **Bidirectional Likes**: Spotify ↔ Last.fm through intelligent matching
- **Play History Import**: Spotify GDPR exports with enhanced resolution
- **Playlist Backup**: Local storage with restoration capability

## Data Architecture

### Entity Resolution Model

```
tracks (canonical) ↔ track_mappings ↔ connector_tracks (service-specific)
```

**Benefits**:
- Complete service metadata preservation
- Many-to-many track relationships
- Confidence scoring for match quality
- Independent service updates

### Temporal Data Design

- **Immutable Events**: Play history, sync operations
- **Time-Series Metrics**: Popularity, play counts
- **Checkpoint System**: Incremental sync state

**Benefits**: 
- Complete audit trail
- Efficient incremental operations
- Historical analysis capability

### Soft Delete Pattern

All entities support soft deletion with `is_deleted` flag and `deleted_at` timestamp.

**Benefits**:
- Maintains referential integrity
- Enables data recovery
- Supports audit requirements

## Database-First Workflow Architecture

### Critical Design Principle: Database-Centric Operations

**All workflow operations work exclusively on database tracks (`tracks` table), never directly on external connector data.**

This architectural constraint ensures system consistency and enables sophisticated cross-service operations that would be impossible with external-only data.

### Database Schema Relationships

```
External Playlists → Database Persistence → Workflow Operations

┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ Spotify         │    │ Database        │    │ Workflows       │
│ Playlist        │───▶│ Persistence     │───▶│ (Enrichment,    │
│                 │    │                 │    │  Sorting, etc.) │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### Core Database Tables

#### Primary Track Storage
- **`tracks`** - Internal canonical track representations (what workflows operate on)
- **`track_metrics`** - Metrics storage linked to internal tracks by `track_id`
- **`playlists`** - Internal playlist representations

#### Connector Integration
- **`connector_tracks`** - External service track representations
- **`track_mappings`** - Links internal tracks to external tracks (many-to-one)
- **`connector_playlists`** - External service playlist representations

### Mandatory Database Persistence Flow

#### 1. Source Node Responsibility
Source nodes (e.g., `spotify_playlist_source`) must:
- Fetch external playlist data
- Convert to domain entities (without database IDs)
- **Call `SavePlaylistUseCase` to persist to database**
- Return tracks with populated database IDs

#### 2. Track Upsert Strategy
The `TrackUpsertEnrichmentStrategy` ensures database consistency:
```python
# Repository handles upsert automatically via connector ID
saved_track = await self.track_repos.core.save_track(track)
# Returns track with database ID populated
```

#### 3. Workflow Operations
All downstream operations (enrichment, sorting, filtering) work with database tracks:
- **Input**: Tracks with `track.id != None`
- **Metrics**: Stored in `track_metrics` table by `track_id`
- **Enrichment**: Uses database track IDs for identity resolution

### Critical Developer Safeguards

#### Database ID Requirements
```python
# ✅ Correct: Tracks have database IDs
for track in tracklist.tracks:
    assert track.id is not None, "Track must have database ID"
```

#### Error Detection
Common failure pattern - tracks without database IDs:
```python
# ❌ Broken: Enrichment fails silently
if not tracks_with_ids:
    logger.warning("No tracks with database IDs - enrichment skipped")
    return {}
```

#### Source Node Pattern
```python
# ✅ Correct source node implementation
async def external_playlist_source(context, config):
    # 1. Fetch external playlist
    external_tracks = await connector.get_playlist(playlist_id)
    
    # 2. Convert to domain entities
    domain_tracks = [convert_to_domain(track) for track in external_tracks]
    
    # 3. MANDATORY: Persist to database
    save_command = SavePlaylistCommand(
        tracklist=TrackList(tracks=domain_tracks),
        enrichment_config=EnrichmentConfig(enabled=True),
        persistence_options=PersistenceOptions(operation_type="create_internal")
    )
    result = await SavePlaylistUseCase().execute(save_command)
    
    # 4. Return tracks with database IDs
    return {"tracklist": TrackList(tracks=result.enriched_tracks)}
```

### Data Consistency Benefits

#### 1. Cross-Service Operations
- Sort Spotify playlist by Last.fm play counts
- Sync likes between services through track matching
- Build sophisticated filters using cross-service data

#### 2. Reliable Enrichment
- Enrichment services require database track IDs
- Metrics stored with consistent track references
- Caching and freshness work with stable track identities

#### 3. Audit and History
- Complete operation history linked to database tracks
- Temporal data analysis across services
- Reliable backup and restoration

### Common Anti-Patterns to Avoid

#### ❌ Operating on External Data Directly
```python
# Wrong: Working with connector tracks directly
for spotify_track in spotify_playlist.tracks:
    # This breaks cross-service operations
    metric = lastfm.get_playcount(spotify_track.id)
```

#### ❌ Skipping Database Persistence
```python
# Wrong: Bypassing database persistence
return {"tracklist": TrackList(tracks=external_tracks)}
# These tracks have no database IDs!
```

#### ❌ Missing ID Validation
```python
# Wrong: No validation of database IDs
async def enrichment_step(tracklist):
    # Silently fails if tracks lack database IDs
    return await enrich_tracks(tracklist.tracks)
```

### Architecture Validation

To ensure architectural compliance:

1. **All tracks entering workflows must have database IDs**
2. **Source nodes must call `SavePlaylistUseCase`**
3. **Enrichment and metrics operations require database tracks**
4. **Cross-service operations work through database mappings**

This database-first approach is fundamental to Narada's ability to provide unified operations across music services while maintaining data consistency and enabling sophisticated cross-service workflows.

## Database Session Management Architecture

Narada implements a sophisticated session management strategy to handle SQLite's concurrency limitations while maintaining Clean Architecture principles and preventing database locks.

### Session Management Patterns

#### 1. Workflow-Scoped Sessions
**Pattern**: Single shared session per workflow execution
**Implementation**: `SharedSessionProvider` in `prefect.py`
**Usage**: All Prefect workflow tasks share one session to prevent concurrent write conflicts

```python
# Create a single shared session for the entire workflow execution
async with get_session() as shared_session:
    # Create shared session provider that wraps the session
    shared_session_provider = SharedSessionProvider(shared_session)
    
    # All workflow tasks use the same session
    context = {
        "session_provider": shared_session_provider,
        "shared_session": shared_session,  
    }
```

**Benefits**: Eliminates SQLite "database is locked" errors, ensures ACID properties across workflow operations, simplifies transaction management.

#### 2. Session-Per-Operation Pattern
**Pattern**: Fresh session for each discrete operation
**Implementation**: `DatabaseProgressContext.run_with_repositories()`
**Usage**: CLI operations and use cases that don't run within workflows

```python
async with DatabaseProgressContext(...) as progress:
    # Each operation gets its own short-lived session
    async def _import_operation(repositories: TrackRepositories) -> OperationResult:
        # Session created and closed automatically
        return await service.import_tracks(...)
    
    return await progress.run_with_repositories(_import_operation)
```

**Benefits**: Prevents long-held sessions, follows SQLAlchemy best practices, maintains Clean Architecture boundaries.

#### 3. Isolated Sessions for Metrics
**Pattern**: Specialized sessions for operations needing isolation
**Implementation**: `get_isolated_session()` 
**Usage**: Metrics operations that may conflict with main operations

```python
async with get_isolated_session() as session:
    # Optimized session settings for metrics operations
    # - autoflush=False to avoid implicit I/O
    # - isolated transaction boundaries
```

**Benefits**: Prevents metrics operations from interfering with main workflows, optimized for specific use cases.

### SQLite Configuration

**Connection Pooling**: Uses `NullPool` for SQLite to create/close connections on demand, eliminating pooling-related locks.

**Pragmas Applied**:
- `journal_mode=WAL`: Write-ahead logging for concurrent read access
- `busy_timeout=30000`: 30-second timeout for lock conflicts
- `synchronous=NORMAL`: Balanced safety/performance
- `foreign_keys=ON`: Enforce referential integrity

**Event Listeners**: Automatically apply pragmas on each connection creation to ensure consistent database behavior.

### Anti-Patterns to Avoid

❌ **Multiple Concurrent Sessions in Workflows**: Creates SQLite lock conflicts
❌ **Long-Held Sessions**: Blocks other operations unnecessarily  
❌ **Direct Session Creation**: Bypasses configured pragmas and pooling strategy
❌ **Session Sharing Across Components**: Violates Clean Architecture boundaries

✅ **Use Workflow-Scoped Sessions**: For Prefect workflows
✅ **Use Session-Per-Operation**: For CLI and use case operations
✅ **Use Context Managers**: Ensure proper session lifecycle management
✅ **Follow Injection Patterns**: Maintain Clean Architecture compliance

## Development Philosophy

### Ruthlessly DRY
Single-maintainer codebase demands zero redundancy. One implementation per concept, reused across contexts.

### Batch-First Design
Design for N items, single operations are degenerate cases. This scales naturally and reduces API overhead.

### Immutable Domain
Pure transformations without side effects. Easier to reason about, test, and debug.

### Framework-First
Leverage existing tools (Typer, Rich, Prefect) rather than building custom solutions. Focus development effort on unique business logic.

### Progressive Enhancement
Start with simple implementations, add sophistication incrementally. Avoid over-engineering for hypothetical future needs.

## Architectural Benefits

### Current Capabilities
- **Smart Playlist Operations**: Cross-service data transformations
- **Bidirectional Synchronization**: Intelligent track matching between services
- **Comprehensive Data Ownership**: Complete play history and metadata control
- **Sophisticated Updates**: Differential playlist operations with conflict resolution

### Future Extensibility
- **Web Interface**: FastAPI backend with React frontend using existing use cases
- **Additional Services**: Apple Music, YouTube Music integration using established patterns
- **Advanced Analytics**: Machine learning on comprehensive listening data
- **Collaborative Features**: Multi-user support with existing architecture

### Technical Scalability
- **Database**: SQLite handles millions of tracks efficiently
- **API Efficiency**: Batch operations and caching minimize external calls
- **Memory Usage**: Streaming operations and lazy loading for large datasets
- **Performance**: Async-first design enables concurrent operations

## Security Considerations

### Authentication
- **OAuth 2.0**: Secure token-based authentication with automatic refresh
- **API Keys**: Secure storage and rotation for service credentials
- **Local Storage**: Encrypted storage for sensitive configuration

### Data Privacy
- **Local First**: All data stored locally, no external data transmission
- **Consent**: Explicit user consent for all data operations
- **Minimal Data**: Only necessary data collected and stored

### Error Handling
- **Graceful Degradation**: Partial failures don't break entire operations
- **Retry Logic**: Exponential backoff for transient failures
- **Validation**: Input validation at system boundaries

## Monitoring and Observability

### Logging Strategy
- **Structured Logging**: JSON format with consistent fields
- **Context Propagation**: Track operations across system boundaries
- **Performance Metrics**: Timing and throughput for optimization

### Progress Tracking
- **Real-time Feedback**: Progress bars and status updates
- **Operation Metrics**: Success/failure rates, timing data
- **User Feedback**: Clear error messages with suggested actions

### Health Monitoring
- **Service Status**: Connection health for external services
- **Data Quality**: Validation and consistency checks
- **Performance**: Query performance and resource usage

## Testing Architecture

### Domain Testing
- **Pure Unit Tests**: No external dependencies, fast execution
- **Property-Based Testing**: Algorithmic correctness validation
- **Example**: Track matching confidence calculations

### Application Testing
- **Use Case Testing**: Business logic validation with mocked dependencies
- **Integration Testing**: Component interaction verification
- **Example**: Playlist import workflows

### Infrastructure Testing
- **API Integration**: Real external service testing
- **Database Testing**: Repository implementation validation
- **Example**: Spotify API error handling

## Deployment Architecture

### Local Development
- **Poetry**: Dependency management and virtual environments
- **Pre-commit**: Automated code quality checks
- **SQLite**: Zero-configuration database

### Production Deployment
- **Single Binary**: Self-contained executable
- **Configuration**: Environment-based configuration
- **Data**: Portable SQLite database

### Future Deployment Options
- **Docker**: Containerized deployment for consistency
- **Cloud**: FastAPI service deployment for web interface
- **Desktop**: Native app packaging for broader distribution

## Migration and Evolution

### Backward Compatibility
- **Database Migrations**: Alembic for schema evolution
- **API Versioning**: Maintain compatibility during changes
- **Configuration**: Graceful handling of configuration changes

### Technology Evolution
- **Modular Design**: Easy technology replacement
- **Interface Abstraction**: Clean boundaries for technology changes
- **Testing**: Comprehensive test coverage for safe refactoring

### Future Architecture
- **Microservices**: Clean Architecture enables service decomposition
- **Event-Driven**: Natural evolution from current command patterns
- **Distributed**: Workflow engine supports distributed execution

This architecture provides a solid foundation for current capabilities while enabling future growth and evolution without fundamental rewrites.

## Related Documentation

- **[DEVELOPMENT.md](DEVELOPMENT.md)** - Developer onboarding and contribution guide
- **[DATABASE.md](DATABASE.md)** - Database schema and design reference
- **[API.md](API.md)** - Complete CLI command reference
- **[workflow_guide.md](workflow_guide.md)** - Workflow system documentation
- **[likes_sync_guide.md](likes_sync_guide.md)** - Likes synchronization between Spotify and Last.fm
- **[BACKLOG.md](../BACKLOG.md)** - Project roadmap and planned features
- **[CLAUDE.md](../CLAUDE.md)** - Development commands and style guide