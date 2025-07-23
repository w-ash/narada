# Narada v0.2.4: Quality & Cleanup Initiative

**Vision**: Solidify the codebase by eliminating technical debt, fixing all tests, and cleaning up legacy patterns to create a stable foundation for future feature development outlined in `BACKLOG.md`.

**Current Status**: ✅ Critical runtime bugs fixed. ✅ Test suite infrastructure repaired. ✅ All failing tests fixed (620 passing, 1 skipped, 0 failures).

---

## ✅ COMPLETED: Green Build Achieved (0 Failing Tests)

**Context**: The test suite was critically broken with 59 failures due to recent architectural changes. All critical issues have been resolved and the build is now green with 620 tests passing, 1 skipped, 0 failures.

### Completed Fixes

- ✅ **Enricher Tests (3 failures)**: Fixed missing connector registry and repositories in test context for `tests/unit/test_enricher_key_types.py`
  - **Root Cause**: Tests created enricher nodes but didn't provide required `connectors` registry in context
  - **Solution**: Added mock connector registry and repositories to test context

- ✅ **Repository Test (1 failure)**: Fixed `tests/unit/test_repositories/test_track_repository.py::TestTrackRepository::test_find_tracks_by_ids_multiple_tracks`
  - **Root Cause**: Test used domain `Track` entities where `DBTrack` database models were expected by mapper
  - **Solution**: Updated test to use proper `DBTrack` models with correct data structure (`artists={"names": ["Artist 1"]}`)

### Quality Issues Identified (Non-Critical)

During the test fixes, several quality issues were discovered that align perfectly with the systematic architectural work already planned below:

- **Type system issues (10 errors)** - exactly the "Type System Anti-Patterns" cleanup in section 4 below
- **Repository protocol compatibility issues** - addressed by "Refactor Use Cases for True Dependency Inversion" in Future Work
- **Linting issues (125 warnings)** - mostly unused test parameters and broad exceptions  
- **Prefect logging I/O errors** - harmless but should be investigated

> **Recommendation**: Address these quality issues as part of the planned systematic cleanup phases rather than urgent patches.

---

## 🚀 Next Priority: Systematically Improve Test Quality

**Context**: The recent runtime failures were caused by a systemic testing anti-pattern where mocks were used to make broken code pass. Once the build is green, we must refactor tests to validate real component integrations and prevent this class of bugs from recurring. This phase is about moving from "tests that pass" to "tests that provide confidence".

### Implementation Plan

#### Phase 1: Eliminate Artificial Mocks (In Progress)

- **Goal**: Remove all instances of tests artificially patching objects (e.g., `mock_connector._connector = ...`). Tests must validate the real component's public interface.
- **Action**:
  - `⏳ [pending]` **Find and Replace**: Search the codebase for the `._connector` pattern in tests and refactor them to mock the public methods (e.g., `mock_connector.create_playlist.return_value = ...`). There are over 400 references to fix.
  - `⏳ [pending]` **Convert Integration Tests**: Refactor mock-heavy integration tests to use real components instantiated via `create_workflow_context()`, mocking only the outermost boundaries (external API clients).

#### Phase 2: Create DRY Test Fixtures (Pending)

- **Goal**: Reduce test code duplication and ensure consistent setup for integration tests.
- **Action**:
  - `⏳ [pending]` **Create Shared Fixtures**: Develop shared pytest fixtures that provide a real, working `WorkflowContext` for integration tests.
  - `⏳ [pending]` **Refactor Tests**: Update integration tests to use these new shared fixtures, promoting a consistent testing approach.

---

## 🧹 Final Phase: Codebase Cleanup

**Context**: With a stable and reliable test suite, the final step is to remove legacy code, placeholder implementations, and type system workarounds. This will complete the Clean Architecture migration and leave the codebase in an exceptionally clean state, ready for new feature development.

### High Priority - Remove Legacy Compatibility Layers

1. **Legacy CLI Aliases** (`src/infrastructure/cli/ui.py:285-287`): Remove `display_sync_stats` and `display_workflow_result` aliases. Update all callers to use `display_operation_result` directly.

2. **Legacy Protocol Properties** (`src/application/workflows/protocols.py:113-117`): Remove the deprecated `repositories` property from the `WorkflowContext` protocol.

3. **Legacy Comments** (`src/application/workflows/node_factories.py:58-61`): Remove outdated comment block about a removed legacy implementation.

### Medium Priority - Architectural & Type System Cleanup

4. **Type System Anti-Patterns** (Codebase-wide): This is a critical quality improvement.
   - **Action**: Find all uses of `cast()` and `Any` that are used to paper over typing issues.
   - **Goal**: Replace these type casts with proper interface alignment and fix the underlying type mismatches. Using `cast(SomeProtocol, broken_implementation)` hides architectural debt and must be eliminated.

5. **Placeholder Repository Provider** (`src/application/workflows/context.py`): The `PlaceholderRepositoryProvider` class within `create_workflow_context` is an acknowledged "hack" for backward compatibility.
   - **Goal**: Eliminate this placeholder by completing the "Refactor Use Cases for True Dependency Inversion" epic. Once use cases no longer create their own repositories, this placeholder will be obsolete.

6. **Incomplete Matching Provider** (`src/application/providers/concrete_matching_provider.py:51-80`): The track matching functionality may be non-functional. Either implement it properly or document it as an intentional minimal implementation.

7. **Backward Compatibility Comments** (Multiple files): Review if compatibility layers in `match_tracks.py` and `destination_nodes.py` are still needed. Remove them if possible.

### Low Priority - Documentation Cleanup

8. **Wrapper/Adapter References** (Multiple files): Update docstrings in connectors and other files to remove references to "wrapper" patterns and reflect the clean architecture.

---

## Future Work: Foundational Architectural Refinements (from BACKLOG.md)

**Context**: Once the codebase is stable and the test suite is green, the next phase is to complete the foundational architectural refinements outlined in the project backlog. This will fully realize the benefits of the Clean Architecture and prepare the system for the "Playlist Workflow Expansion" features.

### Key Initiatives (Sequenced for Efficiency)

> **Architectural Note on Sequencing**: The following tasks are ordered to prevent rework. The `MatcherService` is refactored first to provide a stable interface. Then, the general dependency injection pattern is established. Finally, the `UpdatePlaylistUseCase` is completed, integrating with the new, stable components in a single step.

#### 1. Clarify Enrichment vs. Matching Data Flow

- **Goal**: Refactor the `MatcherService` to align with the superior, single-responsibility pattern established by the `TrackMetadataEnricher`.

- **Architectural Vision**: The system should have a clear distinction between *identity resolution* (finding a track's external ID) and *data enrichment* (fetching metadata for a known ID). The `MatcherService` should only do the former.

- **Action**:
  1. Refactor `MatcherService` to remove all internal data freshness logic (e.g., the `max_age_hours` parameter). Its sole responsibility should be to find connector IDs for tracks that don't have them.
  2. Create a new, lean `EnricherService` (or reuse components from `TrackMetadataEnricher`) that takes a list of tracks with known connector IDs and fetches their latest metadata.
  3. Update all callers of `MatcherService` to adopt the new, two-step flow: first call the matcher to resolve identities, then call the enricher to fetch data.

- **Why**: This eliminates redundant logic, makes the data flow explicit and efficient (by not re-matching known tracks), and brings the entire system's data access patterns into alignment with our best practices.

#### 2. Refactor Use Cases for True Dependency Inversion

- **Goal**: Make all Application Use Cases pure orchestrators that are 100% independent of the database, dramatically improving testability and adaptability.

- **Architectural Vision**: Use cases should depend only on *interfaces* (protocols) defined in the domain layer, not on concrete infrastructure implementations. This is the final, critical step to achieving true Clean Architecture.

- **Phased Implementation Plan** (to avoid "boiling the ocean"):

  1. **Phase 1: Define Core Protocols**: In the `src/domain/repositories/` directory, ensure all repository protocols (e.g., `PlaylistRepository`, `TrackRepository`) are clearly defined. This is a safe, non-breaking first step.

  2. **Phase 2: Refactor a Pilot Use Case (`UpdatePlaylistUseCase`)**:
     - **Objective**: Prove the dependency inversion pattern on a single, representative use case.
     - **Action (Use Case)**: Modify `UpdatePlaylistUseCase.__init__` to accept a `playlist_repo` that conforms to the `PlaylistRepository` protocol.
     - **Action (Wiring)**: Update `UseCaseProviderImpl` to instantiate the concrete `SQLAlchemyPlaylistRepository` and inject it into the `UpdatePlaylistUseCase`.
     - **Action (Testing)**: Update the tests for `UpdatePlaylistUseCase` to inject a mock repository object that implements the `PlaylistRepository` protocol. This eliminates the need to mock database sessions in tests.

  3. **Phase 3: Roll Out to Remaining Use Cases**:
     - **Objective**: Apply the now-proven pattern to other key use cases.
     - **Action**: Repeat the refactoring process for `SavePlaylistUseCase` and any other services that directly instantiate repositories.

- **Why**: This incremental approach delivers value at each step, reduces risk, and establishes a clear, repeatable pattern for modernizing the entire application layer.

#### 3. Complete UpdatePlaylistUseCase Implementation

- **Goal**: Evolve `UpdatePlaylistUseCase` from a diff *calculator* into a fully-featured, production-ready diff *executor* that can intelligently synchronize playlists.

- **Architectural Vision**: The use case should be the single source of truth for all differential playlist updates. It must correctly calculate, sequence, and execute operations (ADD, REMOVE, MOVE) against both the internal database representation and external services like Spotify, while remaining extensible.

- **Phased Implementation Plan**:

  1. **Phase 1: Solidify the Differential Algorithm (Internal Logic)**
     - **Objective**: Ensure the calculated `PlaylistDiff` is 100% accurate before touching external APIs.
     - **Action (Positioning)**: Refactor the `calculate_diff` method to address the `"Simplified positioning for now"` comment. The target position for new `ADD` operations must be calculated based on the track's actual index in the `target_tracklist` to ensure the final order is correct.
     - **Action (Execution)**: In `_execute_operations`, enhance the logic to correctly apply `MOVE` operations to the in-memory `updated_tracks` list. Currently, they are logged but not executed, meaning the reordering is never reflected in the final persisted playlist.

  2. **Phase 2: Implement External Service Synchronization**
     - **Objective**: Translate the calculated `PlaylistDiff` into a series of efficient, sequenced API calls to an external service.
     - **Action (Service Impl)**: Create a concrete implementation of the `PlaylistSyncService` protocol for Spotify. This service will receive the list of `PlaylistOperation` objects from the use case.
     - **Architectural Note**: This is distinct from the existing `MatcherService`. The Matcher's role is **read-only identity resolution** (finding tracks), whereas the `PlaylistSyncService`'s role is **write-only state modification** (adding/removing/moving tracks in a playlist). This separation of concerns is critical for a clean architecture.
     - **Action (Batching & Sequencing)**: Inside the `SpotifySyncService`, implement the logic to batch operations according to API limits (e.g., 100 tracks per request). Crucially, execute them in the correct order: `REMOVE`s first (in reverse index order), then `ADD`s, then `MOVE`s to prevent index-related errors.
     - **Action (Wiring)**: Ensure the `UpdatePlaylistUseCase` is instantiated with the `SpotifySyncService` so `_execute_operations` can correctly delegate to it.

  3. **Phase 3: Integrate with MatcherService for Robust Matching**
     - **Objective**: Replace the use case's simplistic internal track matching with the project's existing, powerful `MatcherService`.
     - **Architectural Note**: This is a critical DRY (Don't Repeat Yourself) improvement. Instead of re-implementing ISRC and metadata matching within the use case, we will delegate to the `MatcherService` which is the single source of truth for identity resolution.
     - **Action (Dependency Injection)**: Modify the `UpdatePlaylistUseCase` to accept a `MatcherService` instance during its initialization.
     - **Action (Delegation)**: Replace the entire implementation of the private `_match_tracks` method with a call to the injected `MatcherService`. The service will handle the sophisticated matching logic based on the `track_matching_strategy` option.