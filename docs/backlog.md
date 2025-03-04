
# Project Narada Backlog

Current version: 0.1.2

Note: We've completed use case 1B and are mid-way done with use case 1A 

## Planned

### v0.1.3 Result Visualization & Metrics Display

Goal: Enhance the CLI workflow execution output with structured track results and associated metrics while establishing a foundation for future API integration.

- [x] Domain Result Model
    
    - Effort: S
    - What: Create minimal, transport-agnostic `WorkflowResult` class to capture tracks with associated metrics
    - Why: Establishes clean domain boundary for future API while immediately improving CLI output
    - Dependencies: None
    - Status: Complete
    - Notes:
        - Keep implementation under 50 LOC
        - Support serialization to both CLI table and JSON
        - Preserve metrics used in sorting/filtering operations
        - Design with future API consumption in mind
    
- [x] CLI Result Integration
    
    - Effort: S
    - What: Extend `run_workflow()` command to display track list with metrics after execution
    - Why: Provides immediate visibility into workflow results and transformation metrics
    - Dependencies: Domain Result Model
    - Status: Complete
    - Notes:
        - Use Rich library's existing table capabilities
        - Extract metrics from Prefect's final task context
        - Focus on most recently applied transformations
        - Implement as optional flag (--show-results)
    
- [x] Use Case 1A End to End Testing
    
    - Effort: S
    - What: Make sure we can run use case 1A and get back the expected results
    - Why: Provides immediate visibility into workflow results and transformation metrics
    - Dependencies: CLI Result Integration
    - Status: Complete


### v0.3 API-First Interface with Workflow Visualization
Goal: Transform Narada from a CLI-only tool into a service-oriented platform with elegant workflow visualization capabilities. This version establishes a clean API layer while introducing visualization that maintains the system's core functional architecture.

Key Objectives:
- Implement FastAPI service layer for all core operations
- Create elegant DAG visualization using React Flow
- Enable workflow inspection without editing (read-only first)
- Maintain clean architectural boundaries between domains

#### Core Architecture Foundation

- [ ] FastAPI Service Implementation
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

- [ ] Workflow Schema Enhancer
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

- [ ] DAG Layout Engine
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

- [ ] React Flow Visualization Component
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

- [ ] React App Shell
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

#### Testing Infrastructure

- [ ] API Test Suite
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

- [ ] Visualization Test Suite
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

### v0.4 Interactive Workflow Editor
Goal: Extend the visualization system to support full editing capabilities, enabling users to create and modify workflows through an intuitive graphical interface while maintaining the lean architectural principles of the system.

Key Objectives:
- Enable drag-and-drop workflow creation
- Implement node configuration panel
- Support workflow validation and testing
- Maintain clean separation between UI and domain logic

- [ ] Drag-and-Drop Node Creation
    - Effort: M
    - What: Implement drag-and-drop node creation from node palette
    - Why: Need intuitive workflow creation experience
    - Dependencies: v0.3
    - Status: Not Started
    - Notes:
        - Create node palette component
        - Implement drag source for node types
        - Add drop target handling
        - Include node positioning logic
        - Support undo/redo

- [ ] Node Configuration Panel
    - Effort: L
    - What: Create dynamic configuration panel for node parameters
    - Why: Users need to configure node behavior without JSON editing
    - Dependencies: v0.3
    - Status: Not Started
    - Notes:
        - Generate form from node schema
        - Implement validation
        - Add help text and documentation
        - Support complex parameter types
        - Include preset configurations

- [ ] Edge Management
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

- [ ] Workflow Persistence
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

- [ ] In-Editor Validation
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

### v0.5 LLM-Assisted Workflow Creation
Goal: Integrate LLM capabilities to enable natural language workflow creation, enhancing user experience while maintaining the system's clean architecture and separation of concerns.

Key Objectives:
- Enable workflow creation from natural language descriptions
- Implement visualization confirmation for LLM-generated workflows
- Support iterative refinement through conversation
- Maintain clean API boundaries and minimal coupling

- [ ] LLM Integration Endpoint
    - Effort: M
    - What: Create API endpoint for LLM-assisted workflow generation
    - Why: Foundation for natural language workflow creation
    - Dependencies: v0.4
    - Status: Not Started
    - Notes:
        - Implement secure LLM API wrapper
        - Add prompt engineering system
        - Support conversation context
        - Include result validation
        - Handle rate limiting

- [ ] Workflow Generation from Text
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

- [ ] Visualization Confirmation UI
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

- [ ] Conversation Interface
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

- [ ] LLM Feedback Loop
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

### v1.0 Enterprise-Ready Workflow Platform
Goal: Transform Narada into a production-ready workflow platform with robust user management, enhanced security, and comprehensive monitoring, while maintaining the system's architectural elegance and minimal footprint.

Key Objectives:
- Implement secure user authentication
- Enable team-based workflow management
- Support version control and collaboration
- Ensure robust monitoring and observability

- [ ] User Authentication System
    - Effort: M
    - What: Implement secure authentication with JWT and role-based access
    - Why: Need proper user management for multi-user support
    - Dependencies: v0.5
    - Status: Not Started
    - Notes:
        - Add JWT authentication
        - Implement role-based access control
        - Support email verification
        - Include password reset
        - Add session management

- [ ] Workflow Version Control
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

- [ ] Production Monitoring System
    - Effort: M
    - What: Create comprehensive monitoring and observability
    - Why: Need visibility into system performance and usage
    - Dependencies: v0.5
    - Status: Not Started
    - Notes:
        - Implement structured logging
        - Add performance metrics
        - Create monitoring dashboard
        - Include alerting system
        - Support distributed tracing

- [ ] Workflow Execution Dashboard
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

## Backlog
Features under consideration for future versions:

- [ ] Advanced Node Palette
    - Effort: M
    - What: Enhanced node selection interface with categories, search, and favorites
    - Why: Improve workflow creation experience with better node discovery
    - Notes: Good quality-of-life improvement

- [ ] Workflow Templates
    - Effort: M
    - What: Pre-built workflow templates for common scenarios
    - Why: Accelerate workflow creation and establish best practices
    - Notes: Could significantly improve onboarding

- [ ] Custom Node Creation
    - Effort: XL
    - What: Interface for creating custom nodes without coding
    - Why: Enable extension without programming
    - Notes: Advanced feature, consider after core platform stability

- [ ] Workflow Debugging Tools
    - Effort: L
    - What: Interactive debugging tools for workflow testing
    - Why: Help users identify and fix workflow issues
    - Notes: Important for complex workflow development

- [ ] Mobile-Responsive UI
    - Effort: M
    - What: Fully responsive design for mobile devices
    - Why: Enable workflow management from any device
    - Notes: Nice to have for v1.1

## Backburner
Ideas we've considered but aren't actively planning:

- Advanced Analytics Dashboard
    - What: Detailed analytics on workflow usage and performance
    - Why: Nice feature but not core to workflow management
    - Notes: Consider after more stable usage patterns emerge

- Multi-Language Support
    - What: UI translations for international users
    - Why: Not critical for initial target audience
    - Notes: Revisit based on user demographics

## Legend

### Priority Levels
- High: Critical path items
- Medium: Important but not blocking
- Low: Nice to have

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