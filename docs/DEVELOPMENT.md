# Narada Development Guide

## Getting Started

### Prerequisites
- Python 3.13+
- Poetry (dependency management)
- Git

### Initial Setup

1. **Clone and Install**
   ```bash
   git clone <repository-url>
   cd narada
   poetry install
   source $(poetry env info --path)/bin/activate
   ```

2. **Configure Environment**
   ```bash
   cp .env.example .env
   # Edit .env with your service credentials
   ```

3. **Initialize Database**
   ```bash
   poetry run alembic upgrade head
   ```

4. **Verify Installation**
   ```bash
   poetry run pytest
   poetry run narada --help
   ```

## Development Workflow

### Core Commands
See `CLAUDE.md` for the complete reference. Key commands:

```bash
# Development
poetry run pytest                               # Run all tests
poetry run pytest tests/unit/                  # Run unit tests only
poetry run pytest tests/integration/           # Run integration tests only
poetry run pytest --cov=narada --cov-report=html # Coverage report

# Code Quality
ruff check . --fix                             # Lint and auto-fix
ruff format .                                  # Format code
poetry run pyright src/                        # Type check

# Database
poetry run alembic revision --autogenerate     # Generate migration
poetry run alembic upgrade head                # Apply migrations
```

### Pre-commit Workflow
Always run before committing:
```bash
ruff format .
ruff check . --fix
poetry run pyright src/
poetry run pytest
```

## Project Structure

### Clean Architecture Layers

```
src/
├── domain/                   # Pure business logic (no external dependencies)
│   ├── entities/             # Core business objects
│   ├── matching/             # Track matching algorithms
│   └── transforms/           # Functional transformation pipelines
│
├── application/              # Use cases and orchestration
│   ├── services/             # Use case orchestrators
│   ├── utilities/            # Shared application utilities
│   └── workflows/            # Business workflow definitions
│
└── infrastructure/           # External implementations
    ├── cli/                  # Command line interface
    ├── connectors/           # External service integrations
    ├── persistence/          # Data access layer
    └── services/             # Infrastructure-level services
```

### Key Files to Understand

#### Domain Layer (Start Here)
- `src/domain/entities/track.py` - Core Track and Artist entities
- `src/domain/entities/playlist.py` - Playlist and TrackList entities
- `src/domain/matching/algorithms.py` - Track matching logic
- `src/domain/transforms/core.py` - Functional transformation primitives

#### Application Layer
- `src/application/use_cases/` - Business logic orchestration
- `src/application/workflows/node_catalog.py` - Workflow node registry
- `src/application/workflows/prefect.py` - Workflow execution engine

#### Infrastructure Layer
- `src/infrastructure/cli/app.py` - CLI entry point
- `src/infrastructure/connectors/` - External service integrations
- `src/infrastructure/persistence/repositories/` - Data access implementations

## Architecture Patterns

### 1. Clean Architecture
Dependencies flow inward: Infrastructure → Application → Domain

```python
# Domain (no external dependencies)
@dataclass
class Track:
    title: str
    artists: list[str]
    
# Application (depends on domain)
class ImportTracksUseCase:
    def __init__(self, repository: TrackRepository):
        self.repository = repository
    
    async def execute(self, tracks: list[Track]) -> ImportResult:
        # Business logic here
        
# Infrastructure (depends on application)
class SpotifyConnector:
    async def get_tracks(self) -> list[Track]:
        # External API calls
```

### 2. Repository Pattern
Centralized data access with consistent interfaces:

```python
# Domain interface
class TrackRepository(Protocol):
    async def get_by_id(self, track_id: int) -> Track | None:
        ...
    
    async def save_batch(self, tracks: list[Track]) -> list[Track]:
        ...

# Infrastructure implementation
class SQLAlchemyTrackRepository:
    async def get_by_id(self, track_id: int) -> Track | None:
        # Database implementation
```

### 3. Command Pattern
Rich operation contexts with validation:

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

### 4. Strategy Pattern
Pluggable algorithms:

```python
class TrackMatchingStrategy(Protocol):
    async def match_tracks(self, tracks: list[Track]) -> list[MatchResult]:
        ...

class SpotifyTrackMatcher:
    async def match_tracks(self, tracks: list[Track]) -> list[MatchResult]:
        # Spotify-specific matching
```

## Testing Strategy

### Test Structure
```
tests/
├── unit/                     # Fast, isolated tests
│   ├── test_domain_*.py      # Domain layer tests (zero dependencies)
│   ├── test_application_*.py # Application layer tests
│   └── test_services/        # Legacy service tests
├── integration/              # Integration tests with external services
│   └── test_*.py
└── cli/                      # CLI command tests
    └── test_*.py
```

### Testing Patterns

#### Domain Tests (Fastest)
```python
def test_track_matching_confidence():
    # Pure unit tests, no dependencies
    algorithm = TrackMatchingAlgorithm()
    result = algorithm.calculate_confidence(track1, track2)
    assert result.confidence >= 0.8
```

#### Application Tests (Mocked Dependencies)
```python
@pytest.fixture
def mock_repository():
    return AsyncMock(spec=TrackRepository)

async def test_import_tracks_use_case(mock_repository):
    use_case = ImportTracksUseCase(mock_repository)
    result = await use_case.execute(tracks)
    assert result.success
```

#### Integration Tests (Real External Services)
```python
@pytest.mark.integration
async def test_spotify_connector():
    connector = SpotifyConnector()
    tracks = await connector.get_playlist_tracks("playlist_id")
    assert len(tracks) > 0
```

### Test Utilities
- `tests/fixtures/` - Test data builders
- `tests/conftest.py` - Shared fixtures
- Use `@pytest.mark.asyncio` for async tests

## Adding New Features

### 1. Domain-First Development
Start with domain entities and business logic:

```python
# 1. Domain entity
@dataclass
class NewEntity:
    name: str
    value: int

# 2. Domain repository interface
class NewEntityRepository(Protocol):
    async def save(self, entity: NewEntity) -> NewEntity:
        ...

# 3. Domain tests
def test_new_entity_creation():
    entity = NewEntity(name="test", value=42)
    assert entity.name == "test"
```

### 2. Application Layer
Add use cases and orchestration:

```python
# 1. Use case
class NewFeatureUseCase:
    def __init__(self, repository: NewEntityRepository):
        self.repository = repository
    
    async def execute(self, command: NewFeatureCommand) -> NewFeatureResult:
        # Business logic
        
# 2. Application tests
async def test_new_feature_use_case(mock_repository):
    use_case = NewFeatureUseCase(mock_repository)
    result = await use_case.execute(command)
    assert result.success
```

### 3. Infrastructure Layer
Implement external concerns:

```python
# 1. Repository implementation
class SQLAlchemyNewEntityRepository:
    async def save(self, entity: NewEntity) -> NewEntity:
        # Database implementation
        
# 2. CLI command
@app.command()
def new_feature():
    # CLI implementation
```

### 4. Integration
Wire everything together and add tests:

```python
# Integration test
@pytest.mark.integration
async def test_new_feature_end_to_end():
    # Test the complete flow
```

## Common Development Tasks

### Adding a New CLI Command

1. **Create Use Case**
   ```python
   # src/application/use_cases/new_feature.py
   class NewFeatureUseCase:
       async def execute(self, command: NewFeatureCommand) -> NewFeatureResult:
           # Implementation
   ```

2. **Create CLI Command**
   ```python
   # src/infrastructure/cli/new_commands.py
   @app.command()
   def new_feature():
       # CLI implementation
   ```

3. **Add to Main App**
   ```python
   # src/infrastructure/cli/app.py
   app.add_typer(new_commands.app, name="new")
   ```

### Adding a New Workflow Node

1. **Create Transform Function**
   ```python
   # src/application/workflows/transforms.py
   async def new_transform(tracklist: TrackList) -> TrackList:
       # Transform logic
   ```

2. **Register in Catalog**
   ```python
   # src/application/workflows/node_catalog.py
   @node("transformer.new_transform")
   async def handle_new_transform(tracklist: TrackList, config: dict) -> TrackList:
       return await new_transform(tracklist, **config)
   ```

### Adding External Service Integration

1. **Create Connector**
   ```python
   # src/infrastructure/connectors/new_service.py
   class NewServiceConnector:
       async def get_tracks(self) -> list[Track]:
           # API integration
   ```

2. **Add to Matching System**
   ```python
   # src/domain/matching/providers.py
   class NewServiceMatchingProvider:
       async def match_tracks(self, tracks: list[Track]) -> list[MatchResult]:
           # Matching logic
   ```

### Database Schema Changes

1. **Update Model**
   ```python
   # src/infrastructure/persistence/database/db_models.py
   class NewTable(NaradaDBBase):
       __tablename__ = "new_table"
       name: Mapped[str] = mapped_column(String)
   ```

2. **Generate Migration**
   ```bash
   poetry run alembic revision --autogenerate -m "Add new table"
   ```

3. **Review and Apply**
   ```bash
   # Review generated migration file
   poetry run alembic upgrade head
   ```

## Code Style Guidelines

### General Principles
- **Ruthlessly DRY**: No code duplication
- **Clean Breaks**: No backward compatibility layers
- **Batch-First**: Design for N items, single operations are degenerate cases
- **Immutable Domain**: Pure transformations, no side effects

### Python Conventions
- Python 3.13+ features (match statements, modern type syntax)
- Type everything: domain models, return types, generics
- Double quotes for strings
- Google-style docstrings
- Line length: 88 characters

### Architecture Conventions
- One class per file in domain models
- Never put business logic in CLI
- Use dependency injection for testability
- Functional composition with toolz where appropriate

### Error Handling
- Use `@resilient_operation("name")` for external APIs
- Let exceptions bubble to service layer
- Log failures with context
- Chain exceptions: `raise Exception() from err`

## Debugging and Troubleshooting

### Common Issues

1. **Type Errors**
   ```bash
   poetry run pyright src/
   # Fix type issues before proceeding
   ```

2. **Test Failures**
   ```bash
   poetry run pytest -v --tb=short
   # Use -v for verbose output, --tb=short for concise tracebacks
   ```

3. **Database Issues**
   ```bash
   # Check migration status
   poetry run alembic current
   
   # Reset database
   rm data/narada.db
   poetry run alembic upgrade head
   ```

### Debugging Workflow Execution
```python
# Add debug logging to workflow nodes
logger = get_logger(__name__)
logger.info("Processing tracks", track_count=len(tracks))
```

### Performance Profiling
```python
# Use with long-running operations
import time
start = time.time()
# ... operation ...
logger.info("Operation completed", duration=time.time() - start)
```

## Contributing Guidelines

### Before Starting
1. Read this guide and `ARCHITECTURE.md`
2. Set up development environment
3. Run tests to ensure everything works
4. Check `BACKLOG.md` for current priorities

### Pull Request Process
1. Create feature branch from `main`
2. Implement changes following architecture patterns
3. Add tests for new functionality
4. Update documentation if needed
5. Run full test suite and linting
6. Create PR with clear description

### Code Review Checklist
- [ ] Follows Clean Architecture principles
- [ ] Has appropriate test coverage
- [ ] Passes all tests and linting
- [ ] Documentation updated if needed
- [ ] No breaking changes to existing APIs
- [ ] Error handling implemented properly

## Resources

### Documentation
- **[ARCHITECTURE.md](ARCHITECTURE.md)** - System architecture and design decisions
- **[DATABASE.md](DATABASE.md)** - Database schema and design reference
- **[API.md](API.md)** - Complete CLI command reference
- **[workflow_guide.md](workflow_guide.md)** - Workflow system documentation
- **[likes_sync_guide.md](likes_sync_guide.md)** - Likes synchronization between Spotify and Last.fm
- **[CLAUDE.md](../CLAUDE.md)** - Development commands and style guide
- **[BACKLOG.md](../BACKLOG.md)** - Project roadmap and priorities

### External Resources
- [SQLAlchemy 2.0 Documentation](https://docs.sqlalchemy.org/en/20/)
- [Typer Documentation](https://typer.tiangolo.com/)
- [Rich Documentation](https://rich.readthedocs.io/)
- [Prefect Documentation](https://docs.prefect.io/)

### Getting Help
- Check existing tests for usage patterns
- Review similar implementations in the codebase
- Consult [ARCHITECTURE.md](ARCHITECTURE.md) for design decisions
- Ask questions in pull request reviews