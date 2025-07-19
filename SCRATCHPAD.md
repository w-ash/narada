# Narada v0.2.4: Playlist Workflow Expansion - Architectural Implementation Plan

**Version**: 0.2.4  
**Initiative**: Playlist Workflow Expansion  
**Goal**: Enable advanced playlist workflows with play history analysis while completing Clean Architecture foundation  
**Status**: Planning Phase  

---

## 🎯 Executive Summary

v0.2.4 represents a critical architectural maturation phase that must **complete the Clean Architecture foundation** before adding new functionality. This dual focus ensures that new play history and workflow capabilities are built on solid architectural principles while addressing existing technical debt.

**Core Principle**: *Foundation First, Features Second* - No new functionality until architectural integrity is complete.

---

## 🏗️ Current Architecture Assessment

### ✅ Strengths (Maintain & Leverage)
- **Clean Architecture Structure**: Proper Domain/Application/Infrastructure separation
- **Modern Python 3.13 Patterns**: Future-ready type system and language features  
- **Comprehensive Testing**: 509 passing tests with good coverage
- **Workflow Foundation**: Solid node-based transformation system
- **Repository Pattern**: Established but incomplete dependency injection
- **DRY Implementation**: Zero redundancy across major components

### ⚠️ Critical Gaps (Must Address)
- **Incomplete Dependency Inversion**: Use cases create concrete instances vs receiving interfaces
- **Type Safety Violations**: `Any` types in domain interfaces breaking type contracts
- **Data Flow Confusion**: Matching and enrichment conflated in single service
- **Architectural "Hacks"**: LazyRepositoryProvider circumvents proper DI patterns
- **Incomplete Implementations**: UpdatePlaylistUseCase contains placeholder TODOs

---

## 🔧 Technical Debt Resolution Strategy

### Phase 1: Repository Pattern Completion (Foundation)
**Priority**: CRITICAL - Prerequisite for all other work
**Target**: True dependency inversion in use cases

```python
# Current (PROBLEM):
class SavePlaylistUseCase:
    async def execute(self, ...):
        async with get_session() as session:  # Direct coupling
            repo = TrackRepository(session)   # Creates concrete instance
            
# Target (SOLUTION):  
class SavePlaylistUseCase:
    def __init__(self, track_repo: TrackRepositoryProtocol, ...):  # Dependency injection
        self.track_repo = track_repo
```

**Benefits**:
- 100% testable business logic (no database mocking)
- Technology-agnostic use cases
- Proper Clean Architecture compliance
- Foundation for rapid feature development

### Phase 2: Service Layer Clarification
**Priority**: HIGH - Enables efficient data flow
**Target**: Separate identity resolution from metadata enrichment

```python
# Current (PROBLEM):
class MatcherService:
    async def match_tracks(self, tracks):
        # Conflates identity resolution + metadata enrichment
        
# Target (SOLUTION):
class TrackIdentityResolver:        # NEW - Handles unknown tracks
    async def resolve_identity(self, unknown_tracks) -> list[TrackMatch]
    
class TrackMetadataEnricher:        # NEW - Refreshes known tracks  
    async def enrich_metadata(self, known_tracks) -> list[Track]
```

**Benefits**:
- Clear separation of expensive vs cheap operations
- No re-matching of known tracks
- Explicit data flow for different track states
- Simplified MetadataFreshnessController logic

### Phase 3: Playlist Command Clarification  
**Priority**: MEDIUM - Enables clear responsibility boundaries
**Target**: Single responsibility for playlist operations

```python
# Current (PROBLEM):
class SavePlaylistUseCase:
    # Handles both creation AND updates
    
# Target (SOLUTION):
class PersistPlaylistUseCase:       # RENAMED - Database persistence only
    async def persist(self, playlist: Playlist) -> Playlist
    
class UpdatePlaylistUseCase:        # FOCUSED - External service updates only  
    async def update_external(self, diff: PlaylistDiff) -> UpdateResult
```

---

## 🎨 Architectural Vision for Play History Integration

### Design Principle: *Composition over Extension*
New play history capabilities should **compose existing patterns** rather than creating new architectural concepts.

### Transformation Node Pattern Extension
```python
# Leverage existing TRANSFORM_REGISTRY pattern:
@register_transform("filter.play_count")
class PlayCountFilter(FilterTransform):
    """Filter tracks by play count thresholds."""
    
@register_transform("sort.last_played") 
class LastPlayedSorter(SortTransform):
    """Sort tracks by recency of last play."""
    
@register_transform("discover.seasonal")
class SeasonalDiscovery(FilterTransform):
    """Find tracks played heavily in specific time periods."""
```

**Benefits**:
- Zero new architectural concepts
- Leverages existing workflow infrastructure  
- Maintains DRY principles across transformations
- Easy to test and compose

### Play History Data Flow
```python
# Clean data flow for play analysis:
PlayHistorySource -> PlayMetricsCalculator -> TransformationNodes -> PlaylistDestination
```

**Key Insight**: Play history is just another data source that feeds into the existing transformation pipeline.

---

## 🚀 Implementation Strategy

### Pre-Development Checklist
**CRITICAL**: These steps must be completed before any new feature work:

1. **✅ Format & Lint**: `ruff format . && ruff check . --fix`
2. **✅ Type Check**: `poetry run pyright src/` (zero errors required)
3. **✅ Test Suite**: `poetry run pytest` (all tests passing)
4. **✅ Architecture Review**: Confirm Clean Architecture compliance

### Development Workflow
1. **Technical Debt First**: Complete architectural foundation
2. **Pattern Establishment**: Create clear patterns for new functionality
3. **Incremental Implementation**: Add capabilities following established patterns
4. **Continuous Validation**: Maintain architectural integrity at each step

---

## 📐 DRY Principles Application

### Unified Progress Reporting Pattern
```python
# Current state: Inconsistent progress reporting across operations
# Target: Single interface for all long-running operations

class ProgressReporter(Protocol):
    async def report(self, current: int, total: int, message: str) -> None
        
# Apply to all operations:
- Track matching progress
- Playlist sync progress  
- Play history import progress
- Workflow execution progress
```

### Transformation Pattern Consistency
```python
# Maintain consistent transformation signatures:
async def transform_fn(
    context: WorkflowContext,
    config: TransformConfig
) -> TrackList

# Never deviate from this pattern - ensures composability
```

### Error Handling Standardization
```python
# Unified error handling across all operations:
@resilient_operation("operation_name")
async def operation(...) -> OperationResult
    # Consistent error handling, logging, and retry logic
```

---

## 📋 Detailed Implementation Plan

### Sprint 1: Architectural Foundation (2-3 days)
**Goal**: Complete Clean Architecture implementation

#### 1.1 Repository Interface Type Safety
- [ ] Replace `Any` types with proper domain entity forward references
- [ ] Update all repository protocols with correct typing
- [ ] Verify pyright passes with strict type checking

#### 1.2 Use Case Dependency Inversion  
- [ ] Define repository protocols in domain layer
- [ ] Refactor SavePlaylistUseCase to accept interfaces
- [ ] Refactor UpdatePlaylistUseCase to accept interfaces
- [ ] Update workflow context to provide proper DI
- [ ] Remove LazyRepositoryProvider "hack"

#### 1.3 Service Layer Clarification
- [ ] Create TrackIdentityResolver for unknown track matching
- [ ] Create TrackMetadataEnricher for known track refreshing
- [ ] Refactor existing MatcherService consumers
- [ ] Update MetadataFreshnessController logic

### Sprint 2: UpdatePlaylistUseCase Completion (2-3 days)
**Goal**: Production-ready playlist update functionality

#### 2.1 Sophisticated Reordering Logic (TODO #123)
- [ ] Implement optimal track reordering algorithm
- [ ] Add position optimization for minimal API calls
- [ ] Include track addition timestamp preservation

#### 2.2 ISRC/Metadata Matching (TODO #124)  
- [ ] Extend matching beyond Spotify ID
- [ ] Add ISRC-based track identification
- [ ] Implement metadata-based fallback matching

#### 2.3 Actual Spotify API Operations (TODO #125)
- [ ] Replace playlist creation with track add/remove/reorder
- [ ] Implement proper Spotify API differential updates
- [ ] Add comprehensive error handling and retries

### Sprint 3: Play History Foundation (2-3 days)
**Goal**: Establish patterns for play history functionality

#### 3.1 Play History Transformation Nodes (BACKLOG: Play History Filter and Sort)
- [ ] Create PlayCountFilter following existing filter patterns
  - [ ] Enable play count filtering (e.g., tracks played >10 times, <5 times)
  - [ ] Support time-period analysis (e.g., tracks played >5 times in July 2024)
- [ ] Create LastPlayedSorter following existing sort patterns  
  - [ ] Add play recency sorting (most/least recently played)
  - [ ] Include relative time periods (last 30 days, past week, this month)
- [ ] Create SeasonalDiscovery for time-period analysis
  - [ ] Build on existing metric-based filtering patterns
- [ ] Register all new transforms in TRANSFORM_REGISTRY
- [ ] Leverage existing filter/sorter architecture patterns

#### 3.2 Unified Progress Reporting
- [ ] Create ProgressReporter protocol
- [ ] Implement console progress reporter with Rich
- [ ] Update all long-running operations to use unified progress
- [ ] Add ETA calculations and operation-specific details

### Sprint 4: Advanced Playlist Capabilities (2-3 days)
**Goal**: Enhanced playlist workflow features

#### 4.1 Advanced Transformer Nodes (BACKLOG: Advanced Transformer Workflow nodes)
- [ ] Implement combining operations with different strategies
- [ ] Add time-based transformers (seasonal, time of day)
- [ ] Include randomization with optional weighting for sorting a playlist
- [ ] Include selection of just the first X or last X from a tracklist

#### 4.2 Enhanced Playlist Naming (BACKLOG: Enhanced Playlist Naming)
- [ ] Support template parameters in playlist names
- [ ] Allow using source playlist names in new playlist names/descriptions
- [ ] Add the ability to append date/time to names and descriptions
- [ ] Implement metadata insertion into descriptions
- [ ] Add validation to prevent invalid characters

---

## 🧪 Testing Strategy & Pyramid Implementation

### Test Pyramid Architecture (Clean Architecture Alignment)
```
           /\     E2E CLI Tests (5-10%)
          /  \    tests/cli/ - End-to-end user scenarios
         /____\   
        /      \  Integration Tests (15-20%)
       /        \ tests/application/ - Use case integration
      /          \tests/infrastructure/ - External service tests
     /____________\
    Unit Tests (70-80%)
    tests/domain/ - Fast business logic tests
```

### Layer-Specific Testing Strategy

#### Domain Layer Tests (Unit - Fast & Isolated)
```bash
poetry run pytest tests/domain/  # Target: <100ms total
```
**Focus Areas**:
- [ ] Business logic validation (Track, Playlist entities)
- [ ] Transform functions (filters, sorters, combiners) 
- [ ] Matching algorithms and confidence calculations
- [ ] Domain service orchestration logic
- [ ] Error handling and edge cases

**Testing Principles**:
- **Fast**: <1ms per test, no I/O operations
- **Isolated**: Pure functions, no database/network
- **Deterministic**: Same result every time
- **Focused**: One behavior per test

#### Application Layer Tests (Integration - Use Case Orchestration)
```bash
poetry run pytest tests/application/  # Target: <5s total
```
**Focus Areas**:
- [ ] Use case orchestration (SavePlaylistUseCase, UpdatePlaylistUseCase)
- [ ] Repository interface contracts
- [ ] Service coordination and data flow
- [ ] Dependency injection patterns
- [ ] Cross-component integration

**Testing Approach**:
- **Real Dependencies**: Use actual repository implementations
- **Test Database**: In-memory SQLite for speed
- **Interface Validation**: Ensure protocols are correctly implemented
- **Data Flow**: Verify end-to-end data transformations

#### Infrastructure Layer Tests (Integration - External Boundaries)
```bash
poetry run pytest tests/infrastructure/  # Target: <10s total
```
**Focus Areas**:
- [ ] Database repository operations (CRUD, queries)
- [ ] External API integrations (Spotify, Last.fm, MusicBrainz)
- [ ] Connector implementations and rate limiting
- [ ] File I/O operations and data parsing
- [ ] Configuration and environment handling

**Testing Strategy**:
- **Contract Testing**: Verify external API assumptions
- **Database Testing**: Real SQLite operations with test data
- **Error Simulation**: Network failures, rate limits, invalid responses
- **Performance Validation**: Ensure acceptable response times

#### CLI Layer Tests (E2E - User Experience)
```bash
poetry run pytest tests/cli/  # Target: <30s total
```
**Focus Areas**:
- [ ] Command-line interface behavior
- [ ] User workflow scenarios
- [ ] Progress reporting and error messages
- [ ] Configuration management
- [ ] Output formatting and validation

### TDD Implementation Strategy for v0.2.4

#### Sprint 1: Architectural Foundation TDD
```python
# 1. Write failing domain test
def test_track_repository_protocol_type_safety():
    # Test proper typing without Any usage
    assert False  # RED

# 2. Implement minimal code
class TrackRepositoryProtocol(Protocol):
    async def find_by_id(self, track_id: int) -> Track | None: ...
    # GREEN

# 3. Refactor with full implementation
# REFACTOR - Complete type safety across all protocols
```

#### Sprint 2: UpdatePlaylistUseCase TDD
```python
# Test sophisticated reordering logic (TODO #123)
def test_playlist_reordering_minimizes_api_calls():
    # Test optimal reordering algorithm
    assert calculate_reorder_operations(current, target) == expected_minimal_ops

# Test ISRC matching (TODO #124)
def test_isrc_matching_fallback():
    # Test ISRC-based track identification
    assert match_by_isrc(track_without_spotify_id) == expected_match

# Test actual Spotify operations (TODO #125)
def test_spotify_differential_update():
    # Test real Spotify API operations vs playlist creation
    assert update_playlist_tracks(diff) == UpdateResult.SUCCESS
```

#### Sprint 3: Play History TDD
```python
# Domain tests for new transformations
def test_play_count_filter_applies_threshold():
    tracks_with_plays = create_test_tracks_with_play_counts([5, 15, 2])
    filtered = PlayCountFilter(min_plays=10).transform(tracks_with_plays)
    assert len(filtered.tracks) == 1  # Only track with 15 plays

# Application tests for integration
def test_play_history_workflow_integration():
    workflow = build_play_history_workflow()
    result = await execute_workflow(workflow, test_context)
    assert result.success and len(result.tracks) > 0
```

### Testing Quality Gates

#### Pre-Development Validation
- **✅ All Tests Pass**: `poetry run pytest` (0 failures, 0 skipped)
- **✅ Type Safety**: `poetry run pyright src/` (0 errors)
- **✅ Code Quality**: `ruff check . --fix` (0 violations)

#### Development Workflow (TDD Cycle)
1. **RED**: Write failing test for new functionality
2. **GREEN**: Write minimal code to pass the test
3. **REFACTOR**: Improve code while keeping tests green
4. **VALIDATE**: Run full test suite + type checking

#### Post-Sprint Validation
- **✅ Test Coverage**: >90% on domain layer, >80% on application layer
- **✅ Performance**: Domain tests <100ms, application tests <5s
- **✅ Architecture**: Tests validate Clean Architecture principles
- **✅ Integration**: All layers tested at appropriate boundaries

### Testing Infrastructure Updates for v0.2.4

#### Enhanced Test Fixtures
```python
# Domain layer test builders
@pytest.fixture
def sample_track_with_plays():
    return create_track_with_play_history(play_count=10, last_played=yesterday())

# Application layer test context
@pytest.fixture
async def use_case_context():
    return create_test_context_with_real_repos()

# Infrastructure layer test database
@pytest.fixture
async def test_database():
    return create_in_memory_test_database()
```

#### Parallel Test Execution
```bash
# Fast feedback during development
poetry run pytest tests/domain/ -x      # Stop on first failure
poetry run pytest tests/application/ -v # Verbose output for integration
poetry run pytest --tb=short           # Concise error output
```

#### Continuous Validation
```bash
# Pre-commit validation script
poetry run pytest tests/domain/ tests/application/ && \
poetry run pyright src/ && \
ruff check . --fix
```

---

## 🎯 Success Metrics

### Technical Quality Gates
- **✅ Zero Type Errors**: `poetry run pyright src/` passes completely
- **✅ Zero Test Failures**: All 509+ tests pass consistently  
- **✅ Zero Technical Debt**: All TODO markers resolved or documented
- **✅ Clean Architecture Compliance**: Full dependency inversion achieved

### Feature Completeness Gates
- **✅ Production Playlist Updates**: UpdatePlaylistUseCase handles real Spotify operations
- **✅ Play History Integration**: New transformation nodes functional and tested
- **✅ Unified Progress**: Consistent progress reporting across all operations
- **✅ Discovery Templates**: Pre-built workflows demonstrate new capabilities

### Maintainability Gates  
- **✅ Pattern Consistency**: All new code follows established patterns
- **✅ DRY Compliance**: Zero code duplication in new functionality
- **✅ Documentation Complete**: BACKLOG.md updated with completed work
- **✅ Test Coverage**: >90% coverage maintained on new functionality

---

## 🔍 Architectural Decision Records

### ADR-001: Repository Pattern Completion
**Decision**: Complete dependency inversion for all use cases before new features
**Rationale**: Foundation must be solid before building new capabilities
**Impact**: Dramatically improves testability and architectural clarity

### ADR-002: Service Layer Separation  
**Decision**: Separate identity resolution from metadata enrichment
**Rationale**: Different performance characteristics and data flow requirements
**Impact**: More efficient processing and clearer component responsibilities

### ADR-003: Transformation Pattern Reuse
**Decision**: New play history features use existing transformation patterns
**Rationale**: Maintains architectural consistency and leverages existing infrastructure
**Impact**: Faster development and consistent user experience

### ADR-004: Progress Reporting Unification
**Decision**: Single progress interface across all operations
**Rationale**: Consistent user experience and simplified implementation
**Impact**: Better user feedback and reduced code duplication

---

## 🎉 Expected Outcomes

Upon completion of v0.2.4, the system will have:

1. **Architectural Maturity**: Complete Clean Architecture implementation with proper dependency inversion
2. **Feature Richness**: Advanced play history analysis and playlist workflow capabilities  
3. **Technical Excellence**: Zero technical debt and consistent architectural patterns
4. **User Experience**: Unified progress reporting and discovery workflow templates
5. **Developer Productivity**: Clear patterns for future feature development
6. **Maintainability**: Compact, understandable codebase following DRY principles

**Strategic Result**: A solid foundation ready for FastAPI web interface development and advanced streaming service integrations in future versions.

---

*"Architecture is about the important stuff... whatever that is." - Ralph Johnson*

In v0.2.4, the "important stuff" is completing our architectural foundation while adding powerful new capabilities that maintain our system's elegance and maintainability.