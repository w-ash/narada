# Narada

Narada is a music playlist integration platform that connects multiple music services (Spotify, Last.fm, MusicBrainz) to create and backup playlists through customizable workflows.

## Features

- **Music Service Integration**: Connect with Spotify, Last.fm, and MusicBrainz
- **Workflow System**: Define complex playlist transformation pipelines using JSON
- **Smart Filtering**: Filter tracks by release date, artist, popularity, and more
- **Rich CLI Interface**: Interactive command-line tools with progress tracking
- **Data Persistence**: Store and manage playlists in local database and Spotify

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
# Check service connection status
narada status

# Run a workflow
narada workflow [workflow_id]

# View available commands
narada --help
```

## Workflow System

Narada uses a powerful workflow system to create and transform playlists. Workflows are defined in JSON files and processed through a directed acyclic graph (DAG) of nodes.

### Running Workflows

The improved workflow system features a rich interactive interface:

```bash
# List all available workflows
narada workflow

# Run a specific workflow
narada workflow discovery_mix
```

#### New Features

- **Interactive Workflow Selection**: Choose from available workflows with a simple menu
- **Real-time Progress Tracking**: Track workflow execution with a progress bar
- **Task Completion Monitoring**: See status updates for each completed node
- **Track Count Display**: View the number of tracks processed at each step
- **Error Reporting**: Clear error messages when workflows encounter problems

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
narada workflow discovery_mix
```

## Architecture

Narada follows clean architecture principles with:

- **Immutable Domain Models**: Core entities using attrs with frozen=True for data integrity
- **Repository Pattern**: Abstracts data access with batch-first design
- **Functional Transformations**: Pure functions with no side effects using toolz
- **Async Operations**: SQLAlchemy 2.0 with async/await for database operations
- **Type Safety**: Comprehensive typing with Pyright and modern Python 3.13+ features

## Development

### Project Structure

```
narada/
├── narada/
│   ├── cli/             # Command line interface
│   ├── core/            # Core domain models and protocols
│   ├── database/        # Database models and migrations
│   ├── integrations/    # Music service connectors (Spotify, Last.fm, MusicBrainz)
│   ├── repositories/    # Data access layer with repository pattern
│   ├── services/        # Business logic services
│   └── workflows/       # Workflow system with Prefect
├── docs/                # Documentation and guides
├── tests/               # Test suite
└── scripts/             # Utility scripts
```

### Development Commands

```bash
# Run tests
pytest

# Run tests with coverage
pytest --cov=narada

# Lint and format code
ruff check --fix .
ruff format .

# Type checking
poetry run pyright narada/

# Run integration tests only
pytest -m integration
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