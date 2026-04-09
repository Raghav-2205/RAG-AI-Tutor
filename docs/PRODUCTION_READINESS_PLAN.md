# Production Readiness Plan

## Goal

Turn this repository from a mixed prototype/LMS build into a stable, testable, deployable application with clear contracts between backend, frontend, storage, and AI services.

## Current Reality

The project already has strong feature breadth:

- JWT auth
- document upload + RAG chat
- LMS classes, assignments, quizzes, attendance
- planner, notifications, analytics, community, announcements, events

The main blocker is not missing features. It is inconsistency:

- old and new Mongo collection shapes both exist
- some backend modules read legacy collections while newer screens write newer ones
- some frontend pages still rely on older assumptions or duplicated fetch logic
- runtime safety, observability, and automated verification are still thin

## Guiding Rules

1. Stabilize data contracts before adding features.
2. Fix shared flows before edge flows.
3. Prefer one canonical collection and one canonical API shape per domain.
4. Add tests for each repaired contract before moving to the next phase.
5. Treat AI features as unreliable dependencies and design for failure.

## Phase 1: Stabilize Core Contracts

### Objective

Remove schema drift and make the main user journeys reliable.

### Work

- Audit every Mongo collection used by:
  - auth
  - chat
  - upload
  - dashboard
  - quizzes
  - LMS
  - planner
  - notifications
- Pick canonical collections for each domain.
- Replace legacy reads where possible.
- Add compatibility adapters only where a full migration cannot happen immediately.
- Remove duplicate or conflicting routes.
- Standardize shared field names:
  - `id`
  - `user_id`
  - `chat_id`
  - `quiz_id`
  - `submitted_at`
  - `created_at`
  - `is_read`

### Exit Criteria

- Student can register/login.
- Student can upload a document and chat with citations.
- Teacher can create a class, assignment, quiz, and mark attendance.
- Student dashboard loads without empty-data bugs caused by schema mismatch.
- Notifications and calendar work with current data models.

## Phase 2: Backend Hardening

### Objective

Make the backend safe, predictable, and maintainable.

### Work

- Add Pydantic response models for every major endpoint.
- Centralize repeated role checks and ownership checks.
- Introduce repository/service boundaries for Mongo access.
- Replace broad `except Exception` blocks with typed handling where possible.
- Add stricter validation for:
  - uploads
  - date/time fields
  - role-restricted routes
  - quiz payloads
- Separate old standalone quiz flow from LMS quiz flow, or merge them into one canonical system.

### Exit Criteria

- No route uses ambiguous or conflicting resource shapes.
- Authz checks are consistent across teacher/admin/student features.
- Error responses are predictable and frontend-safe.

## Phase 3: Frontend Consolidation

### Objective

Reduce fragility caused by duplicated page scripts and inconsistent API usage.

### Work

- Centralize API calls through one shared client.
- Centralize auth/session handling.
- Centralize notification handling.
- Remove remaining hardcoded local API URLs.
- Refactor large inline-script views into shared JS modules gradually.
- Standardize loading, empty, and error states across pages.
- Add page-level smoke checks for:
  - dashboard
  - subjects
  - teacher portal
  - student LMS
  - planner

### Exit Criteria

- All main pages use the same API base strategy.
- Expired auth behaves consistently across the app.
- Shared UI behaviors no longer need to be fixed page-by-page.

## Phase 4: Testing and CI

### Objective

Catch regressions before deployment.

### Work

- Add unit tests for service modules.
- Add API integration tests for:
  - auth
  - upload
  - chat
  - LMS
  - planner
  - notifications
  - dashboard
- Seed test fixtures for Mongo and Chroma.
- Add a smoke suite for core user journeys.
- Run tests automatically in CI.

### Current Baseline

- `test/test_integration_api_flows.py` now provides a stable isolated contract suite for:
  - auth
  - upload
  - chat
  - standalone quiz
  - LMS quiz flow
  - planner
  - dashboard
  - notifications
- `.github/workflows/integration-contracts.yml` runs that suite on pushes and pull requests using `requirements-test.txt`.
- `test/test_static_page_smoke.py` verifies that the main LMS and tutor page entrypoints and shared JS/CSS assets are servable through the static frontend mount.
- `test/test_mongo_lms_smoke.py` adds a second-tier real MongoDB LMS smoke path for:
  - teacher registration and login
  - class creation
  - LMS quiz creation
  - student enrollment
  - student quiz fetch and submission
  - persisted quiz attempt verification in Mongo
- `.github/workflows/mongo-lms-smoke.yml` runs that Mongo-backed LMS smoke path in GitHub Actions with a Mongo service container.

### Exit Criteria

- Pull requests fail on broken contracts.
- Main flows are covered by automated tests.

## Phase 5: Security and Reliability

### Objective

Make the app safe for real users and resilient in production.

### Work

- Tighten CORS from `*` to known frontend origins.
- Remove insecure default secrets from runtime assumptions.
- Add rate limiting for auth, chat, and upload endpoints.
- Add upload size/type enforcement at API and proxy levels.
- Add request IDs and structured logging.
- Add health endpoints for:
  - API
  - Mongo
  - Chroma
  - LLM connectivity
- Add timeouts, retries, and fallbacks around Gemini/Chroma calls.
- Move long-running ingestion/graph tasks to background workers or job queues.

### Exit Criteria

- External dependency failures degrade gracefully.
- Operational logs are usable for debugging real incidents.
- Security defaults are no longer development-only.

## Phase 6: Deployment and Operations

### Objective

Make releases repeatable and reversible.

### Work

- Create environment-specific config for dev, staging, and production.
- Add database migration/versioning strategy.
- Add Docker health checks and production-ready startup order.
- Add backup and restore procedures.
- Add release checklist and rollback procedure.
- Add monitoring and alerting for:
  - API error rate
  - response latency
  - failed AI calls
  - DB connectivity

### Exit Criteria

- Staging mirrors production behavior closely.
- A release can be deployed and rolled back safely.

## Recommended Order of Execution

1. Phase 1 contract stabilization
2. Phase 2 backend hardening
3. Phase 3 frontend consolidation
4. Phase 4 tests and CI
5. Phase 5 security and reliability
6. Phase 6 deployment and operations

## Suggested Working Rhythm

### Sprint A

- finish contract audit
- remove remaining legacy collection mismatches
- document canonical schemas

### Sprint B

- fix backend authz and response models
- repair remaining frontend API inconsistencies

### Sprint C

- add integration tests for main flows
- stand up CI

### Sprint D

- add security controls
- add observability
- prepare staging deploy

## Definition of "Production Ready"

The app is production ready when:

- core user journeys work end to end without manual repair
- backend and frontend use stable contracts
- failures are observable
- regressions are caught in CI
- secrets and permissions are handled safely
- deployments are repeatable and reversible
