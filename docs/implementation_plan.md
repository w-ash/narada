# Narada Implementation Plan

## Project Goals
- Create a music metadata hub integrating Spotify, Last.fm, and MusicBrainz
- Implement with **less than 2,000 lines of code** total
- Focus on clean architecture and reusable components
- Leverage Python 3.13+ features for concise, robust code
- Follow domain-driven design principles

## Use Case 1A: Sort Spotify Playlist by Last.fm Play Count

### Architecture Vision

We're building Use Case 1A (sort Spotify playlist by Last.fm play count) as the foundation for a larger transformation pipeline architecture. This requires thinking beyond the immediate implementation to create composable, reusable components that will power future use cases with minimal code expansion.

### System Overview
This feature will:
1. Fetch a user's Spotify playlist
2. Get play counts from Last.fm for each track
3. Sort tracks by personal play count
4. Create a new sorted playlist (or update existing)

### Core Design Principles

1. **Pipeline Architecture** - Leverage functional transformations via composable operations
2. **Separation of Concerns** - Entity resolution separate from playlist operations
3. **Progressive Enhancement** - Start with direct path, add resolution sophistication incrementally
4. **Data Caching** - Minimize API calls through intelligent local storage
5. **Functional Core** - Pure transformations with side effects at boundaries

## Implementation Pran

### Implementation Steps Overview

1. [x] **Core Config & Database Setup** - SQLAlchemy models for persistence
2. [x] **Domain Models** - Models for core domain entities
3. [ ] **Connector Adapters** - Thin wrappers for external APIs
4. [ ] **Entity Resolution** - Cross-connector entity matching
5. [ ] **Repository Layer** - Persistence abstraction with caching
6. [ ] **Transformation Pipeline** - Composable operations using toolz
7. [ ] **Playlist Operations** - Reusable transformations for playlists
8. [ ] **Workflow Orchestration** - End-to-end operation composition
9. [ ] **CLI Interface** - User interaction layer

### Step 1: Core Config & Database Setup

#### Status
✅ Complete

#### Files
- `narada/config.py` - Environment & logging setup
- `narada/data/database.py` - SQLAlchemy async engine configuration & Database schema models

#### Database Schema Design

Core tables mirror patterns from leading streaming platforms:

```python
# tracks - Central canonical entity
class Track(Base):
    __tablename__ = "tracks"
    
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    artists = Column(JSON, nullable=False)  # JSON array of artist names
    album = Column(String)
    duration_ms = Column(Integer)
    release_date = Column(Date)
    isrc = Column(String, index=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

```

#### Implementation Tasks

1. Set up SQLAlchemy 2.0 async engine with connection pooling
2. Create base model classes for typed access patterns
3. Implement models with appropriate indices
4. Create migration setup with Alembic

##### Testing Approach

###### Manual Test Script: 
`narada/data/test_database.py`

```python
async def test_database_connection():
    """Test database connectivity and model creation."""
    # Test connection to the database
    # Create tables
    # Insert sample records
    # Verify retrieval with basic queries
```

##### Verification Criteria:
- Database connection established
- Tables created with proper schema
- Basic CRUD operations work (verified visually)
- Foreign key constraints enforced
- Indices created correctly

##### Test Command:
```bash
python -m narada.data.test_database
```



### Step 2: Domain Models
#### Status
🔄 In Progress

#### Files
- `narada/core/models.py`

#### Key Model Structure

##### Model Categories

- **Domain Entities (attrs)**
    - Pure business objects
    - Pipeline processing units
    - Immutable by design

##### Models to Create

###### Domain Entities

- **Track**  
    Purpose: Core music entity representation Justification: Central to all use cases, handles basic metadata
- **Playlist**  
    Purpose: Ordered track collection Justification: Required for UC1, UC3; handles ordering and metadata
- **ConnectorMapping**  
    Purpose: Cross-connector entity resolution Justification: Critical for all use cases; separating this from Track keeps our resolution logic clean
- **PlayCount**  
    Purpose: Temporal play count data Justification: UC1 requires efficient play count queries; separating from Track improves write patterns
- **PlaylistOperation**  
    Purpose: Transformation definition Justification: Enables UC1A/B transformation pipeline while maintaining composability

#### Test Command

`python -m narada.core.test_entities`

### Step 3: Connector Integration Layer

#### Architecture Vision

Modern streaming platforms succeed by maintaining clean boundaries between external connectors and domain logic. Our architecture leverages battle-tested libraries while establishing clear conversion points:

```
External API → Library → Converter → Domain Model
```

#### Libraries

- **spotipy**: Spotify Web API client
- **pylast**: Last.fm integration
- **musicbrainzngs**: ISRC→MBID resolution
- **backoff**: Retry handling
- **httpx**: Modern async HTTP client

#### Implementation Structure

```
narada/
└── integrations/
    ├── spotify.py       # Spotify integration & conversion
    ├── lastfm.py        # Last.fm integration & conversion
    ├── musicbrainz.py   # Resolution connector
    └── integrations.py  # Shared integration utilities
```

#### Key Components

##### Spotify Integration
```python
# ~50 LOC focused on:
- OAuth flow management
- Playlist operation mapping
- Track conversion to domain model
```

##### Last.fm Integration
```python
# ~50 LOC focused on:
- API key authentication
- Play count retrieval
- Track matching
```

##### MusicBrainz Integration
```python
# ~30 LOC focused on:
- Batch ISRC lookup
- Response caching
- Error handling
```

#### Converter Functions
Each connector integration needs lean converter functions that transform external data into our domain models. This pattern has proven highly effective in early-stage streaming platforms:

1. **Spotify Converters**
   ```python
   # ~15 LOC
   def spotify_to_track(data: dict) -> Track:
       """Transform Spotify track data to domain model."""
   ```

2. **Last.fm Converters**
   ```python
   # ~15 LOC
   def lastfm_to_track(data: dict) -> Track:
       """Transform Last.fm track data to domain model."""
   ```

3. **MusicBrainz Converters**
   ```python
   # ~10 LOC
   def extract_mbid(data: dict) -> str:
       """Extract MBID from MusicBrainz response."""
   ```

#### Testing Strategy

##### Test Files

```
tests/integrations/
├── test_spotify.py
├── test_lastfm.py
├── test_musicbrainz.py
└── fixtures/          # Sample API responses
```

##### Verification Criteria
- Auth flows complete
- Converters handle edge cases
- Resolution pipeline works
- Resource cleanup succeeds

This architecture gives us professional connector integration while staying well within our LOC budget. The key insight: Let the proven libraries do the heavy lifting while we focus on clean domain integration.

### Step 4: Entity Resolution

#### Purpose
Match tracks between connectors when direct IDs aren't available.

#### Components

**EntityResolver**
- `get_mbid_from_isrc(isrc)` - Check cache then query MusicBrainz
- `match_to_lastfm(track)` - Multi-tier resolution strategy

**Resolution Flow**
1. Try direct MBID lookup if available
2. Try ISRC → MBID → Last.fm
3. Fall back to artist/title search
4. Score match confidence

#### Strategy
- Cache all resolution results
- Use confidence scoring for uncertain matches
- Enable background resolution improvements

#### Test Command
`python -m narada.core.test_resolver`
- Test cached resolution paths
- Verify fallback to direct search works
- Confirm confidence scoring correctly identifies match quality
- Check rate limiting respects connector constraints

### Step 5: Repository Layer

#### Purpose
Provide persistence connectors with caching to reduce API calls.

#### Components

**TrackRepository**
- `save_track(track)` - Store with duplicate prevention
- `find_by_isrc(isrc)` - Lookup by identifier
- `update_play_count(track_id, username, count)` - Cache play count

**EntityMappingRepository**
- `save_mapping(isrc, mbid, confidence)` - Cache resolution
- `find_mapping(isrc)` - Get cached resolution

#### Strategy
- Use SQLAlchemy's async features
- Implement entity merging for partial updates
- Keep repositories focused on single entity types

#### Test Command
`python -m narada.data.test_repositories`
- Verify track storage with duplicate prevention works
- Test play count caching and retrieval
- Confirm entity mapping storage and lookup
- Check transaction integrity with error scenarios

### Step 6: Transformation Pipeline

#### Purpose
Create composable operations for playlist transformation.

#### Components

**Base Operations**
- `get_play_counts(playlist, username)` - Enhance tracks with play data
- `sort_by(playlist, key_func, reverse)` - Generic sorting
- `limit(playlist, count)` - Take first N tracks

**Composed Functions**
- `sort_by_plays` - Combine resolution, play counts, and sorting
- `create_pipeline(*operations)` - Toolz-based composition

#### Strategy
- Design for composition over inheritance
- Prefer pure functions with minimal side effects
- Create reusable operations for future use cases

#### Test Command
`python -m narada.core.test_pipeline`
- Test individual operations in isolation
- Verify composition creates expected transformation sequence
- Ensure pipeline execution maintains immutability
- Confirm error handling propagates correctly through pipeline

### Step 7: Playlist Operations

#### Purpose
Build reusable, composable transformations specifically for playlist manipulation.

#### Components

**Core Operations**
- `sort_by_plays(playlist, username)` - Primary sorting operation
- `filter_by_plays(playlist, min_plays, max_plays)` - Play count filtering
- `deduplicate_playlist(playlist)` - Remove duplicate tracks

**Utility Operations**
- `annotate_playlist(playlist, annotation_func)` - Add metadata to tracks 
- `merge_playlists(playlists)` - Combine multiple playlists

#### Strategy
- Build on pipeline architecture from Step 6
- Design for reusability across use cases
- Use partial application for configuration

#### Test Command
`python -m narada.playlists.test_operations`
- Test each operation with sample playlist data
- Verify sort operations maintain correct ordering
- Confirm playlist transformations preserve metadata
- Test edge cases like empty playlists and duplicates

### Step 8: Workflow Orchestration

#### Purpose
Coordinate end-to-end flows that combine multiple operations.

#### Components

**Orchestrators**
- `execute_sort_flow(source_id, target_name, username)` - Main UC1A flow
- `handle_errors(workflow_func)` - Error handling decorator

**Flow Structure**
1. Input validation
2. Connector authentication
3. Data retrieval
4. Transformation execution
5. Result persistence
6. Cleanup/logging

#### Strategy
- Keep orchestration separate from operations
- Use dependency injection for components
- Implement clean error handling and logging

#### Test Command
`python -m narada.playlists.test_flows`
- Test full workflow with mocked components
- Verify error handling with simulated failures
- Confirm expected side effects occur
- Check logging and diagnostics

### Step 9: CLI Interface

#### Purpose
Provide a clean, user-friendly command interface.

#### Components

**Main App**
- Entry point with command grouping
- Global options like verbosity

**Commands**
- `sort-playlist` - Primary UC1A command
- `setup` - Initialize configuration
- `auth` - Handle authentication

**Options Structure**
```
sort-playlist
  --source-id TEXT          [required]
  --target-name TEXT        [required]
  --username TEXT           [required]
  --create-new / --update   [default: create-new]
```

#### Strategy
- Use Typer for modern CLI capabilities
- Implement rich output with status indicators
- Provide helpful error messages
- Include examples in help text

#### Test Command
`python -m narada test-cli`
- Verify command parsing works correctly
- Test help output contains necessary information
- Confirm error handling surfaces useful messages
- Check exit codes reflect operation status

## Technical Decisions

### Data Flow Architecture
1. **User Input** → CLI parameters capture playlist ID and options
2. **Data Retrieval** → Fetch Spotify playlist and convert to domain model
3. **Enrichment** → Get Last.fm play counts for each track
4. **Data Storage** → Save tracks and play counts to local database
5. **Transformation** → Sort playlist tracks by play count
6. **Output** → Create new Spotify playlist with sorted tracks

### Key Technical Choices
- **Python Version:** 3.13+ (using pattern matching, better typing)
- **Database:** SQLite with SQLAlchemy 2.0 (async interface)
- **HTTP Client:** `httpx` for modern async requests
- **CLI Framework:** `typer` for clean command interfaces
- **Models:** Pydantic v2 for domain models, SQLAlchemy for persistence
- **Error Handling:** Exception groups for connector integration issues
- **Logging:** Loguru for structured logs with context
- **API Clients:** `spotipy` for Spotify, `pylast` for Last.fm

### Development Strategy
1. Start with minimal database structure to enable caching/persistence
2. Implement connector adapters one at a time with manual testing
3. Create high-level domain operations that orchestrate connectors
4. Connect with simple CLI interface
5. Add comprehensive error handling and recovery

### Testing Approach
- Unit tests for core domain logic
- Integration tests with mocked external connectors
- Manual testing for full end-to-end flows during development
- Pytest fixtures for database setup and teardown
