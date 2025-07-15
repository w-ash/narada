
# Project Narada Backlog

**Current Version**: 0.2.3 (in progress)  
**Status**: Clean Architecture migration complete, modern testing architecture in progress

## Overview
Narada has evolved from a simple music sync tool into a sophisticated workflow platform with Clean Architecture foundations. We've completed cross-service synchronization, play history imports, and architectural modernization. Currently focusing on test architecture improvements before advancing to API and visualization features.

## Completed Milestones ✅

### v0.2.0-0.2.2: Core Data Platform
**Achievement**: Complete cross-service sync and play history platform

**Key Features Delivered**:
- ✅ **Spotify ↔ Last.fm Sync**: Bidirectional likes synchronization 
- ✅ **Play History Import**: Spotify GDPR exports + Last.fm API with smart deduplication
- ✅ **Enhanced Track Resolution**: 100% processing rate for any age Spotify export
- ✅ **DRY Architecture**: Unified models, factory patterns, zero redundancy

### v0.2.3: Clean Architecture Foundation  
**Achievement**: Modern, maintainable codebase ready for scale

**Architecture Transformation**:
- ✅ **Clean Architecture**: Domain/Application/Infrastructure layers with proper boundaries
- ✅ **Dependency Injection**: Technology-agnostic business logic
- ✅ **Performance**: Domain tests 10x faster, maintained test coverage
- ✅ **Future-Ready**: Foundation for web APIs and modern frameworks

**Clean Architecture Initiative Completed**:
- ✅ **Phase 0: Project Structure Migration**: Migrated from legacy `/narada` to modern `/src` structure with consistent import paths
- ✅ **Phase 1: Repository Interface Consolidation**: Unified repository contracts in domain layer, eliminated 5 duplicate protocols
- ✅ **Phase 2: Service Layer Reorganization**: Moved business logic to application layer, deleted 7 redundant files, established proper CLI → Application → Domain flow
- ✅ **Phase 3: Architecture Compliance & Quality**: Verified Clean Architecture principles, updated to Python 3.13 patterns, maintained full test coverage
- ✅ **Phase 4: Modern Testing Architecture**: Replaced heavy async mocking with lightweight dependency injection, achieved 332/332 tests passing

**Detailed Migration Results**:
        - ✅ **Future-Ready**: Foundation established for FastAPI web interface with zero business logic changes needed
        - ✅ **Migration Complete**: Successfully migrated all imports from `narada.*` to `src.*` structure
        - ✅ **Old Code Removed**: Deleted legacy `/narada` directory after comprehensive verification
        - ✅ **Core Tests Passing**: 314/332 tests passing for CLI and integration functionality
        - **Result**: Clean Architecture migration complete, ready for web interface development

**Remaining Clean Architecture Work**:

- [x] **Modern Testing Architecture** (Phase 4)
    - Effort: M
    - What: Replace heavy async mocking with lightweight dependency injection patterns
    - Why: Brittle workflow tests were blocking progress due to complex mocking anti-patterns. Clean dependency injection enables fast, maintainable tests while preserving architectural boundaries.
    - Dependencies: Clean Architecture Restructuring
    - Status: Complete
    - Notes:
        - **Achievement**: 332/332 tests passing with clean linting
        - **Performance**: <10 second test runtime achieved
        - **Approach**: Function-level dependency injection with pytest fixtures

- [ ] **Matcher System Modernization** (Phase 5)
    - Effort: L
    - What: Decompose monolithic matcher into modular provider pattern
    - Why: Current 961-line matcher violates Single Responsibility Principle, mixing domain logic with service-specific API calls. Clean Architecture separation enables easier testing, maintenance, and extension to new music services.
    - Dependencies: Modern Testing Architecture
    - Status: Not Started
    - Notes:
        - **Problem**: Domain logic, API calls, and orchestration tangled together
        - **Solution**: Provider pattern with proper layer separation
        - **Benefit**: Adding new music services becomes trivial

- [ ] **Workflow Node Architecture** (Phase 6)
    - Effort: M
    - What: Extract playlist persistence logic into reusable Application Use Cases
    - Why: Current workflow nodes contain complex business logic that should live in Application layer. Proper separation prepares for modern workflow engines and web interface integration.
    - Dependencies: Matcher System Modernization
    - Status: Not Started
    - Notes:
        - **Problem**: Business process logic trapped in infrastructure layer
        - **Solution**: Dedicated Use Cases with proper dependency injection
        - **Benefit**: Ready for FastAPI, async patterns, and modern orchestration

---

## Planned Roadmap 🚀

### v0.2.4: Play History Workflow Integration
**Goal**: Enable advanced play-based filtering and discovery workflows

#### Play History Analysis Capabilities
- [ ] **Play History Filter and Sort Extensions**
    - Effort: M
    - What: Extend existing filter and sorter node categories to support play history metrics
    - Why: Users need granular control over finding tracks based on listening behavior - frequently/rarely played tracks, seasonal patterns, discovery gaps, and listening recency for advanced playlist curation
    - Dependencies: v0.2.3
    - Status: Not Started
    - Notes:
        - Leverage existing filter/sorter architecture in `TRANSFORM_REGISTRY`
        - Enable play count filtering (e.g., tracks played >10 times, <5 times)
        - Support time-period analysis (e.g., tracks played >5 times in July 2024)
        - Add play recency sorting (most/least recently played)
        - Include relative time periods (last 30 days, past week, this month)
        - Build on existing metric-based filtering patterns

- [ ] **Discovery Workflow Templates**
    - Effort: S
    - What: Create pre-built workflow templates leveraging new play history capabilities
    - Why: Reduce complexity for users to access powerful play analysis without workflow construction expertise
    - Dependencies: Play History Filter and Sort Extensions
    - Status: Not Started
    - Notes:
        - Common discovery patterns: "Hidden Gems", "Seasonal Favorites", "Rediscovery", "New vs Old"
        - Templates demonstrate play history node capabilities
        - Provide starting points for user customization

### v0.3.0: User Experience & Reliability
**Goal**: Polish the user experience and improve system reliability

#### Enhanced CLI Experience  
- [ ] **Enhanced Error Handling**
    - Effort: M
    - What: Improve error handling across workflow execution and API operations
    - Why: Better user experience with actionable error messages
    - Dependencies: v0.2.4
    - Status: Not Started
    - Notes:
        - Add retry logic for transient API failures
        - Provide specific guidance for common error scenarios
        - Implement graceful degradation for partial failures
        - Add error context and suggestions

- [ ] **Shell Completion Support**
    - Effort: S
    - What: Add shell completion for bash/zsh/fish
    - Why: Improves CLI usability and discoverability
    - Dependencies: None
    - Status: Not Started
    - Notes:
        - Use Typer's built-in completion support
        - Generate completion scripts for major shells
        - Include dynamic completion for workflows and connectors

- [ ] **Progress Reporting Consistency**
    - Effort: S
    - What: Standardize progress reporting across all long-running operations
    - Why: Users need consistent feedback on operation status
    - Dependencies: None
    - Status: Not Started
    - Notes:
        - Use unified progress provider interface
        - Add ETA calculations where possible
        - Include operation-specific progress details

### v0.4.0: Performance & Advanced Analytics
**Goal**: Optimize performance and add advanced play analytics

#### System Performance
- [ ] **Performance Optimizations**
    - Effort: M
    - What: Optimize database queries and batch processing for large datasets
    - Why: Better performance with large play history and track collections
    - Dependencies: v0.3.0
    - Status: Not Started
    - Notes:
        - Optimize batch processing parameters based on dataset size
        - Add database indexing for play history queries
        - Implement connection pooling improvements
        - Cache frequently accessed connector mappings

- [ ] **Advanced Play Analytics**
    - Effort: M
    - What: Add analytics commands for listening patterns and insights
    - Why: Provides valuable insights into listening habits
    - Dependencies: Performance Optimizations
    - Status: Not Started
    - Notes:
        - Top tracks by time period
        - Listening pattern analysis (time of day, day of week)
        - Track discovery timeline
        - Export analytics to CSV/JSON formats

- [ ] **Background Sync Capabilities**
    - Effort: M
    - What: Enable scheduled background synchronization of play history and likes
    - Why: Keeps data current without manual intervention
    - Dependencies: Advanced Play Analytics
    - Status: Not Started
    - Notes:
        - Add scheduling system for regular sync jobs
        - Implement incremental sync for efficiency
        - Add configuration for sync frequency and scope
        - Include sync status monitoring

---

### v0.5.0: Core Functionality Improvements
**Goal**: Essential functionality improvements based on user feedback

#### Enhanced Capabilities
- [ ] **Manual Entity Resolution Override**
    - Effort: M
    - What: Add ability for users to manually create and edit track matches
    - Why: Automatic matching can't handle all edge cases; manual override needed
    - Dependencies: None
    - Status: Not Started
    - Notes:
        - Allow setting track ID, connector, and connector ID
        - Set confidence to 100% for manual matches
        - Support overriding existing matches
        - Add CLI command for manual match creation
        - Save metadata about who created the match and when

- [ ] **Matcher Status Feedback**
    - Effort: S
    - What: Implement better progress reporting for matcher operations
    - Why: Matching is a long-running process with no visibility
    - Dependencies: None
    - Status: Not Started
    - Notes:
        - Add progress indicators for batch operations
        - Show success/failure counts in real-time
        - Implement optional verbose mode for detailed progress
        - Report service-specific rate limiting information
        - Include estimated completion time

- [ ] **Enhanced Destination Nodes**
    - Effort: M
    - What: Add update and parameterization capability to destination nodes
    - Why: Enable dynamic playlist naming and descriptions
    - Dependencies: None 
    - Status: Not Started
    - Notes:
        - Support template parameters in playlist names
        - Allow using source playlist names in new playlist names/descriptions
        - Add date/time formatting options
        - Implement track count and metadata insertion
        - Add validation to prevent invalid characters
        - Create nodes that update Spotify and internal playlists with append/replace options

### v0.6.0: Advanced Core Features
**Goal**: Continue enhancing core functionality with advanced capabilities

#### Advanced Transformations
- [ ] **Advanced Transformers**
    - Effort: M
    - What: Implement additional transformer nodes for workflow system
    - Why: More transformation options enable more powerful workflows
    - Dependencies: None
    - Status: Not Started
    - Notes:
        - Implement merging operations with different strategies
        - Add time-based transformers (seasonal, time of day)
        - Support user preference learning
        - Include randomization with weighting

- [ ] **Two-Way Like Synchronization**
    - Effort: M
    - What: Implement bidirectional like synchronization between services
    - Why: Currently only supports one-way sync (Spotify → Narada → Last.fm)
    - Dependencies: None
    - Status: Not Started
    - Notes:
        - Add conflict detection and resolution
        - Implement service prioritization
        - Support timestamp-based resolution
        - Add manual override options
        - Include detailed sync reporting

- [x] Incremental Likes Export
    - Effort: S
    - What: Enhance the export functionality to only process recently added likes
    - Why: More efficient for regular synchronization of large libraries
    - Dependencies: None
    - Status: Complete
    - Notes:
        - Extended repository with timestamp-based queries for efficient filtering
        - Added since_timestamp parameter to repository and service methods
        - Implemented conditional logic in like_sync.py for incremental export
        - Added checkpoint timestamps for tracking last sync
        - Improved logging for visibility into incremental sync operations

---

### v0.7.0: API-First Interface with Workflow Visualization  
**Goal**: Transform Narada into a service-oriented platform with elegant workflow visualization

#### Modern Web Interface Foundation
- [ ] **FastAPI Service Implementation**
    - Effort: M
    - What: Create FastAPI service exposing core workflow operations
    - Why: Need programmatic access to workflow capabilities before building visualization
    - Dependencies: None
    - Status: Not Started
    - Notes:
        - Key Features:
            - Full Pydantic schema validation
            - Proper error handling with consistent responses
            - Automatic OpenAPI documentation
            - Async support throughout
            - Clear domain boundaries

- [ ] **Workflow Schema Enhancer**
    - Effort: S
    - What: Create adapter that transforms workflow definitions into visualization-friendly schema
    - Why: Current task-based schema lacks presentation metadata for visualization
    - Dependencies: FastAPI Service
    - Status: Not Started
    - Notes:
        - Convert from task/upstream format to nodes/edges model
        - Add position information for layout
        - Include visual metadata (colors, icons, categories)
        - Preserve backward compatibility

- [ ] **DAG Layout Engine**
    - Effort: M
    - What: Implement server-side layout calculation for workflow visualization
    - Why: Need automatic positioning of nodes for clear visualization
    - Dependencies: Workflow Schema Enhancer
    - Status: Not Started
    - Notes:
        - Integrate dagre for hierarchical layout
        - Calculate optimal node positions
        - Respect node categories and relationships
        - Handle large workflows efficiently
        - Cache layout results

- [ ] **React Flow Visualization Component**
    - Effort: M
    - What: Create React visualization component using React Flow
    - Why: Need clean, interactive workflow visualization with minimal code
    - Dependencies: DAG Layout Engine
    - Status: Not Started
    - Notes:
        - Implement read-only visualization first
        - Add node type-based styling
        - Include smooth animations
        - Support zooming and panning
        - Show node details on selection

- [ ] **React App Shell**
    - Effort: S
    - What: Create minimal React application shell around visualization component
    - Why: Need container to host visualization while maintaining minimal footprint
    - Dependencies: React Flow Visualization
    - Status: Not Started
    - Notes:
        - Implement workflow selector
        - Add basic navigation
        - Include error handling
        - Support responsive layout
        - Maintain minimal bundle size

#### API Testing & Quality Assurance
- [ ] **API Test Suite**
    - Effort: S
    - What: Implement comprehensive test suite for API endpoints
    - Why: Need to validate API behavior and prevent regressions
    - Dependencies: FastAPI Service
    - Status: Not Started
    - Notes:
        - Test all core operations
        - Include error cases
        - Validate response formats
        - Test persistence operations
        - Add performance benchmarks

- [ ] **Visualization Test Suite**
    - Effort: S
    - What: Create tests for visualization component and layout engine
    - Why: Need to ensure visualization accurately represents workflows
    - Dependencies: React Flow Visualization
    - Status: Not Started
    - Notes:
        - Test node/edge rendering
        - Validate layout algorithm
        - Test user interactions
        - Include accessibility testing
        - Ensure cross-browser compatibility

---

### v0.8.0: Interactive Workflow Editor
**Goal**: Full editing capabilities with intuitive graphical interface

#### Interactive Editing System
- [ ] **Drag-and-Drop Node Creation**
    - Effort: M
    - What: Implement drag-and-drop node creation from node palette
    - Why: Need intuitive workflow creation experience
    - Dependencies: v0.5.0
    - Status: Not Started
    - Notes:
        - Create node palette component
        - Implement drag source for node types
        - Add drop target handling
        - Include node positioning logic
        - Support undo/redo

- [ ] **Node Configuration Panel**
    - Effort: L
    - What: Create dynamic configuration panel for node parameters
    - Why: Users need to configure node behavior without JSON editing
    - Dependencies: v0.5.0
    - Status: Not Started
    - Notes:
        - Generate form from node schema
        - Implement validation
        - Add help text and documentation
        - Support complex parameter types
        - Include preset configurations

- [ ] **Edge Management**
    - Effort: M
    - What: Implement interactive edge creation and deletion
    - Why: Users need to visually connect nodes
    - Dependencies: Drag-and-Drop Node Creation
    - Status: Not Started
    - Notes:
        - Add interactive connection points
        - Implement edge validation
        - Support edge deletion
        - Include edge styling
        - Handle edge repositioning

- [ ] **Workflow Persistence**
    - Effort: S
    - What: Add save/load functionality for workflows
    - Why: Users need to persist their work
    - Dependencies: Node Configuration Panel
    - Status: Not Started
    - Notes:
        - Implement save API endpoint
        - Add version control
        - Support auto-save
        - Include export/import
        - Handle validation during save

- [ ] **In-Editor Validation**
    - Effort: M
    - What: Add real-time validation of workflow structure
    - Why: Users need immediate feedback on workflow validity
    - Dependencies: Edge Management
    - Status: Not Started
    - Notes:
        - Validate node configurations
        - Check edge validity
        - Highlight errors
        - Provide guidance
        - Support auto-correction

---

### v0.9.0: LLM-Assisted Workflow Creation
**Goal**: Natural language workflow creation with LLM integration

#### AI-Powered Creation
- [ ] **LLM Integration Endpoint**
    - Effort: M
    - What: Create API endpoint for LLM-assisted workflow generation
    - Why: Foundation for natural language workflow creation
    - Dependencies: v0.6.0
    - Status: Not Started
    - Notes:
        - Implement secure LLM API wrapper
        - Add prompt engineering system
        - Support conversation context
        - Include result validation
        - Handle rate limiting

- [ ] **Workflow Generation from Text**
    - Effort: L
    - What: Implement system to translate natural language to workflow definitions
    - Why: Enable non-technical users to create workflows
    - Dependencies: LLM Integration Endpoint
    - Status: Not Started
    - Notes:
        - Design specialized prompts
        - Implement node mapping
        - Add configuration extraction
        - Include workflow validation
        - Support complex workflow patterns

- [ ] **Visualization Confirmation UI**
    - Effort: M
    - What: Create interface for reviewing and confirming LLM-generated workflows
    - Why: Users need to verify generated workflows before saving
    - Dependencies: Workflow Generation from Text
    - Status: Not Started
    - Notes:
        - Show visualization of generated workflow
        - Highlight key components
        - Allow immediate adjustments
        - Provide explanation of structure
        - Include confidence indicators

- [ ] **Conversation Interface**
    - Effort: L
    - What: Implement chat-style interface for workflow creation and refinement
    - Why: Natural conversation provides better user experience
    - Dependencies: Visualization Confirmation UI
    - Status: Not Started
    - Notes:
        - Create chat UI component
        - Implement conversation history
        - Add contextual suggestions
        - Support workflow references
        - Include guided assistance

- [ ] **LLM Feedback Loop**
    - Effort: M
    - What: Create system for user feedback on LLM-generated workflows
    - Why: Improve generation quality through user input
    - Dependencies: Conversation Interface
    - Status: Not Started
    - Notes:
        - Implement feedback collection
        - Add result quality tracking
        - Create feedback insights dashboard
        - Support model improvement
        - Include A/B testing

---

### v1.0.0: Production-Ready Workflow Platform
**Goal**: Transform into production-ready platform with robust user management

#### Production Infrastructure
- [ ] **User Authentication System**
    - Effort: M
    - What: Implement secure authentication with JWT and role-based access
    - Why: Need proper user management for multi-user support
    - Dependencies: v0.7.0
    - Status: Not Started
    - Notes:
        - Add JWT authentication
        - Implement role-based access control
        - Support email verification
        - Include password reset
        - Add session management

- [ ] **Workflow Version Control**
    - Effort: L
    - What: Implement version tracking and management for workflows
    - Why: Users need to track changes and revert when needed
    - Dependencies: Team Collaboration Features
    - Status: Not Started
    - Notes:
        - Add versioning system
        - Implement diff visualization
        - Support rollback
        - Include branching
        - Add merge capabilities

- [ ] **Production Monitoring System**
    - Effort: M
    - What: Create comprehensive monitoring and observability
    - Why: Need visibility into system performance and usage
    - Dependencies: v0.7.0
    - Status: Not Started
    - Notes:
        - Implement structured logging
        - Add performance metrics
        - Create monitoring dashboard
        - Include alerting system
        - Support distributed tracing

- [ ] **Workflow Execution Dashboard**
    - Effort: L
    - What: Build visual dashboard for workflow execution monitoring
    - Why: Users need visibility into running workflows
    - Dependencies: Production Monitoring System
    - Status: Not Started
    - Notes:
        - Create real-time execution visualization
        - Add performance metrics
        - Implement log viewer
        - Support debugging tools
        - Include execution history

---

## Future Considerations 💭

### Quality of Life Improvements
- [ ] **Advanced Node Palette**
    - Effort: M
    - What: Enhanced node selection interface with categories, search, and favorites
    - Why: Improve workflow creation experience with better node discovery
    - Notes: Good quality-of-life improvement

- [ ] **Workflow Templates**
    - Effort: M
    - What: Pre-built workflow templates for common scenarios
    - Why: Accelerate workflow creation and establish best practices
    - Notes: Could significantly improve onboarding

- [ ] **Custom Node Creation**
    - Effort: XL
    - What: Interface for creating custom nodes without coding
    - Why: Enable extension without programming
    - Notes: Advanced feature, consider after core platform stability

- [ ] **Workflow Debugging Tools**
    - Effort: L
    - What: Interactive debugging tools for workflow testing
    - Why: Help users identify and fix workflow issues
    - Notes: Important for complex workflow development

- [ ] **Mobile-Responsive UI**
    - Effort: M
    - What: Fully responsive design for mobile devices
    - Why: Enable workflow management from any device
    - Notes: Nice to have for v1.1

### Lower Priority Ideas
- **Advanced Analytics Dashboard**
    - What: Detailed analytics on workflow usage and performance
    - Why: Nice feature but not core to workflow management
    - Notes: Consider after more stable usage patterns emerge

- **Multi-Language Support**
    - What: UI translations for international users
    - Why: Not critical for initial target audience
    - Notes: Revisit based on user demographics

---

## Reference Guide 📋

### Effort Estimates
- XS: < 1 day
- S: 1-2 days
- M: 3-5 days
- L: 1-2 weeks
- XL: 2-4 weeks
- XXL: 1+ months

### Status Options
- Not Started
- In Progress
- Blocked
- Completed