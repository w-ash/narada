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
| Database ORM          | SQLAlchemy     | ^2.0.40 | Type-safe query building, async support                         |
| Database Migrations   | Alembic        | ^1.15.2 | Schema version control and migrations                           |
| Database Async        | aiosqlite      | ^0.21.0 | Async SQLite driver for SQLAlchemy                              |
| HTTP Client           | httpx          | ^0.28.1 | Modern async-first HTTP client                                  |
| Spotify Interface     | spotipy        | ^2.25.1 | OAuth handling, Spotify Web API client                          |
| Last.fm Interface     | pylast         | ^5.5.0  | Last.fm API integration                                         |
| MusicBrainz Interface | musicbrainzngs | ^0.7.1  | MusicBrainz metadata lookups                                    |
| CLI Framework         | typer          | ^0.15.2 | Type-safe CLI with minimal boilerplate                          |
| Terminal UI           | rich           | ^14.0.0 | Rich terminal output formatting and progress bars               |
| Entity Definition     | attrs          | ^25.3.0 | Immutable value objects with minimal boilerplate                |
| Functional Tools      | toolz          | ^1.0.0  | Functional composition utilities                                |
| Logging               | loguru         | ^0.7.3  | Context-aware logging with minimal configuration                |
| Error Handling        | backoff        | ^2.2.1  | Declarative retry mechanisms for API stability                  |
| String Matching       | rapidfuzz      | ^3.13.0 | High-performance fuzzy string matching                          |
| Workflow Engine       | Prefect        | ^3.3.3  | DAG-based execution with minimal overhead                       |
| Configuration         | python-dotenv  | ^1.1.0  | Environment variable management                                 |

### Development Tools

| Tool          | Package        | Version | Purpose                           |
| ------------- | -------------- | ------- | --------------------------------- |
| Build System  | Poetry         | ≥2.1.0  | Dependency and build management   |
| Linter/Format | ruff           | ^0.11.5 | Fast, comprehensive Python linter and formatter |
| Type Checker  | pyright        | ^1.1.399| Static type checking               |
| Testing       | pytest         | ^8.3.5  | Test framework and runner         |
| Async Testing | pytest-asyncio | ^0.26.0 | Async test support                |
| Coverage      | pytest-cov     | ^6.1.1  | Test coverage reporting           |
| Git Hooks     | pre-commit     | ^4.2.0  | Automated pre-commit checks       |

### Key Architectural Patterns

| Pattern | Implementation | Benefit |
|---------|---------------|---------|
| Pipeline Architecture | toolz.compose + workflow nodes | Enables unlimited playlist transformations within fixed LOC budget |
| Connector Adapters | Thin API wrappers with async support | Isolates external dependencies for easier testing and replacement |
| Repository Pattern | SQLAlchemy 2.0 async with bulk operations | Centralizes data access with consistent error handling and performance |
| Entity Resolution | Multi-tier matching with confidence scoring | Balances accuracy with performance through progressive resolution |
| Command Pattern | Typer CLI with Rich formatting | Separates UI from business logic with beautiful user experience |
| Service Layer | Domain-specific async services | Places business logic between repositories and interfaces |
| Progress Integration | Unified progress tracking system | Consistent progress feedback across all operations |
| Async-First Design | Async/await throughout the stack | Efficient handling of I/O-bound operations (API calls, DB) |
| Composition | Like operations and sync abstractions | Enables DRY implementation of related functionality |
| Checkpoint-based Sync | SyncCheckpoint entities with timestamps | Provides resumability for long-running operations |
| Batch-First Operations | Repository bulk operations | Optimizes performance for large datasets |
| Type Safety | Comprehensive type annotations | Prevents runtime errors and improves IDE support |

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

### Directory Structure (Clean Architecture - v0.2.3)

```
narada/                           # Project root
├── pyproject.toml                # Project metadata and dependencies  
├── README.md                     # Project documentation
├── CLAUDE.md                     # Commands and style guide
├── BACKLOG.md                    # Development backlog and roadmap
│
├── src/                          # Clean Architecture source code
│   ├── domain/                   # Pure business logic (zero external dependencies)
│   │   ├── entities/             # Core business entities
│   │   │   ├── track.py          # Track and Artist entities
│   │   │   ├── playlist.py       # Playlist and TrackList entities  
│   │   │   ├── operations.py     # Operation result entities
│   │   │   └── shared.py         # Shared value objects
│   │   ├── matching/             # Track matching algorithms
│   │   │   ├── algorithms.py     # Pure confidence calculation logic
│   │   │   ├── types.py          # MatchResult, ConfidenceEvidence types
│   │   │   └── protocols.py      # Matching service contracts
│   │   └── transforms/           # Functional transformation pipelines
│   │       └── core.py           # Pure functional primitives
│   │
│   ├── application/              # Use cases and orchestration
│   │   ├── services/             # Use case orchestrators
│   │   │   ├── import_service.py # Import orchestration
│   │   │   └── matching_service.py # High-level matching orchestration
│   │   ├── utilities/            # Shared application utilities
│   │   │   ├── batching.py       # Batch processing utilities
│   │   │   ├── progress.py       # Progress handling utilities
│   │   │   └── results.py        # Result factory utilities
│   │   └── workflows/            # Business workflow definitions
│   │       ├── node_catalog.py   # Node registry and catalog
│   │       ├── node_factories.py # Node creation factories
│   │       ├── source_nodes.py   # Source node implementations
│   │       ├── destination_nodes.py # Destination node implementations
│   │       ├── prefect.py        # Prefect adapter with progress tracking
│   │       └── definitions/      # JSON workflow definitions
│   │
│   └── infrastructure/           # External implementations
│       ├── config.py             # Configuration management
│       ├── cli/                  # Command line interface
│       │   ├── app.py            # CLI entry point with flattened commands
│       │   ├── *_commands.py     # Command implementations by domain
│       │   └── progress_provider.py # Rich-based progress UI
│       │
│       ├── connectors/           # External service integrations
│       │   ├── spotify.py        # Spotify API integration
│       │   ├── lastfm.py         # Last.fm API integration
│       │   ├── musicbrainz.py    # MusicBrainz integration
│       │   └── base_connector.py # Base connector classes
│       │
│       ├── persistence/          # Data access layer
│       │   ├── database/         # Database management
│       │   │   ├── db_connection.py # Database connection management
│       │   │   ├── db_models.py  # SQLAlchemy model definitions
│       │   │   └── migrations/   # Schema version control
│       │   └── repositories/     # Repository implementations
│       │       ├── track/        # Track repository module
│       │       ├── playlist/     # Playlist repository module
│       │       └── sync.py       # Sync checkpoint repository
│       │
│       └── services/             # Infrastructure-level services
│           ├── matcher.py        # Entity resolution service
│           ├── *_import.py       # Import service implementations
│           └── like_sync.py      # Cross-service synchronization
│
├── tests/                        # Test suite (Clean Architecture layers)
│   ├── unit/                     # Fast unit tests
│   │   ├── test_domain_*.py      # Domain layer tests (37 tests - zero dependencies)
│   │   ├── test_application_*.py # Application layer tests (54 tests)
│   │   └── test_services/        # Legacy service unit tests
│   ├── integration/              # Integration tests
│   │   └── test_*.py             # External service integration tests
│   └── cli/                      # CLI command tests
│       └── test_*.py             # Command interface tests
│
├── docs/                         # Documentation and guides
├── scripts/                      # Utility scripts
├── alembic/                      # Database migrations
└── data/                         # Data directory (db, imports, logs)
```

#### Clean Architecture Theory

**Why This Structure?**

Clean Architecture organizes code by dependency direction: Infrastructure → Application → Domain. Dependencies only flow inward.

- **Domain**: Pure business logic (track matching, confidence algorithms). No external dependencies.
- **Application**: Use cases and orchestration. Defines interfaces for infrastructure to implement.
- **Infrastructure**: External concerns (APIs, databases, CLI). Implements application interfaces.

**Key Benefits**:
- Domain tests run 10x faster (no database/network)
- Business logic works with any interface (CLI today, web API tomorrow)
- Technology can be swapped without changing core features
- Clear debugging boundaries

This enables Narada to add new interfaces (web, mobile) without rewriting business logic.

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
│  • Track           │     │  • Node Registry      │     │  • Spotify        │
│  • Playlist        │◄────┤  • Task Execution     │────►│  • Last.fm        │
│  • TrackLike       │     │  • DAG Processing     │     │  • MusicBrainz    │
└────────────────────┘     └───────────────────────┘     └───────────────────┘
                                     ▲  
                                     │  
                                     ▼  
┌────────────────────┐     ┌───────────────────────┐     ┌───────────────────┐
│  Repositories      │     │  Services             │     │  CLI Layer        │
│  ────────────────  │     │  ────────────────     │     │  ───────────────  │
│  • TrackRepository │◄────┤  • Like Operations    │────►│  • Commands       │
│  • PlaylistRepo    │     │  • Sync Services      │     │  • UI Components  │
│  • TrackSyncRepo   │     │  • Workflow Services  │     │  • Input Handling │
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
- connector_tracks
- track_mappings
- track_metrics
- track_likes
- track_plays
- playlists
- playlist_mappings
- playlist_tracks
- sync_checkpoints

All tables inherit from `NaradaDBBase` which provides:
- `id` (Primary Key)
- `is_deleted` (Soft delete flag)
- `deleted_at` (Soft delete timestamp)
- `created_at` (Record creation timestamp)
- `updated_at` (Last update timestamp)

#### Tracks Table

Central storage for music metadata with essential identification information.

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
| mbid          | String (IDX)| MusicBrainz identifier               |
| created_at    | DateTime    | Record creation timestamp            |
| updated_at    | DateTime    | Last update timestamp                |
| is_deleted    | Boolean     | Soft delete indicator                |
| deleted_at    | DateTime    | Deleted at timestamp                 |
+---------------+-------------+--------------------------------------+
```

##### Key Points
1. **Core Track Entity** - Primary source of truth for track information
2. **Streamlined Identifiers** - Direct storage for common identifiers (spotify_id, isrc, mbid)
3. **JSON Artist Storage** - Flexible handling of multiple artists per track
4. **Rich Relationships** - Connected to mappings, metrics, likes, plays, and playlists

#### Connector Tracks Table

External service-specific track representations with rich metadata.

```
+--------------------+-------------+--------------------------------------+
| connector_tracks   | Type        | Purpose                              |
+--------------------+-------------+--------------------------------------+
| id                 | Integer (PK)| Internal identifier                  |
| connector_name     | String (IDX)| Service name (spotify, lastfm, etc)  |
| connector_track_id | String      | External service track identifier    |
| title              | String      | Track title in external service      |
| artists            | JSON        | Artists as represented in service    |
| album              | String      | Album name in external service       |
| duration_ms        | Integer     | Duration in milliseconds             |
| isrc               | String (IDX)| ISRC code if available               |
| release_date       | DateTime    | Release date in external service     |
| raw_metadata       | JSON        | Complete service-specific metadata   |
| last_updated       | DateTime    | Timestamp of last metadata refresh   |
| created_at         | DateTime    | Record creation timestamp            |
| updated_at         | DateTime    | Last update timestamp                |
| is_deleted         | Boolean     | Soft delete indicator                |
| deleted_at         | DateTime    | Deleted at timestamp                 |
+--------------------+-------------+--------------------------------------+
```

##### Key Points
1. **External Representation** - Preserves exactly how tracks appear in each service
2. **Complete Metadata** - Captures all available metadata from each service
3. **Independent Existence** - Can exist before being mapped to internal tracks
4. **Efficiency** - Minimizes API calls by storing complete external track data

#### Track Mappings Table

Connects internal tracks to external service tracks with match quality metadata.

```
+--------------------+-------------+--------------------------------------+
| track_mappings     | Type        | Purpose                              |
+--------------------+-------------+--------------------------------------+
| id                 | Integer (PK)| Internal identifier                  |
| track_id           | Integer (FK)| Reference to canonical track         |
| connector_track_id | Integer (FK)| Reference to connector track         |
| match_method       | String      | Resolution method used               |
| confidence         | Integer     | Match confidence (0-100)             |
| created_at         | DateTime    | Record creation timestamp            |
| updated_at         | DateTime    | Last update timestamp                |
| is_deleted         | Boolean     | Soft delete indicator                |
| deleted_at         | DateTime    | Deleted at timestamp                 |
+--------------------+-------------+--------------------------------------+
```

##### Key Points
1. **True Many-to-Many** - Links internal tracks to connector tracks
2. **Resolution Metadata** - Tracks match method and confidence
3. **Enhanced Structure** - Points to complete connector track records
4. **Flexible Architecture** - Supports future alternative match algorithms

#### Track Metrics Table

Time-series metrics for tracks from various services.

```
+-------------------+-------------+--------------------------------------+
| track_metrics     | Type        | Purpose                              |
+-------------------+-------------+--------------------------------------+
| id                | Integer (PK)| Internal identifier                  |
| track_id          | Integer (FK)| Reference to track                   |
| connector_name    | String      | Source service name                  |
| metric_type       | String      | Metric type (play_count, etc)        |
| value             | Float       | Numeric metric value                 |
| collected_at      | DateTime    | When the metric was collected        |
| created_at        | DateTime    | Record creation timestamp            |
| updated_at        | DateTime    | Last update timestamp                |
| is_deleted        | Boolean     | Soft delete indicator                |
| deleted_at        | DateTime    | Deleted at timestamp                 |
+-------------------+-------------+--------------------------------------+
```

##### Key Points
1. **Time-Series Design** - Historical metrics with timestamps
2. **Multiple Metric Types** - Supports various metrics (plays, popularity, etc.)
3. **Service-Specific** - Clearly identifies the source of each metric
4. **Flexible Value Type** - Floating-point for wider range of metrics

#### Track Likes Table

Track preference state across music services with synchronization support.

```
+-----------------+-------------+--------------------------------------+
| track_likes     | Type        | Purpose                              |
+-----------------+-------------+--------------------------------------+
| id              | Integer (PK)| Internal identifier                  |
| track_id        | Integer (FK)| Reference to track                   |
| service         | String      | Service name (spotify, lastfm, etc)  |
| is_liked        | Boolean     | Current like status                  |
| liked_at        | DateTime    | When the track was liked             |
| last_synced     | DateTime    | When sync was last performed         |
| created_at      | DateTime    | Record creation timestamp            |
| updated_at      | DateTime    | Last update timestamp                |
| is_deleted      | Boolean     | Soft delete indicator                |
| deleted_at      | DateTime    | Deleted at timestamp                 |
+-----------------+-------------+--------------------------------------+
```

##### Key Points
1. **Like Status Tracking** - Records like/favorite status per service
2. **Sync Support** - Timestamps for tracking synchronization
3. **Historical Data** - Captures when tracks were liked
4. **Uniqueness** - One like entry per track/service combination

#### Track Plays Table ✅ **IMPLEMENTED**

Immutable record of track play events from Spotify personal data imports.

```
+-------------------+-------------+--------------------------------------+
| track_plays       | Type        | Purpose                              |
+-------------------+-------------+--------------------------------------+
| id                | Integer (PK)| Internal identifier                  |
| track_id          | Integer (FK)| Reference to track                   |
| service           | String      | Service name (spotify, lastfm, etc)  |
| played_at         | DateTime    | When the track was played            |
| ms_played         | Integer     | Milliseconds played (optional)       |
| context           | JSON        | Additional play context              |
| import_timestamp  | DateTime    | When this record was imported        |
| import_source     | String      | Source of import (e.g., "spotify_personal_data") |
| import_batch_id   | String      | Batch identifier for import group    |
| created_at        | DateTime    | Record creation timestamp            |
| updated_at        | DateTime    | Last update timestamp                |
| is_deleted        | Boolean     | Soft delete indicator                |
| deleted_at        | DateTime    | Deleted at timestamp                 |
+-------------------+-------------+--------------------------------------+
```

##### Key Points
1. **Immutable Events** - Records individual play events from Spotify exports
2. **Timeline Ready** - Optimized for chronological queries with played_at index
3. **Import Tracking** - Full provenance tracking for data imports
4. **Batch Processing** - Support for efficient bulk imports with batch IDs
5. **Complete Context** - JSON field for platform-specific metadata

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
| connector_playlist_id  | String      | Connector's playlist identifier      |
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

#### Sync Checkpoints Table

Tracks synchronization state for incremental operations.

```
+------------------+-------------+--------------------------------------+
| sync_checkpoints | Type        | Purpose                              |
+------------------+-------------+--------------------------------------+
| id               | Integer (PK)| Internal identifier                  |
| user_id          | String      | User identifier                      |
| service          | String      | Service name (spotify, lastfm, etc)  |
| entity_type      | String      | Entity type (likes, plays, etc)      |
| last_timestamp   | DateTime    | Last successful sync timestamp       |
| cursor           | String      | Continuation token if applicable     |
| created_at       | DateTime    | Record creation timestamp            |
| updated_at       | DateTime    | Last update timestamp                |
| is_deleted       | Boolean     | Soft delete indicator                |
| deleted_at       | DateTime    | Deleted at timestamp                 |
+------------------+-------------+--------------------------------------+
```

##### Key Points
1. **Incremental Sync** - Enables efficient incremental operations
2. **Resumability** - Cursor support for paginated operations
3. **Multi-Entity** - Supports different entity types per service
4. **User Context** - Tracks separate sync state per user

### Design Decisions

1. **Base Model Pattern**
   - All tables inherit from `NaradaDBBase` with consistent fields
   - Standardized soft delete, timestamps, and primary keys
   - Reduces duplicated code and ensures consistency

2. **Connector Architecture**
   - Separation between internal records and connector-specific entities
   - Allows complete metadata storage for each service
   - Supports advanced cross-service entity resolution

3. **JSON for Complex Data**
   - Artists and raw metadata stored as JSON
   - Avoids complex joins while supporting nested data structures
   - Preserves complete information from external services

4. **Temporal Design**
   - Time-series metrics with explicit collection timestamps
   - Event-based play records with chronological indexing
   - Sync checkpoints for incremental processing

5. **Soft Delete Strategy**
   - `is_deleted` flag with timestamp across all tables
   - Preserves relational integrity while allowing "deletion"
   - Enables data recovery and history preservation

### Relationship Architecture

The database uses a rich relationship model with SQLAlchemy's relationship feature:

1. **Core Track Relationships**
   - Track → Mappings → Connector Tracks (many-to-many)
   - Track → Metrics (one-to-many)
   - Track → Likes (one-to-many)
   - Track → Plays (one-to-many)
   - Track → Playlist Tracks → Playlists (many-to-many)

2. **Playlist Relationships**
   - Playlist → Playlist Tracks → Tracks (many-to-many)
   - Playlist → Mappings (one-to-many)

3. **Cascade Behavior**
   - Appropriate cascade delete settings
   - Passive delete flags for query optimization
   - Proper orphan handling for clean relationship management

### Indexing Strategy

| Table | Index | Type | Purpose | SQLAlchemy Implementation |
|-------|-------|------|---------|---------------------------|
| tracks | id | Primary | Primary key | `mapped_column(primary_key=True)` |
| tracks | spotify_id | Single | Fast lookup by Spotify ID | `mapped_column(index=True)` |
| tracks | isrc | Single | Fast lookup for entity resolution | `mapped_column(index=True)` |
| tracks | mbid | Single | Fast lookup by MusicBrainz ID | `mapped_column(index=True)` |
| connector_tracks | id | Primary | Primary key | `mapped_column(primary_key=True)` |
| connector_tracks | connector_name | Single | Fast filtering by service | `mapped_column(index=True)` |
| connector_tracks | (connector_name, connector_track_id) | Composite Unique | Prevent duplicates | `UniqueConstraint('connector_name', 'connector_track_id')` |
| connector_tracks | (connector_name, isrc) | Composite | Lookup by service and ISRC | `Index('ix_connector_tracks_lookup', 'connector_name', 'isrc')` |
| track_mappings | id | Primary | Primary key | `mapped_column(primary_key=True)` |
| track_mappings | (track_id, connector_track_id) | Composite | Fast relationship lookup | `Index('ix_track_mappings_lookup', 'track_id', 'connector_track_id')` |
| track_metrics | id | Primary | Primary key | `mapped_column(primary_key=True)` |
| track_metrics | (track_id, connector_name, metric_type) | Composite | Fast metric lookup | `Index('ix_track_metrics_lookup', 'track_id', 'connector_name', 'metric_type')` |
| track_likes | id | Primary | Primary key | `mapped_column(primary_key=True)` |
| track_likes | (track_id, service) | Composite Unique | Enforce single like entry | `UniqueConstraint('track_id', 'service')` |
| track_likes | (service, is_liked) | Composite | Fast filtering by service | `Index('ix_track_likes_lookup', 'service', 'is_liked')` |
| track_plays | id | Primary | Primary key | `mapped_column(primary_key=True)` |
| track_plays | service | Single | Filter by service | `Index('ix_track_plays_service', 'service')` |
| track_plays | played_at | Single | Chronological queries | `Index('ix_track_plays_timeline', 'played_at')` |
| playlists | id | Primary | Primary key | `mapped_column(primary_key=True)` |
| playlist_tracks | id | Primary | Primary key | `mapped_column(primary_key=True)` |
| playlist_tracks | (playlist_id, sort_key) | Composite | Ordered track retrieval | `Index('ix_playlist_tracks_order', 'playlist_id', 'sort_key')` |
| playlist_mappings | id | Primary | Primary key | `mapped_column(primary_key=True)` |
| playlist_mappings | (playlist_id, connector_name) | Composite Unique | Enforce single mapping | `UniqueConstraint('playlist_id', 'connector_name')` |
| sync_checkpoints | id | Primary | Primary key | `mapped_column(primary_key=True)` |
| sync_checkpoints | (user_id, service, entity_type) | Composite Unique | Enforce single checkpoint | `UniqueConstraint('user_id', 'service', 'entity_type')` |

### Database Session Management

The database implementation provides several key utilities:

1. **Connection Pooling** - Configured with timeouts and recycling
2. **Async Session Factory** - Type-safe async sessions with SQLAlchemy 2.0 patterns
3. **Context Manager** - `get_session()` for clean transaction handling
4. **Base Class Utilities** - Methods like `active_records()` and `mark_soft_deleted()`

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

### Use Case 0: Modern CLI Experience ✅ **IMPLEMENTED**
**Description**: Beautiful, intuitive command-line interface with Rich formatting
**Implementation Status**: **COMPLETE** - Modern CLI with flattened commands and Rich UI

**Implemented Features**:
- ✅ **Flattened Command Structure**: Direct commands like `import-spotify-likes`, `export-likes-to-lastfm`
- ✅ **Rich Terminal UI**: Color-coded panels, progress bars, and professional typography
- ✅ **Direct Workflow Execution**: Run workflows as simple commands (`narada discovery_mix`)
- ✅ **Shell Completion**: Tab completion for commands and workflow names
- ✅ **Unified Help System**: Organized command help with descriptive panels
- ✅ **Progress Integration**: Real-time progress tracking for all long-running operations
- ✅ **Error Handling**: Graceful error messages with actionable guidance

**CLI Commands**:
```sh
# System commands
narada setup              # Configure music service connections
narada status             # Show system status and configuration

# Data synchronization  
narada import-spotify-likes    # Import liked tracks from Spotify
narada import-spotify-plays    # Import play history from Spotify export
narada export-likes-to-lastfm  # Export likes to Last.fm

# Workflow management
narada wf list                 # List available workflows
narada discovery_mix           # Run discovery mix workflow directly
narada sort_by_lastfm_user_playcount  # Run sorting workflow directly

# Help and completion
narada --help                  # Show all commands with organized panels
narada completion --install    # Install shell completion
```

### Use Case 1: Smart Playlist Operations ✅ **IMPLEMENTED**

#### 1A: Play Count Sorting ✅ **IMPLEMENTED**
**Description**: Sort Spotify playlist by personal Last.fm play count  
**Implementation Status**: **COMPLETE** - Available as `sort_by_lastfm_user_playcount` command

**Architecture Flow**:
- Fetch playlist via Spotify API
- Resolve tracks to Last.fm entities via matcher service
- Retrieve & cache play counts with batch optimization
- Apply sorting transformation via workflow engine
- Create/update playlist via Spotify API

#### 1B: Discovery Mix Generation ✅ **IMPLEMENTED** 
**Description**: Filter multiple playlists by recency/plays/blocks for discovery mix  
**Implementation Status**: **COMPLETE** - Available as `discovery_mix` command

**Architecture Flow**:
- Batch fetch source playlists
- Apply composite filtering pipeline via workflow nodes
- Deduplicate across sources using workflow transforms
- Sort by configurable metrics (Last.fm play counts, release dates)
- Generate new playlist with rich metadata

#### 1N: Additional Playlist Generation ✅ **IMPLEMENTED**
**Description**: Support dozens of complex DAG flows via JSON workflow definitions
**Implementation Status**: **COMPLETE** - Extensible workflow system with 4+ predefined workflows

**Available Workflows**:
- `discovery_mix` - Multi-source discovery playlist generation
- `sort_by_lastfm_user_playcount` - Sort by personal Last.fm play counts
- `sort_by_lastfm_global_playcount` - Sort by global Last.fm popularity  
- `sort_by_release_date` - Sort by track release dates  


### Use Case 2: Cross-Connector Likes Synchronization ✅ **IMPLEMENTED**
**Description**: Sync likes between services with Narada as source of truth  
**Implementation Status**: **COMPLETE** - Full bidirectional like synchronization implemented

**Architecture Flow**:
- **Import Phase**:
  - Fetch liked tracks from external services (Spotify)
  - Save to local database with proper entity resolution
  - Mark tracks as liked in Narada (source of truth)
  - Track sync state with checkpoints for resumability

- **Export Phase**:
  - Identify tracks liked in Narada but not in target service (Last.fm)
  - Use matcher system for accurate service entity resolution
  - Update external service (mark as loved in Last.fm)
  - Record sync state for incremental operation

- **Implemented Components**:
  - ✅ `LikeOperation` service for common like operations
  - ✅ `CheckpointManager` for tracking sync state 
  - ✅ Spotify like import with OAuth integration
  - ✅ Last.fm love export with API integration
  - ✅ Batch processing for performance optimization
  - ✅ Incremental sync with timestamp-based filtering
  - ✅ Rich progress bars and CLI feedback
  - ✅ Comprehensive test coverage

- **CLI Commands**:
  ```sh
  # Import liked tracks from Spotify to Narada
  narada import-spotify-likes [--limit NUMBER] [--batch-size NUMBER] [--user-id STRING]
  
  # Export liked tracks from Narada to Last.fm
  narada export-likes-to-lastfm [--limit NUMBER] [--batch-size NUMBER] [--user-id STRING]
  ```

### Use Case 2.1: Play History Import ✅ **IMPLEMENTED**
**Description**: Import comprehensive play history from Spotify GDPR exports with revolutionary track resolution
**Implementation Status**: **COMPLETE** - Enhanced Spotify track resolution with 100% processing rate

**Features**:
- ✅ Parse Spotify personal data JSON exports (any age, 2011+)
- ✅ **Enhanced Multi-Stage Track Resolution**:
  - **Stage 1**: Direct API lookup with relinking detection (90%+ success)
  - **Stage 2**: Metadata-based search fallback with confidence scoring (≥70% threshold)
  - **Stage 3**: Metadata preservation for complete data coverage (100% coverage)
- ✅ **Smart Relinking Detection**: Automatically handles Spotify's track versioning and remastering
- ✅ **Zero Data Loss**: Every play gets imported and tracked, even unresolvable tracks
- ✅ **Automatic Track Creation**: Creates internal tracks from Spotify API data
- ✅ **Rich Resolution Analytics**: Detailed statistics showing exactly how tracks were resolved
- ✅ **Future-Proof Design**: Handles obsolete track IDs and rights changes
- ✅ **Performance Optimized**: Efficient batching with error isolation and rate limiting
- ✅ Track import progress with checkpoints
- ✅ CLI command with Rich progress tracking

**CLI Commands**:
  ```sh
  # Import play history from Spotify personal data export
  narada import-spotify-plays FILE_PATH [--batch-size NUMBER]
  ```

**Enhanced Resolution Output Example**:
  ```
  📊 Enhanced Resolution Results:
     Resolution rate: 100.0%
     Direct ID: 2        (tracks found as-is)
     Relinked ID: 8     (tracks updated by Spotify)
     Search match: 0     (metadata-based fallback)
     Preserved metadata: 0  (unresolvable but saved)
     Total with track ID: 10
  ```

**Architecture**:
- `SpotifyPersonalDataParser` for JSON parsing
- `SpotifyPlayResolver` with enhanced `resolve_with_fallback()` method
- Multi-stage resolution pipeline leveraging existing confidence scoring
- `TrackPlayRepository` for efficient bulk storage
- Progress integration with real-time feedback and resolution statistics

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

### Current Development Roadmap (v0.2.4-0.2.6)

**✅ v0.2.2 COMPLETE**: Enhanced Spotify JSON Track Resolution with 100% processing rate
**✅ v0.2.3 COMPLETE**: Clean Architecture Migration for future web interface foundation

Based on the current backlog, the immediate roadmap focuses on:

#### v0.2.4: User Experience & Reliability  
- **Enhanced Error Handling** - Better error messages and retry logic
- **Shell Completion Support** - Tab completion for bash/zsh/fish
- **Progress Reporting Consistency** - Unified progress across all operations

#### v0.2.5: Performance & Advanced Analytics
- **Performance Optimizations** - Database query optimization for large datasets
- **Advanced Play Analytics** - Listening pattern analysis and insights
- **Background Sync Capabilities** - Scheduled synchronization jobs

#### v0.2.6: Advanced Features
- **Play-Based Workflow Filters** - Filter and sort by play counts and time windows
- **Export Capabilities** - Export analytics and play data to various formats

### Future Evolution (v0.3.0+)

1. **Manual Entity Resolution** - User override for automatic matching
2. **Enhanced Destination Nodes** - Dynamic playlist naming and updates  
3. **Web Interface** - Potential FastAPI frontend with workflow visualization
4. **More Connectors** - Integration with Apple Music, YouTube, etc.
5. **LLM-Assisted Workflows** - Natural language workflow creation

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


