# Narada

**A music metadata hub that connects multiple streaming services**

Narada connects multiple music services (Spotify, Last.fm, MusicBrainz) to help you sync your listening data, create smart playlists, and manage your music across platforms.

## Features

- **Music Service Integration**: Connect with Spotify, Last.fm, and MusicBrainz
- **Workflow System**: Define complex playlist transformation pipelines using JSON
- **Smart Filtering**: Filter tracks by release date, artist, popularity, and more
- **Modern CLI Interface**: Rich-formatted output with panels, colors, and professional typography
- **Direct Workflow Execution**: Run workflows as simple commands (`narada discovery_mix`)
- **Data Persistence**: Store and manage playlists in local database and Spotify

## What's New in v0.2.3

### Core Features (v0.2.2 & Earlier)
- 🚀 **Enhanced Spotify Track Resolution**: 100% processing rate for Spotify exports
- 🔗 **Smart Relinking Detection**: Automatically handles Spotify's track versioning and remastering  
- 🎯 **Multi-Stage Resolution Pipeline**: Direct lookup → Search fallback → Metadata preservation
- 📊 **Rich Resolution Analytics**: Detailed statistics showing exactly how tracks were resolved
- 💪 **Future-Proof Design**: Handles any age of Spotify export (2011+) with zero data loss
- 🎵 **Play History Import**: Import comprehensive play history from Spotify GDPR exports
- 💾 **Enhanced Repository Layer**: Robust data access with batch operations and type safety
- 🔗 **Cross-Service Sync**: Complete likes synchronization between Spotify and Last.fm
- 📈 **Incremental Sync**: Efficient timestamp-based incremental likes export for large libraries

### Architecture Foundation (v0.2.3)
- 🏗️ **Clean Architecture**: Restructured for maintainability and future web interface
- ⚡ **Performance**: Domain tests run 10x faster with isolated business logic
- 🔧 **Dependency Injection**: Technology-agnostic business logic ready for web API
- 🧪 **130 Tests Passing**: Comprehensive test coverage across all architectural layers

### User Experience
- 🎨 **Modern CLI Design**: Beautiful Rich-formatted interface with color-coded panels
- ⚡ **Direct Workflow Commands**: Run `narada discovery_mix` instead of verbose commands  
- 🗂️ **Flattened CLI Structure**: Clear command names like `import-spotify-plays`, `export-likes-to-lastfm`
- 🔧 **Workflow Alias**: Short `wf` alias for workflow management (`narada wf list`)
- 📋 **Single Help System**: Consolidated help showing all commands with descriptive names
- 🏷️ **Version Display**: Automatic version detection throughout the CLI
- 📦 **Organized Panels**: System, Data Sync, and Playlist Workflow sections
- ✅ **Shell Completion**: Tab completion for commands and workflow names

## Getting Started

### Installation

```bash
# Clone the repository
git clone https://github.com/w-ash/narada.git
cd narada

# Install dependencies with Poetry
poetry install

# Activate virtual environment
source $(poetry env info --path)/bin/activate
```

### Setup

Run the setup command to configure your music service connections:

```bash
narada setup
```

This will guide you through connecting your Spotify and Last.fm accounts.

### Basic Commands

```bash
# Single help system showing all commands
narada --help

# Check service connection status
narada status

# Data sync commands with clear names
narada import-spotify-plays data/spotify_export.json
narada import-spotify-likes --limit 1000
narada export-likes-to-lastfm

# Run workflows directly (new in v0.2.1!)
narada discovery_mix
narada sort_by_release_date

# Short alias for workflow management
narada wf list
narada wf run

# Quick version check
narada version
```

### Enhanced Spotify Track Resolution (v0.2.2)

Narada achieves **100% processing rate** for Spotify exports of any age:

#### Multi-Stage Resolution Pipeline
- **Stage 1**: Direct API lookup with automatic relinking detection (90%+ success)
- **Stage 2**: Metadata-based search fallback using confidence scoring (≥70% threshold)  
- **Stage 3**: Metadata preservation for complete data preservation (100% coverage)

#### Real-World Benefits
- **Handles any age of Spotify export** - from 2011 to present day
- **Zero data loss** - every play gets imported and tracked
- **Smart relinking detection** - automatically handles Spotify's track versioning
- **Rich visibility** - see exactly how each track was resolved

#### Example Resolution Output
```
📊 Enhanced Resolution Results:
   Resolution rate: 100.0%
   Direct ID: 2        (tracks found as-is)
   Relinked ID: 8     (tracks updated by Spotify)
   Search match: 0     (metadata-based fallback)
   Preserved metadata: 0  (unresolvable but saved)
   Total with track ID: 10
```

### Clean Architecture Foundation (v0.2.3)

Narada was restructured to Clean Architecture patterns to enable future expansion:

#### Technical Foundation
- **Domain Layer**: Pure business logic with zero external dependencies
- **Application Layer**: Use case orchestrators with dependency injection
- **Infrastructure Layer**: External services and interfaces
- **Performance**: Domain tests run 10x faster without database dependencies

#### Benefits for Users
- **Future Web Interface**: Foundation laid for web-based management alongside CLI
- **Faster Development**: New features can be added more quickly and safely
- **Better Testing**: More reliable tests lead to fewer bugs
- **Extensibility**: Easy to add new music services and interfaces

### Modern CLI Experience

Narada features a beautiful, modern CLI with Rich-formatted output and intuitive navigation:

#### Visual Interface
- **Rich panels** with color-coded sections and emoji icons
- **Professional typography** with proper spacing and visual hierarchy  
- **Automatic version display** throughout the interface
- **Single help system** - `narada` shows comprehensive help

#### Flattened Command Structure
- **Descriptive names**: `import-spotify-plays`, `export-likes-to-lastfm` 
- **No nested commands**: All commands available at top level
- **Clear purpose**: Command names describe exactly what they do
- **Direct workflow execution**: `narada discovery_mix` (no more verbose commands!)
- **Short alias available**: `narada wf list` and `narada wf run`
- **Direct workflow execution** with simple command names

## Workflow System

Narada uses a powerful workflow system to create and transform playlists. Workflows are defined in JSON files and processed through a directed acyclic graph (DAG) of nodes.

### Running Workflows

Narada's workflow system features direct execution and rich visual feedback:

```bash
# Single help system shows all available commands and workflows
narada --help

# Data sync with descriptive command names
narada import-spotify-plays /path/to/spotify_export.json
narada import-spotify-likes --limit 500
narada export-likes-to-lastfm --batch-size 100

# Run workflows directly - no complex commands needed!
narada discovery_mix
narada sort_by_release_date

# Or use the workflow management interface
narada wf list              # List all workflows
narada wf run               # Interactive runner
```

#### Features

- **Direct Execution**: Run any workflow as a top-level command
- **Rich Progress Display**: Real-time progress tracking with visual feedback
- **Professional Output**: Beautiful tables and panels with color coding
- **Error Handling**: Clear error messages with helpful context
- **Auto-discovery**: New workflows automatically become available as commands

### Workflow Definition

Create custom workflows by defining JSON files in the definitions directory:

```json
{
  "id": "my_workflow",
  "name": "My Custom Workflow",
  "description": "Creates a personalized playlist based on my preferences",
  "version": "1.0",
  "tasks": [
    {
      "id": "source_playlist",
      "type": "source.spotify_playlist",
      "config": {
        "playlist_id": "spotify_playlist_id_here"
      }
    },
    {
      "id": "filter_recent",
      "type": "filter.by_release_date",
      "config": {
        "max_age_days": 90
      },
      "upstream": ["source_playlist"]
    },
    {
      "id": "destination",
      "type": "destination.create_spotify_playlist",
      "config": {
        "name": "My Recent Discoveries",
        "description": "Recently released tracks I might like"
      },
      "upstream": ["filter_recent"]
    }
  ]
}
```

### Available Node Types

- **Sources**: Fetch tracks from Spotify playlists
- **Filters**: Filter tracks by various criteria (date, duplicates, etc.)
- **Enrichers**: Add metadata from Last.fm and other services
- **Sorters**: Sort tracks by popularity, play count, etc.
- **Combiners**: Merge, concatenate, or interleave playlists
- **Selectors**: Limit tracks based on various criteria
- **Destinations**: Create or update playlists in Spotify or internal database

See the Workflow Guide for a complete reference of available nodes and configuration options.

## Example Workflows

### Discovery Mix

The `discovery_mix` workflow creates a playlist of new releases from multiple curated sources:

1. Fetches tracks from multiple Spotify playlists (Pollen, Serotonin, Metropolis, Stereogum)
2. Filters each source to tracks released within the last 90 days
3. Limits each source to a specified number of tracks
4. Combines all sources and sorts by popularity
5. Appends Release Radar tracks at the beginning
6. Removes duplicates and tracks already in other playlists
7. Creates a new Spotify playlist with the results

Run this workflow with:

```bash
narada discovery_mix
```

## Architecture

Narada is built for reliability and performance:

- **Fast**: Optimized batch processing and async operations
- **Reliable**: Comprehensive error handling and data validation
- **Extensible**: Plugin-based workflow system for custom transformations
- **Type-Safe**: Full typing support for better development experience

## Development

### Project Structure

```
narada/
├── src/                 # Core application code
│   ├── domain/         # Business logic and entities
│   ├── application/    # Use cases and workflows
│   └── infrastructure/ # External services and CLI
├── docs/               # Documentation and guides
├── tests/              # Test suite
└── scripts/            # Utility scripts
```

### Development Commands

```bash
# Run tests
poetry run pytest

# Run tests with coverage  
poetry run pytest --cov=narada --cov-report=html

# Lint and format code
poetry run ruff check --fix .
poetry run ruff format .

# Type checking
poetry run pyright narada/

# Run integration tests only
poetry run pytest -m integration

# Test the modern CLI
narada --help                           # See the unified help interface
narada import-spotify-plays --help     # Test flattened sync commands
narada discovery_mix --help            # Test direct workflow commands
narada wf list                         # Test the alias functionality
```

### Code Style

- Python 3.13+ with modern typing features
- Line length: 88 characters (enforced by Ruff)
- Immutable domain models using attrs
- Repository pattern for all data access
- Batch-first design for all operations
- UTC timezone for all datetime objects

### Contributing

1. Fork the repository
2. Create a feature branch
3. Follow the coding standards in CLAUDE.md
4. Add comprehensive tests
5. Run linting and type checking
6. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.