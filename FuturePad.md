

---

## 📋 TODO: Backward Compatibility Wrapper Cleanup (Future Work)

**Context**: The codebase contains 15+ backward compatibility wrappers that maintain API stability during the Clean Architecture migration. While these serve legitimate purposes currently, they represent opportunities for future cleanup once migration is complete and breaking changes are acceptable.

### Identified Backward Compatibility Wrappers

#### **High Impact Cleanup Opportunities**

1. **Configuration System Legacy Support** (`src/config/settings.py:207-310`)
   - **75+ legacy environment variable mappings** in `_LEGACY_KEY_MAP`
   - **Legacy `get_config()` function** providing old dictionary-based access
   - **Impact**: Large reduction in complexity once legacy env vars are deprecated

2. **Use Case Convenience Wrappers** (Multiple files)
   - **`MatchTracksUseCase`** (`match_tracks.py:20-95`) - wrapper around `TrackIdentityUseCase`
   - **`match_tracks()` function** (`match_tracks.py:97-140`) - CLI compatibility function
   - **Sync likes functions** (`sync_likes.py:570-616`) - CLI convenience wrappers
   - **Import orchestrator** (`import_tracks.py:300-309`) - CLI wrapper function

#### **Medium Impact Cleanup Opportunities**

3. **Workflow Node Compatibility Returns** (`destination_nodes.py`)
   - **4 nodes with compatibility return formats** (lines 63-75, 119-131, 177-189, 252-264)
   - **Purpose**: Maintain expected result format during workflow system migration

4. **Domain Entity Compatibility** (`operations.py:369-399`)
   - **`WorkflowResult` extends `OperationResult`** with backward compatibility properties
   - **Legacy `workflow_name` property** for old API compatibility

#### **Low Impact Cleanup Opportunities**

5. **Utility Function Wrappers**
   - **Simple batching wrapper** (`simple_batching.py:16-59`) - bridges to unified progress system
   - **Repository compatibility property** (`track/__init__.py:60-64`) - playlist repo access

6. **Infrastructure Service Compatibility**
   - **LastFM import result compatibility** (`lastfm_import.py:120`) - unified field preservation

### Cleanup Strategy Recommendations

**Phase 1: API Stability Analysis** (Before any removal)
- Survey actual usage of each wrapper across CLI, tests, and external integrations
- Identify which wrappers are actively used vs. maintained "just in case"
- Create migration guides for each wrapper that will be removed

**Phase 2: Gradual Deprecation** (Low risk, high value)
- Add deprecation warnings to unused wrappers
- Update documentation to guide users toward new APIs
- Provide clear migration timelines

**Phase 3: Clean Breaks** (When breaking changes are acceptable)
- Remove configuration legacy key mappings (biggest impact)
- Eliminate use case convenience wrappers where direct use case access is preferred
- Consolidate workflow node return formats to unified system

### Estimated Cleanup Impact
- **~500+ lines of code reduction** from configuration legacy system alone
- **~200+ lines of code reduction** from use case wrappers
- **Significant complexity reduction** in maintenance and cognitive load
- **Better API consistency** with single way to do things (ruthlessly DRY)

### Priority Recommendation
**Defer this cleanup** until after:
1. All current architectural migrations are complete and stable
2. User adoption of new APIs is confirmed through usage analytics
3. Breaking change windows are acceptable to end users

---

## Future Work: Additional Architectural Refinements (After Dependency Inversion)

### Key Initiatives (Sequenced for Efficiency)

#### 1. Clarify Enrichment vs. Matching Data Flow

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