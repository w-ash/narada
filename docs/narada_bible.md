	# Narada Project Bible

## Project Vision

Narada is a personal music metadata hub that integrates Spotify, Last.fm, and MusicBrainz to give you ownership of your listening data while enabling powerful cross-connector operations. The system maintains local representations of your music entities, enabling features that no single connector provides.

## Core Principles

1. **Lean Implementation** - Target under 2,000 LOC for the entire project
2. **Data Ownership** - Local backups of all playlists and interactions
3. **Domain-Driven Design** - Organize by music concepts, not technical patterns
4. **Progressive Delivery** - Build incrementally with testable steps

##  Technology Stack

### Core Dependencies

| Component             | Package        | Version | Purpose                                                         |
| --------------------- | -------------- | ------- | --------------------------------------------------------------- |
| Runtime               | Python         | ≥3.13.0 | Modern language features, pattern matching, improved type hints |
| Database Engine       | SQLite         | ≥3.49.1 | Zero-config, embedded database with async support               |
| Database ORM          | SQLAlchemy     | ≥2.0.38 | Type-safe query building, async support                         |
| Database Migrations   | Alembic        | ≥1.14.1 | Schema version control and migrations                           |
| HTTP Client           | httpx          | ≥0.28.1 | Modern async-first HTTP client                                  |
| Spotify Interface     | spotipy        | ≥2.25.0 | OAuth handling, Spotify Web API client                          |
| Last.fm Interface     | pylast         | ≥5.3.0  | Last.fm API integration                                         |
| MusicBrainz Interface | musicbrainzngs | ≥0.7.1  | MusicBrainz metadata lookups                                    |
| CLI Framework         | typer          | ≥0.15.1 | Type-safe CLI with minimal boilerplate                          |
| Domain Models         | attrs          | ≥25.1.0 | Efficient immutable models                                      |
| Functional Tools      | toolz          | ≥1.0.0  | Functional composition utilities                                |
| Logging               | loguru         | ≥0.7.3  | Structured logging with minimal setup                           |
| Error Handling        | backoff        | ≥2.2.1  | Declarative retry mechanisms                                    |
| Environment           | python-dotenv  | ≥1.0.0  | Configuration management                                        |
| Terminal UI           | rich           | ≥13.7.0 | Rich terminal output formatting                                 |

### Development Tools

| Tool          | Package        | Version | Purpose                           |
| ------------- | -------------- | ------- | --------------------------------- |
| Build System  | Poetry         | ≥2.1.0  | Dependency and build management   |
| Linter        | ruff           | ≥0.9.7  | Fast, comprehensive Python linter |
| Formatter     | black          | ≥25.1.0 | Opinionated code formatting       |
| Testing       | pytest         | ≥8.3.4  | Test framework and runner         |
| Async Testing | pytest-asyncio | ≥0.25.3 | Async test support                |
| Coverage      | pytest-cov     | ≥6.0.0  | Test coverage reporting           |
| Git Hooks     | pre-commit     | ≥4.1.0  | Automated pre-commit checks       |

### Key Architectural Patterns

| Pattern | Implementation | Benefit |
|---------|---------------|---------|
| Pipeline Architecture | toolz.compose | Enables unlimited playlist transformations within fixed LOC budget |
| Connector Adapters | Thin API wrappers | Isolates external dependencies for easier testing and replacement |
| Repository Pattern | SQLAlchemy async sessions | Centralizes data access with consistent error handling |
| Entity Resolution | Multi-tier matching | Balances accuracy with performance through progressive resolution |
| Command Pattern | Typer CLI | Separates UI from business logic for maximum reusability |

### Technology Selection Criteria

1. **Development Velocity** - Prioritize technologies that accelerate initial development
2. **Maintenance Burden** - Prefer tools with lower long-term maintenance costs
3. **Ecosystem Stability** - Choose mature libraries with active maintenance
4. **Code Efficiency** - Select technologies that minimize boilerplate
5. **Future Adaptability** - Ensure architecture can evolve without wholesale rewrites                   

## Architecture

### Core Concepts

1. **Entity Resolution** - Map tracks across connectors with confidence scoring
2. **Transformation Pipeline** - Composable operations on music collections
3. **Event-Based Playlist Model** - Track history of playlist changes
4. **Caching Layer** - Minimize API calls through local storage

### Entity Resolution Strategy

To effectively match tracks across connectors, Narada employs a multi-tier resolution strategy:

1. **Primary Path**: Spotify (ISRC) → MusicBrainz (ISRC→MBID) → Last.fm (MBID)
2. **Fallback Path**: Direct artist/title matching when deterministic IDs unavailable
3. **Confidence Scoring**: Each match is assigned a confidence level (0-100)
4. **Progressive Resolution**: Background resolution of low-confidence matches

This approach balances accuracy with performance while respecting API rate limits.

### Model Separation Pattern

Modern streaming architectures have evolved away from rigid multi-model separation in favor of more pragmatic patterns that reduce complexity while maintaining clean boundaries. Here's the strategic approach for Narada:

#### Core Model Architecture

Two primary model categories shape our system:

1. **Domain Models (attrs)**
   - Pure business logic containers
   - Immutable data structures
   - Connector-agnostic design
   - Validation at construction

2. **Database Models (SQLAlchemy)**
   - Persistence layer
   - Relationship management
   - Query optimization
   - Transaction handling

#### Strategic Pattern

Instead of traditional connector-specific models (like Pydantic schemas), we use lightweight converter functions at connector boundaries:

```
External API → Converter Function → Domain Model → Database Model
```

This pattern, similar to early Spotify's architecture, gives us:
- Minimal code surface area
- Clear transformation points
- Easy debugging and modification
- Direct error visibility

At our scale, sophisticated multi-model architectures create more complexity than they solve. A streamlined approach delivers the benefits of clean architecture without the maintenance burden of excessive abstraction.

### Database Lifecycle

1. **One-time Operations**:
   - Schema definition through SQLAlchemy models
   - Initial database creation and migrations
   - Configuration of connection parameters

2. **Runtime Operations**:
   - Connection pooling and session management
   - Transaction handling with automatic commit/rollback
   - Explicit session context management

### Directory Structure

```
narada/                      # Repository root
├── pyproject.toml           # Project dependencies and metadata
├── README.md                # Project documentation
├── narada/                  # Main package
│   ├── config.py            # Configuration and environment variables
│   ├── core/                # Domain core
│   │   ├── models.py        # Core entity models
│   │   ├── exceptions.py    # Domain-specific exceptions
│   │   └── matcher.py       # Entity resolution engine
│   ├── data/                 # Data persistence layer
│   │   ├── database.py      # Database connection and session management
│   │   ├── models.py        # SQLAlchemy database models
│   │   ├── track_repo.py    # Track repository implementation
│   │   └── playlist_repo.py # Playlist repository implementation
│   ├── integrations/        # External connector adapters
│   │   ├── integrations.py  # Spotify API integration
│   │   ├── spotify.py       # Spotify API integration
│   │   ├── lastfm.py        # Last.fm API integration 
│   │   └── musicbrainz.py   # MusicBrainz API integration
│   ├── sync/                # Sync operations
│   │   ├── likes.py         # Spotify likes to Last.fm
│   │   └── scrobbles.py     # Scrobble management
│   ├── playlists/           # Playlist operations
│   │   ├── transformers.py  # Playlist transformation pipeline
│   │   ├── filters.py       # Reusable playlist filters
│   │   └── operations.py    # Playlist management operations
│   ├── backup/              # Backup operations
│   │   ├── export.py        # Export functionality
│   │   └── import.py        # Import functionality
│   └── cli/                 # Command-line interface
│       ├── app.py           # CLI entry point
│       └── commands.py      # CLI command implementations
└── tests/                   # Test suite
```

# Database Model

## Core Entities

Our database design follows a focused schema pattern that prioritizes essential storage needs while maintaining flexibility for future expansion. Each entity maps to a core domain concept while avoiding unnecessary normalization that would increase query complexity.

- tracks
- play_counts
- track_mappings
- playlists
- playlist_mappings
- playlist_tracks

### Tracks Table

Central storage for music metadata with cross-connector identifiers.

```
+---------------+-------------+--------------------------------------+
| tracks        | Type        | Purpose                              |
+---------------+-------------+--------------------------------------+
| id            | Integer (PK)| Internal identifier                  |
| title         | String      | Track title                          |
| artists       | JSON        | List of artist names/IDs             |
| album         | String      | Album name                           |
| duration_ms   | Integer     | Duration in milliseconds             |
| release_date  | DateTime    | Release date when available          |
| spotify_id    | String (IDX)| Spotify track identifier             |
| isrc          | String (IDX)| International recording code         |
| lastfm_url    | String      | Last.fm track URL                    |
| created_at    | DateTime    | Record creation timestamp            |
| updated_at    | DateTime    | Last update timestamp                |
+---------------+-------------+--------------------------------------+
```

### Play Counts Table

Caches global and user-specific play count data from Last.fm.

```
+------------------+-------------+--------------------------------------+
| play_counts      | Type        | Purpose                              |
+------------------+-------------+--------------------------------------+
| id               | Integer (PK)| Internal identifier                  |
| track_id         | Integer (FK)| Reference to tracks table            |
| user_id          | String (IDX)| Last.fm username                     |
| play_count       | Integer     | Number of global plays               |
| user_play_count  | Integer     | Number of user plays                 |
| last_updated     | DateTime    | Cache timestamp                      |
+------------------+-------------+--------------------------------------+
```

### Track connector Mappings Table

#### Purpose

The Track connector Mappings table serves as our universal cross-connector integration layer, providing deterministic entity resolution across music platforms with confidence scoring and method tracking.

```
+------------------------+-------------+--------------------------------------+
| track_mappings         | Type        | Purpose                              |
+------------------------+-------------+--------------------------------------+
| id                     | Integer (PK)| Internal identifier                  |
| track_id               | Integer (FK)| Reference to canonical track         |
| connector_name         | String      | Platform identifier (spotify, lastfm)|
| connector_id           | String      | Platform-specific identifier         |
| match_method           | String      | Resolution method used               |
| confidence             | Integer     | Match confidence (0-100)             |
| last_verified          | DateTime    | Verification timestamp               |
| metadata               | JSON        | connector-specific auxiliary data    |
+------------------------+-------------+--------------------------------------+
```

#### Design Decisions

1. **connector-Agnostic Architecture**
   - Single table handles all connector integrations
   - Enables unlimited future connector expansion without schema changes
   - Consistent resolution interface across the application

2. **Resolution Method Tracking**
   - `match_method` explicitly documents how each match was determined
   - Common values: "direct" (connector origin), "isrc", "mbid", "artist_title", "fuzzy"
   - Enables selective reprocessing of lower-quality matches

3. **Confidence Scoring System** (Prototype)
   - Quantifies match quality on 0-100 scale
   - Primary matches (direct imports): 100
   - ISRC-based matches: 90-95
   - MBID-based matches: 80-85
   - Artist/title matches: 60-75
   - Fuzzy matches: 30-50

4. **Auxiliary Metadata**
   - JSON field stores connector-specific context that may aid future resolution
   - Examples: track duration, album context, release information
   - Eliminates need for connector-specific schema adjustments

#### Implementation Strategy

This model implements a directed graph of relationships between our canonical tracks and connector-specific entities. The primary workflow:

1. Track import creates canonical record with 100% confidence for source connector
2. Resolution engine attempts deterministic matching (ISRC→MBID chain)
3. Fallback to progressively less confident matching methods
4. Background processes attempt to improve match quality over time

#### Indexing Strategy

| Index | Type | Purpose |
|-------|------|---------|
| (track_id, connector_name) | Composite | Fast lookup for specific connector mappings |
| (connector_name, connector_id) | Composite | Reverse lookups and duplicate prevention |
| confidence | Single | Quality-based filtering and prioritization |

#### Usage Patterns

```python
# Canonical flow: Get Last.fm ID for track
async def get_lastfm_id(track_id):
    mapping = await find_mapping(track_id, "lastfm")
    if mapping and mapping.confidence >= CONFIDENCE_THRESHOLD:
        return mapping.connector_id
    
    # Fallback to resolution if no high-confidence mapping
    lastfm_id = await resolve_track(track_id, "lastfm")
    return lastfm_id
```

This model  simplifies cross-connector entity resolution by centralizing all mapping logic while providing fine-grained visibility into match quality. The design scales linearly with additional connectors.

### Playlists Table

Our source of truth for playlists.

```
+---------------+-------------+--------------------------------------+
| playlists     | Type        | Purpose                              |
+---------------+-------------+--------------------------------------+
| id            | Integer (PK)| Internal identifier                  |
| name          | String      | Playlist name                        |
| description   | Text        | Playlist description                 |
| track_count   | Integer     | Number of tracks                     |
| created_at    | DateTime    | Creation timestamp                   |
| updated_at    | DateTime    | Last update timestamp                |
+---------------+-------------+--------------------------------------+
```
#### Key Points

1. **Source of Truth**
   - Our playlists table is now connector-agnostic
   - Clean separation between our data and connector mappings
   - Follows same pattern as track resolution

2. **Minimal Schema**
   - Core tables remain simple
   - Sync state isolated to mappings table
   - Maintains under 2000 LOC target

3. **Future Ready**
   - Easy to add new connector integrations
   - No changes needed to core playlist structure
   - Consistent with our entity resolution pattern

### Playlist connector Mappings Table

Maps our playlists to external connector playlists.

```
+------------------------+-------------+--------------------------------------+
| playlist_mappings      | Type        | Purpose                              |
+------------------------+-------------+--------------------------------------+
| id                     | Integer (PK)| Internal identifier                  |
| playlist_id            | Integer (FK)| Reference to our playlist            |
| connector_name         | String      | connector name (spotify, apple, etc)   |
| connector_id           | String      | connector's playlist identifier        |
| last_synced           | DateTime    | Last successful sync                 |
+------------------------+-------------+--------------------------------------+
```


### Playlist Tracks Table

Maps the many-to-many relationship between playlists and tracks.

```
+-----------------+-------------+--------------------------------------+
| playlist_tracks | Type        | Purpose                              |
+-----------------+-------------+--------------------------------------+
| id              | Integer (PK)| Internal identifier                  |
| playlist_id     | Integer (FK)| Reference to playlists table         |
| track_id        | Integer (FK)| Reference to tracks table            |
| sort_key        | VARCHAR(32) | Lexicographical ordering key         |
| created_at      | DateTime    | Creation timestamp                   |
| updated_at      | DateTime    | Last update timestamp                |
+-----------------+-------------+--------------------------------------+
```

### Key Points

1. **Efficient Ordering**
   - `sort_key` uses lexicographical strings (a000 → z999)
   - Allows instant reordering without updating multiple rows
   - Space between values for future insertions

2. **Minimal Schema**
   - Removed sync-specific fields
   - Core focus on playlist structure
   - Under 2000 LOC friendly

3. **Future Extensibility**
   - Can add sync capability later if needed
   - Sort key pattern supports other ordering needs
   - No schema changes needed for most features

### Example Sort Keys
```
First track:    "a0000000"
Middle track:   "m0000000"
Last track:     "z0000000"
Between a and m: "g0000000"
```


## Design Decisions

1. **JSON for Artists**
   - Storing artists as JSON provides flexibility for varying artist data structures
   - Avoids complex joins while supporting multiple artists per track
   - Trade-off: Less query optimization for artist filtering

2. **Confidence Scoring**
   - Entity mappings include confidence scores to prioritize high-quality matches
   - Enables progressive enhancement of match quality over time
   - Provides transparency into match reliability

3. **Caching Strategy**
   - Play counts cached with timestamps to enable intelligent refresh policies
   - Entity mappings treated as semi-permanent with verification timestamps
   - Trade-off: Potential staleness vs API rate limits

4. **Position Tracking**
   - Playlist tracks store explicit position to preserve ordering
   - Enables position-based operations (move, swap, insert)
   - Provides history awareness for original vs. transformed playlists

## Indexing Strategy

| Table | Index | Type | Purpose | SQLAlchemy Implementation |
|-------|-------|------|---------|-------------------------|
| tracks | id | Primary | Primary key | `mapped_column(primary_key=True)` |
| tracks | spotify_id | Single | Fast lookup by Spotify ID | `mapped_column(index=True)` |
| tracks | isrc | Single | Fast lookup for entity resolution | `mapped_column(index=True)` |
| play_counts | id | Primary | Primary key | `mapped_column(primary_key=True)` |
| play_counts | (track_id, user_id) | Composite Unique | Enforce single count per track/user | `UniqueConstraint('track_id', 'user_id')` |
| track_mappings | id | Primary | Primary key | `mapped_column(primary_key=True)` |
| track_mappings | (track_id, connector_name) | Composite | Fast lookup for specific connector | `Index('ix_track_mappings_lookup', 'track_id', 'connector_name')` |
| track_mappings | (connector_name, connector_id) | Composite | Reverse lookups and duplicate prevention | `UniqueConstraint('connector_name', 'connector_id')` |
| playlists | id | Primary | Primary key | `mapped_column(primary_key=True)` |
| playlist_tracks | id | Primary | Primary key | `mapped_column(primary_key=True)` |
| playlist_tracks | (playlist_id, sort_key) | Composite | Ordered track retrieval | `Index('ix_playlist_tracks_order', 'playlist_id', 'sort_key')` |
| playlist_mappings | id | Primary | Primary key | `mapped_column(primary_key=True)` |
| playlist_mappings | (playlist_id, connector_name) | Composite Unique | Enforce single mapping per playlist/connector | `UniqueConstraint('playlist_id', 'connector_name')` |

### Index Design Principles

1. **Primary Keys**: Every table has an auto-incrementing integer primary key for consistent reference
2. **Foreign Keys**: All relationships use indexed foreign keys for efficient joins
3. **Composite Indices**: Used where multiple columns are frequently queried together
4. **Unique Constraints**: Prevent duplicate entries in mapping tables
5. **Ordering**: `sort_key` indexed with `playlist_id` for efficient ordered retrieval


## Migration Philosophy

The schema is designed for additive evolution rather than frequent structural changes:
- New features can be added via new tables rather than schema modifications
- Entity resolution quality can improve without schema changes
- Transformation capabilities expand through code, not data model

This approach keeps migrations simple while allowing the system to grow in capability without database restructuring.

## Connector Integration Strategy

Our three core integrations create a unified music metadata system that exceeds the capabilities of any single connector. Each integration serves a specific purpose in our pipeline architecture:

#### Spotify Integration

**Strategic Value**: Source of truth for track metadata and playlist structure.

**Key Capabilities**:
- Track metadata with consistent formatting
- ISRC identifiers for cross-connector matching
- Playlist CRUD operations
- OAuth-based user authentication

**Implementation Approach**: 
- Using `spotipy` client with transparent token refreshing
- Pydantic schemas validate Spotify API responses at boundary
- Batch operations for playlist modifications (up to 100 tracks per request)
- Backoff-enabled resilience for rate limit handling

#### Last.fm Integration

**Strategic Value**: Personal listening data not available in Spotify.

**Key Capabilities**:
- User-specific play counts
- MBID-based track lookups
- Artist/title search fallback
- Historical listening patterns

**Implementation Approach**:
- `pylast` client with intelligent caching
- Play count data cached with TTL strategy
- Pydantic validation ensures consistent response handling
- Tiered lookup approach (MBID → search)

#### MusicBrainz Integration

**Strategic Value**: Entity resolution bridge between connectors.

**Key Capabilities**:
- ISRC to MBID mapping
- Authoritative music metadata
- Relationship data between recordings/releases
- Open data model

**Implementation Approach**:
- `musicbrainzngs` with request batching (50-100 ISRCs per call)
- Permanent local caching of all resolution results
- Decorative rate limiting with `backoff` package
- Background processing for non-critical lookups

### Cross-Connector Resolution Strategy

Our cross-connector resolution flows through an efficient matching pipeline:

1. Spotify → Track with ISRC identification
2. MusicBrainz → Batch ISRC lookup for MBIDs
3. Last.fm → MBID-based play count retrieval
4. Fallback → Artist/title matching when identifiers unavailable

This approach provides:
- Maximum determinism where possible (reducing fuzzy match complexity)
- Optimal batching to minimize API calls
- Resilience through progressive fallbacks
- Confidence scoring for match quality assessment

### Technical Implementation

Our implementation minimizes API interactions through:

- **Boundary Validation**: Pydantic schemas enforce clean data at connector boundaries
- **Progressive Caching**: Tiered caching strategy aligned with data volatility
- **Batch Processing**: Aggregating requests to maximize throughput
- **Rate Management**: Intelligent backoff with connector-specific parameters
- **Error Recovery**: Consistent handling across connector boundaries

This approach yields a system that performs complex cross-connector operations while respecting API constraints and delivering responsive user experiences.

## Feature Roadmap

### Use Case 1: Smart Playlist Operations

#### 1A: Play Count Sorting
**Description**: Sort Spotify playlist by personal Last.fm play count  
**Architecture Flow**:
- Fetch playlist via Spotify API
- Resolve tracks to Last.fm entities
- Retrieve & cache play counts
- Apply sorting transformation
- Create/update playlist via Spotify API

#### 1B: Discovery Mix Generation
**Description**: Filter multiple playlists by recency/plays/blocks for discovery mix  
**Architecture Flow**:
- Batch fetch source playlists
- Apply composite filtering pipeline
- Deduplicate across sources
- Sort by configurable metrics
- Generate new playlist

### Use Case 2: Cross-Connector Likes Synchronization
**Description**: Sync Spotify likes to Last.fm loves  
**Architecture Flow**:
- Fetch liked tracks from Spotify
- Resolve entities through mapping layer
- Update Last.fm loved tracks
- Maintain sync state in mappings
- Track failures for retry

### Use Case 3: Playlist Backup & Restoration
**Description**: Export playlists to local storage for restoration  
**Architecture Flow**:
- Fetch complete playlist metadata
- Store structured JSON with all metadata
- Track mappings preserved for restoration
- Support incremental backup
- Restore to connector with validation

### Use Case 4: Historical Scrobble Backfill
**Description**: Backfill Last.fm scrobbles from Spotify history export  
**Architecture Flow**:
- Parse Spotify JSON history export
- Transform to normalized track entities
- Resolve Last.fm mappings in batch
- Queue scrobbles with timestamps
- Handle rate limits via batching
- Track progress for resume capability

## Development Workflow

1. Implementation begins with Use Case 1A (playlist sorting)
2. Each component is built with isolated testing
3. First build connector adapters, then core processing, then CLI interface
4. Run independent step validation before integration
5. Maintain strict LOC discipline - if code expands, refactor

## Implementation Patterns

### Connector Adapter Pattern
```python
async def get_auth_client():
    # Initialize and return authenticated connector client
    
async def perform_operation(parameters):
    # Execute operation through client abstraction
```

### Repository Pattern
```python
class EntityRepository:
    async def save(self, entity):
        # Persist entity to database
        
    async def get_by_id(self, id):
        # Retrieve entity from database
```

### Transformation Pipeline
```python
def create_pipeline(operations):
    """Create a processing pipeline from operations."""
    async def process(playlist):
        result = playlist
        for operation in operations:
            result = await operation(result)
        return result
    return process
```

### Domain-Database Mapping
```python
# Domain to database conversion
def to_db_model(domain_entity):
    return DBModel(
        # Map domain attributes to database fields
    )

# Database to domain conversion
def to_domain_entity(db_model):
    return DomainEntity(
        # Map database fields to domain attributes
    )
```

## Feature Roadmap

### Use Case 1: Smart Playlist Operations

#### 1A: Play Count Sorting
**Description**: Sort Spotify playlist by personal Last.fm play count
**Flow**: Fetch playlist → Get play counts → Sort → Create/update playlist

#### 1B: Discovery Mix Generation
**Description**: Filter multiple playlists by recency/plays/blocks and create discovery mix
**Flow**: Fetch source playlists → Apply filters → Sort → Create playlist


### Use Case 2: Cross-Connector Likes Synchronization
**Description**: Sync Spotify likes to Last.fm loves
**Flow**: Fetch liked tracks → Resolve entities → Update Last.fm → Track sync status


### Use Case 3: Playlist Backup & Restoration
**Description**: Export playlists to local storage and restore as needed
**Flow**: Fetch playlists → Store structured data → Restore to connector

## Development Workflow

1. Implementation begins with Use Case 1A (playlist sorting)
2. Each component is built with isolated testing
3. First build connector adapters, then core processing, then CLI interface
4. Run independent step validation before integration
5. Maintain strict LOC discipline - if code expands, refactor

## Error Handling

1. **Connector Boundaries** - Centralized error handling at API interfaces
2. **Retry Mechanism** - Exponential backoff for transient failures
3. **Validation** - Strict schema enforcement at boundaries
4. **Exception Groups** - Aggregate errors for batch operations

## Rate Limiting

1. **Per-Connector Limits** - Enforced per API requirements
2. **Caching Strategy** - Minimize calls through local storage
3. **Queuing** - Orderly processing of high-volume operations

## Testing Strategy

1. **Unit Tests** - Pure function and domain model testing
2. **Integration Tests** - Repository and connector adapter validation
3. **End-to-End Tests** - Manual validation of core user flows

## Configuration Management

Environment variables control:
- API credentials and endpoints
- Database location and settings
- Logging verbosity and destinations

## Deployment

This is a local CLI application:
1. Install with `pip install .` or `poetry install`
2. Configure with `.env` file
3. Run operations through CLI commands

## Further Evolution

1. **Web Interface** - Potential FastAPI frontend
2. **More Connectors** - Integration with Apple Music, YouTube, etc.
3. **Advanced Analytics** - Deeper insights into listening patterns

## Code Style Guidelines

1. **Type Annotations** - Used at all public interfaces
2. **Async/Await** - Used for all I/O operations
3. **Domain Language** - Names reflect music domain, not implementation
4. **Functional Core** - Pure domain functions with minimal side effects
5. **Line Limit** - Maximum 88 characters per line