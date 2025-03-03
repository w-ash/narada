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

| Node                  | Package        | Version | Purpose                                                         |
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
| Entity Definition     | attrs          | ≥25.1.0 | Immutable value objects with minimal boilerplate                |
| Functional Tools      | toolz          | ≥1.0.0  | Functional composition utilities                                |
| Logging               | loguru         | ≥0.7.3  | Context-aware logging with minimal configuration                |
| Error Handling        | backoff        | ≥2.2.1  | Declarative retry mechanisms for API stability                  |
| Terminal UI           | rich           | ≥13.7.0 | Rich terminal output formatting                                 |
| Workflow Engine       | Prefect        | ≥3.2.7  | DAG-based execution with minimal overhead                       |

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

### Directory Structure

```
narada/                        # Project root
├── pyproject.toml             # Project metadata and dependencies
├── README.md                  # Project documentation
│
├── narada/                    # Main package
│   ├── config.py              # Configuration management
│   │
│   ├── core/                  # Domain core
│   │   ├── models.py          # Entity definitions (Track, Playlist)
│   │   ├── matcher.py         # Entity resolution engine
│   │   ├── protocols.py       # Shared core protocols
│   │   ├── repositories.py    # Persistence abstractions
│   │   └── transforms.py      # Pure functional primitives
│   │
│   ├── data/                  # Data persistence
│   │   ├── database.py        # Database connection management
│   │   └── migrations/        # Schema version control
│   │
│   ├── integrations/          # Service adapters
│   │   ├── spotify.py         # Spotify API integration
│   │   ├── lastfm.py          # Last.fm API integration
│   │   └── musicbrainz.py     # MusicBrainz integration
│   │
├── workflows/                 # Consolidated workflow system
│   ├── workflow_nodes.py      # All node implementations
│   ├── node_registry.py       # Node type registration
│   ├── node_factory.py        # Factories for node creation
│   ├── prefect.py             # Prefect adapter (thin layer)
│   ├── definitions/           # JSON workflow definitions
│   │   ├── sort_by_plays.json # Use case 1A definition
│   │   └── discovery_mix.json # Use case 1B definition
│   │
│   └── cli/                   # Command line interface
│       ├── app.py             # CLI entry point
│       └── commands.py        # Command implementations
│
├── tests/                     # Test suite
│   ├── core/                  # Domain model tests
│   ├── workflows/             # Workflow engine tests
│   └── integration/           # End-to-end tests
│
└── docs/                      # Documentation
    ├── narada_bible.md        # Architectural vision
    └── workflow_guide.md      # Workflow authoring guide
```

#### Workflow System Interactions

The  architecture follows a clear flow pattern:

1. **Core Layer**: `models.py` defines domain objects
2. **Transformation Layer**: `transforms.py` provides pure functional operations on those models
3. **Node Layer**: `nodes.py` implements business logic using transforms and resolvers
4. **Registry Layer**: `registry.py` creates a type system for discovering nodes
5. **Execution Layer**: `prefect.py` connects the node system to Prefect

Data flows through these layers in a consistent way:

`Workflow Definition (JSON) → prefect.py → registry.py → nodes.py → transforms.py → models.py`

Each layer maintains clear boundaries and responsibilities, which is needed for a codebase targeting under 2000 LOC.
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

## Workflow Engine: Declarative Transformation Architecture
### Workflow Execution Architecture

Narada uses Prefect as its workflow orchestration layer, providing several architectural advantages:

1. **Separation of Concerns** - Prefect cleanly divides workflow definition from execution mechanics
2. **Robust Execution Model** - Built-in handling of retries, failures, and concurrency
3. **Minimal Overhead** - Embedded execution mode requires no additional infrastructure
4. **Progressive Scaling** - Path to distributed execution when workflows increase in complexity
5. **Real-time Progress Tracking** - Custom callback system for workflow visualization

The architecture follows a task-based model where:

- **Atomic Tasks** encapsulate individual operations (e.g., playlist fetching, filtering)
- **Flows** define the directed acyclic graph (DAG) of task dependencies
- **Parameters** enable runtime configuration of workflows
- **Task Results** are tracked and passed between execution steps
- **Context Propagation** ensures data flows correctly between nodes

This approach allows us to leverage our existing functional transformation primitives while gaining enterprise-grade execution reliability.

### Core Architectural Evolution

```
┌────────────────────┐     ┌───────────────────────┐     ┌───────────────────┐
│  Domain Models     │     │  Workflow Engine      │     │  Service Adapters │
│  ────────────────  │     │  ────────────────     │     │  ───────────────  │
│  • Track           │     │  • Node Registry │     │  • Spotify        │
│  • Playlist        │◄────┤  • Task Execution     │────►│  • Last.fm        │
│  • PlaylistOp      │     │  • DAG Processing     │     │  • MusicBrainz    │
└────────────────────┘     └───────────────────────┘     └───────────────────┘
```

### Workflow Engine

We'll implement a declarative workflow engine that separates transformation definitions from execution mechanics:

1. **Node-Based Design** - Modular pipeline elements in clear categories:
   - Sources (Spotify playlists, albums, etc.)
   - Transformers (filters, sorters, matchers)
   - Destinations (playlist creation, exports)

2. **Graph-Based Execution** - Workflows defined as directed acyclic graphs (DAGs) with:
   - Explicit task dependencies
   - Parameterized execution
   - Context propagation between steps

3. **Strategic Technology Selection** - Leverage existing workflow infrastructure:
   - Adopt Prefect as the execution engine
   - Wrap our transformation functions as tasks
   - Store workflow definitions in structured JSON format

### Transformation Categories

Our workflow nodes will be organized into functional categories:

| Category     | Purpose                               | Examples                             |
| ------------ | ------------------------------------- | ------------------------------------ |
| Sources      | Data ingestion from external services | Spotify playlist, album, radio       |
| Enrichers    | Enriches tracks with metadata         | Fetching lastfm playcounts           |
| Filters      | Selective content inclusion           | By date, playcount, metadata         |
| Sorters      | Order manipulation                    | By playcount, release, randomization |
| Selectors    | Subset extraction                     | First/last N, random selection       |
| Combiners    | Stream aggregation                    | Merge, interleave, deduplicate       |
| Destinations | Export and persistence                | Spotify playlist, local storage      |

### Possible Workflow Definition Format

Workflows will be defined in structured JSON that maps directly to execution graphs.

## Implementation Strategy

The implementation will follow a staged approach:

1. **Core Engine** - Implement a minimal node registry and execution flow
2. **Basic Nodes** - Build essential nodes for initial use cases
3. **Prefect Integration** - Wrap nodes as Prefect tasks for robust execution
4. **Storage Layer** - Persist workflow definitions in database with versioning

## Architectural Benefits

This evolution delivers significant strategic advantages:

1. **Zero-Code Workflows** - Create new transformations without writing code
2. **UI-Ready Architecture** - Workflow definitions map cleanly to visual builders
3. **Extension Without Refactoring** - Add new nodes while preserving existing ones
4. **Execution Reliability** - Leverage battle-tested workflow infrastructure
5. **Progressive Enhancement** - Start simple and evolve incrementally

By separating workflow definition from execution mechanics, we create a system that can evolve organically to support increasingly complex transformation needs while maintaining a clean architecture and staying within our LOC constraints.

This architecture has been proven in production systems handling millions of media items at companies like Spotify, Netflix, and SoundCloud. It's specifically designed for the kind of rapid iteration cycles needed in early-stage music technology products.

## Database Model

### Core Entities

Our database design follows a focused schema pattern that prioritizes essential storage needs while maintaining flexibility for future expansion. Each entity maps to a core domain concept while avoiding unnecessary normalization that would increase query complexity.

The schema consists of the following tables:
- tracks
- play_counts
- track_mappings
- playlists
- playlist_mappings
- playlist_tracks

All tables inherit from `NaradaDBBase` which provides:
- `id` (Primary Key)
- `is_deleted` (Soft delete flag)
- `deleted_at` (Soft delete timestamp)
- `created_at` (Record creation timestamp)
- `updated_at` (Last update timestamp)

#### Tracks Table

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
| is_deleted    | Boolean     | Soft delete indicator                |
| deleted_at    | DateTime    | Deleted at timestamp                 |
+---------------+-------------+--------------------------------------+
```

##### Key Points
1. **Connector Specific Fields** - Direct storage for common identifiers (spotify_id, isrc)
2. **JSON Artist Storage** - Flexible handling of multiple artists per track
3. **Metadata Optimization** - Core fields extracted for direct querying

#### Play Counts Table

Caches global and user-specific play count data from Last.fm.

```
+------------------+-------------+--------------------------------------+
| play_counts      | Type        | Purpose                              |
+------------------+-------------+--------------------------------------+
| id               | Integer (PK)| Internal identifier                  |
| track_id         | Integer (FK)| Reference to tracks table            |
| user_id          | String      | Last.fm username                     |
| play_count       | Integer     | Number of global plays               |
| user_play_count  | Integer     | Number of user plays                 |
| last_updated     | DateTime    | Cache timestamp                      |
| created_at       | DateTime    | Record creation timestamp            |
| updated_at       | DateTime    | Last update timestamp                |
| is_deleted       | Boolean     | Soft delete indicator                |
| deleted_at       | DateTime    | Deleted at timestamp                 |
+------------------+-------------+--------------------------------------+
```

##### Key Points
1. **Cache Design** - Structured as a cache with refresh timestamps
2. **Dual Metrics** - Tracks both global and per-user play counts
3. **Unique Constraint** - One count entry per track/user combination

#### Track Connector Mappings Table

The Track Connector Mappings table serves as our universal cross-connector integration layer for tracks.

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
| connector_metadata     | JSON        | Connector-specific auxiliary data    |
| created_at             | DateTime    | Record creation timestamp            |
| updated_at             | DateTime    | Last update timestamp                |
| is_deleted             | Boolean     | Soft delete indicator                |
| deleted_at             | DateTime    | Deleted at timestamp                 |
+------------------------+-------------+--------------------------------------+
```

##### Key Points
1. **Connector-Agnostic Architecture** - Single table handles all connector integrations
2. **Resolution Method Tracking** - Explicitly documents how each match was determined
3. **Confidence Scoring** - Quantifies match quality on 0-100 scale
4. **Metadata Storage** - JSON field stores connector-specific context

#### Playlists Table

Source of truth for playlists with essential metadata.

```
+---------------+-------------+--------------------------------------+
| playlists     | Type        | Purpose                              |
+---------------+-------------+--------------------------------------+
| id            | Integer (PK)| Internal identifier                  |
| name          | String      | Playlist name                        |
| description   | Text        | Playlist description                 |
| track_count   | Integer     | Number of tracks                     |
| created_at    | DateTime    | Record creation timestamp            |
| updated_at    | DateTime    | Last update timestamp                |
| is_deleted    | Boolean     | Soft delete indicator                |
| deleted_at    | DateTime    | Deleted at timestamp                 |
+---------------+-------------+--------------------------------------+
```

##### Key Points
1. **Source of Truth** - Connector-agnostic playlist representation
2. **Minimal Schema** - Only essential fields for playlist identification
3. **Track Count Cache** - Pre-calculated count for efficient display

#### Playlist Connector Mappings Table

Maps internal playlists to external connector playlists.

```
+------------------------+-------------+--------------------------------------+
| playlist_mappings      | Type        | Purpose                              |
+------------------------+-------------+--------------------------------------+
| id                     | Integer (PK)| Internal identifier                  |
| playlist_id            | Integer (FK)| Reference to our playlist            |
| connector_name         | String      | Connector name (spotify, apple, etc) |
| connector_id           | String      | Connector's playlist identifier      |
| last_synced            | DateTime    | Last successful sync                 |
| created_at             | DateTime    | Record creation timestamp            |
| updated_at             | DateTime    | Last update timestamp                |
| is_deleted             | Boolean     | Soft delete indicator                |
| deleted_at             | DateTime    | Deleted at timestamp                 |
+------------------------+-------------+--------------------------------------+
```

##### Key Points
1. **Sync Tracking** - Timestamps for synchronization history
2. **Unique Mapping** - Each playlist maps to exactly one external playlist per connector
3. **Consistent Pattern** - Follows same mapping pattern as track resolution

#### Playlist Tracks Table

Maps the many-to-many relationship between playlists and tracks with ordering.

```
+-----------------+-------------+--------------------------------------+
| playlist_tracks | Type        | Purpose                              |
+-----------------+-------------+--------------------------------------+
| id              | Integer (PK)| Internal identifier                  |
| playlist_id     | Integer (FK)| Reference to playlists table         |
| track_id        | Integer (FK)| Reference to tracks table            |
| sort_key        | String      | Lexicographical ordering key         |
| created_at      | DateTime    | Record creation timestamp            |
| updated_at      | DateTime    | Last update timestamp                |
| is_deleted      | Boolean     | Soft delete indicator                |
| deleted_at      | DateTime    | Deleted at timestamp                 |
+-----------------+-------------+--------------------------------------+
```

##### Key Points
1. **Efficient Ordering** - Lexicographical sort keys (e.g., "a0000000")
2. **Implicit History** - Track position changes preserved through timestamps
3. **Fast Retrieval** - Composite index optimizes ordered track fetching

### Design Decisions

1. **Base Model Pattern**
   - All tables inherit from `NaradaDBBase` with consistent fields
   - Standardized soft delete, timestamps, and primary keys
   - Reduces duplicated code and ensures consistency

2. **JSON for Complex Data**
   - Artists and connector metadata stored as JSON
   - Avoids complex joins while supporting nested data structures
   - Trade-off: Less query optimization for complex filtering

3. **Soft Delete Strategy**
   - `is_deleted` flag with timestamp across all tables
   - Preserves relational integrity while allowing "deletion"
   - Enables data recovery and history preservation

4. **Separation of Concerns**
   - Core data separated from connector-specific mappings
   - Enables clean cross-connector operations
   - Maintains single source of truth for each entity type

### Indexing Strategy

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

### Database Session Management

The database implementation provides several key utilities:

1. **Connection Pooling** - Configured with timeouts and recycling
2. **Async Session Factory** - Type-safe async sessions with SQLAlchemy 2.0 patterns
3. **Context Manager** - `get_session()` for clean transaction handling

## Connector Integration Strategy

Our three core integrations create a unified music metadata system that exceeds the capabilities of any single connector. Each integration serves a specific purpose in our pipeline architecture:

### Connected Service Integrations

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

#### 1N: Additional Playlist Generation
**Description**: Support dozens of complex DAG flows, flexibly extending 1A & 1B to any number of workflows  


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

### Possible Further Evolution

1. **Web Interface** - Potential FastAPI frontend
2. **More Connectors** - Integration with Apple Music, YouTube, etc.
3. **Advanced Analytics** - Deeper insights into listening patterns

## Development Workflow

1. Implementation begins with Use Case 1A (playlist sorting)
2. Each node is built with isolated testing
3. First build connector adapters, then core processing, then CLI interface
4. Run independent step validation before integration
5. Maintain strict LOC discipline - if code expands, refactor
## Deployment

This is a local CLI application:
1. Install with `poetry install`
2. Configure with `.env` file
3. Run operations through CLI commands


