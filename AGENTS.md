# AGENTS.md (How to Use Repo Context Efficiently)

This file tells other AI agents how to work with this repository while minimizing token usage and avoiding broken assumptions.

---

## 1) Start With the Right Notes (Do Not Re-Read Everything)

Read in this order:
1. `CONTEXT.md` (this file’s companion)
2. `docs/PROJECT_SUMMARY.md`
3. `docs/SYSTEM_FLOW.md`
4. `docs/ARCHITECTURE.md`
5. `docs/CODE_ARCHITECTURE_MAPPING.md`
6. `docs/PRODUCTION_READINESS_PLAN.md`

Then, only open the specific backend/frontend files required for the change.

---

## 2) Understand the Canonical Contracts First

This repo is in a stabilization state. Before implementing a feature or fix:
- Identify the domain (Auth / RAG Chat / Upload / Citations / Feedback / LMS / Planner / Analytics).
- Confirm the canonical Mongo collection and response fields used by:
  - backend routes for that domain
  - the frontend view consuming them

If the domain has both legacy and new paths, prefer the one used by the currently-running frontend screens, unless you are explicitly migrating.

---

## 3) Modification Guidelines (Keep Regressions Low)

### Backend
- Prefer editing:
  - `backend/api/*` for request/response contracts
  - `backend/services/*` for business logic orchestration
  - `backend/core/*` for AI/retrieval/LLM-related logic
  - `backend/utils/*` for shared helpers (DB, validation, logging)
- Ensure authz is consistent:
  - routes should call `get_current_user` and enforce `require_role(...)` when needed
- Avoid changing response shapes without updating frontend rendering code.

### Frontend
- This is Vanilla JS with static HTML pages:
  - Update only the affected view(s)
  - Keep token handling consistent with the shared config approach
- Watch for duplicated “API base URL” logic; don’t silently introduce new inconsistent base URLs.

---

## 4) When You Need to Answer “What Changed / Why Is It Broken?”

Use targeted searches:
- Search for the endpoint path in backend: `backend/api/*` and `backend/main.py`
- Search for the endpoint path in frontend: `frontend/public/views/*` and `frontend/public/assets/js/*`
- If you suspect schema drift, search for the Mongo collection name or field names in both:
  - `backend/api/*` write logic
  - `frontend/public/views/*` read/render logic

---

## 5) Output Format for Agents

When responding with an implementation or plan, include:
1. The affected domain(s)
2. The key contracts (request/response fields) you verified
3. The minimal file set that should change
4. Any known risks (especially legacy-vs-new schema)
5. A short test plan (manual smoke steps or targeted API checks)

