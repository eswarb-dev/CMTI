# Implementation Status

## Deterministic Investigation Evidence Hardening - 2026-09-17

Completed:

- Added a deterministic investigation snapshot service that resolves analysis, baseline, and recent windows from seeded CNC-M04 batches unless the user supplies an explicit time scope.
- Added stable evidence IDs for document, operational, and analytical evidence records.
- Captured operational evidence references for surface roughness measurements, spindle vibration telemetry, tool usage, and maintenance events.
- Added deterministic analytics snapshots for surface roughness, vibration, and tool usage using seeded measurements and existing analytics services.
- Preserved the upper-only surface roughness specification: USL is included, LSL is not invented, and Cp/Cpk are not reported for roughness.
- Added three persisted chart snapshots: surface roughness batch mean trend, spindle vibration RMS trend, and tool usage versus replacement interval.
- Added deterministic hypotheses with supporting, contradictory, neutral, and unresolved evidence ID fields. Hypotheses remain advisory associations, not proven causes.
- Persisted the evidence register, deterministic analytics, chart snapshots, deterministic hypotheses, and tool results in investigation state JSON.
- Updated investigation reload APIs so saved investigations return the same deterministic fields after refresh.
- Updated the frontend investigation detail UI with resolved scope, three persisted charts, deterministic analytics cards, evidence register groups, and structured hypothesis evidence IDs.
- Updated PDF generation to render deterministic analytics, native chart drawings from saved chart snapshots, and an evidence register without requiring live frontend screenshots.
- Added regression tests for deterministic scope resolution, stable evidence IDs, roughness one-sided spec behavior, chart snapshot presence, persisted state JSON, missing evidence-reference validation, and PDF deterministic section content.

Verification commands:

```powershell
# Backend lint
cd D:\CMTI\backend
python -m ruff check .
# Result: All checks passed

# Backend tests
cd D:\CMTI
pytest -q
# Result: 105 passed, 1 skipped

# Frontend lint
cd D:\CMTI\frontend
npm run lint
# Result: clean

# Frontend typecheck
cd D:\CMTI\frontend
npm run typecheck
# Result: clean

# Frontend production build
cd D:\CMTI\frontend
npm run build
# Result: succeeded; Vite warns that one JS chunk is larger than 500 kB
```

Known limitations:

- This remains a local single-user demo using synthetic manufacturing data only.
- Deterministic hypotheses are associations requiring engineering review; they are not proof of root cause.
- PDF charts are native report drawings from saved chart snapshots, not pixel-identical copies of the frontend Recharts views.
- LLM/provider behavior was not expanded in this hardening pass.

Next phase:

- Optional polish pass: browser-based visual QA for the updated investigation detail view and PDF pages, plus chunk-size/code-splitting if frontend bundle size becomes a priority.


## Phase 8 - Prototype Stabilization and Demonstration Readiness

Completed:

- Created `backend/Dockerfile` with Python 3.11-slim, reportlab, health check, and uvicorn entrypoint.
- Created `frontend/Dockerfile` with multi-stage build: Node 20 for build, nginx:alpine for serving with API proxy.
- Updated `docker-compose.yml` with three services: PostgreSQL (pgvector), backend, and frontend with health checks and dependency ordering.
- Created `backend/.dockerignore` and `frontend/.dockerignore` to exclude .venv, node_modules, .env, storage, and .git from images.
- Created comprehensive `docs/SETUP.md` covering Docker Compose startup, local development, migrations, seeding, embedding model, tests, troubleshooting, and feature status.
- Created 10-scenario evaluation suite (`tests/test_evaluation.py`) covering:
  1. Roughness investigation on CNC-M04
  2. Healthy comparison machine (CNC-M02)
  3. Exact SOP lookup by document ID
  4. Superseded-revision exclusion
  5. Missing machine scope clarification
  6. Unsupported engineering question
  7. Insufficient evidence (far-future time range)
  8. One-sided specification handling
  9. Provider outage graceful degradation
  10. Document prompt injection prevention
- Created `docs/DEMO_SCRIPT.md` with a five-minute walkthrough: dashboard, engineering question, execution, evidence, analytics, review, and PDF export.
- Updated `docs/IMPLEMENTATION_STATUS.md` with final Phase 6, 7, and 8 status.
- Updated `.gitignore` with additional exclusions for IDE files and Docker build artifacts.
- Verified all 87 backend tests pass (1 skipped = live provider opt-in).
- Verified all 12 frontend tests pass.
- Verified ruff lint clean on app/ and tests/.
- Verified TypeScript compilation clean.
- Verified Vite production build succeeds (523 KB JS, 16 KB CSS).

Verification commands:

```powershell
# Backend tests (87 passed, 1 skipped)
cd backend && .venv\Scripts\python.exe -m pytest ../tests/test_analytics.py ../tests/test_investigation_workflow.py ../tests/test_reviews.py ../tests/test_evaluation.py -q
# Result: 87 passed, 1 skipped

# Lint
cd backend && .venv\Scripts\python.exe -m ruff check app/ ../tests/
# Result: All checks passed

# Frontend tests (12 passed)
cd frontend && npx vitest run -q
# Result: 12 passed

# Frontend typecheck
cd frontend && npx tsc -b --pretty false
# Result: clean

# Frontend production build
cd frontend && npx vite build
# Result: built in ~190ms
```

Known limitations:

- Docker Compose provides full containerized stack but does not include hot-reload for development.
- The LLM provider is disabled by default. Groq-compatible integration is optional and opt-in.
- All manufacturing data is synthetic. No real production data is included.
- Reviewer identities are unverified demonstration inputs, not secure authorization.
- The prototype must not be deployed publicly or connected to real factory systems.

## Phase 7 - Review Decisions and Investigation PDF Export

Completed:

- Added review state machine with five states: draft, pending_review, approved, rejected, revision_requested.
- Server-enforced state transitions with explicit allowed-transition map.
- Version checks reject stale review submissions (HTTP 409).
- Editing reviewed recommendations creates a new version requiring review again.
- All review events persisted to `investigation_review_events` table with exact investigation version.
- Reviewer identity is always `reviewer_identity_verified=False` with unverified demonstration notice.
- PDF generation service using reportlab with: wrapped table cells, repeated table headers, safe margins, headings kept with content, page numbers, synthetic data notice, review history, all investigation sections.
- Added `GET /api/reviews/investigations`, `POST /api/reviews/{code}`, `GET /api/reviews/{code}`, `GET /api/reviews/{code}/pdf`.
- Added review UI with state badges, version display, review form, review history, and PDF download button.
- Added 40 review tests covering transitions, version checks, persistence, PDF generation, long text, and multipage evidence.

## Phase 6 - Complete Engineering Investigation UI

Completed:

- Full frontend rewrite with Dashboard, Copilot, Evidence, and Investigations sections.
- Machine selector, metric cards, Recharts line charts with spec limit reference lines.
- Batch summaries table with OOS and overdue highlighting.
- Ranked hypotheses with evidence links and scores.
- Copilot workspace with question input, machine/time scope, suggested questions, and real execution progress.
- Evidence panel with hybrid retrieval form, citation chips with click-to-expand tooltips.
- Investigation detail with execution timeline, structured assessment, computed results, limitations, warnings, citations.
- Investigation history with clickable list and split-pane detail view.
- Loading, empty, and error states throughout.
- Accessibility: aria-label, aria-current, keyboard focus visible, semantic HTML.
- Responsive layout with CSS grid, mobile sidebar collapse.
- Professional industrial design: navy (#0f1b2d), white, teal (#1a8a7d), Inter font.

## Phase 5 - LangGraph Investigation Workflow and Configurable LLM Adapter

Completed:

- Typed investigation workflow state with investigation ID, query, scope, evidence, tool results, warnings, citations, status, and structured assessment.
- Additive persistence for investigation metadata, evidence snapshots, and execution events.
- Configurable backend-only provider adapter with Groq-compatible integration.
- Pinned `langgraph==1.0.8` for reproducible setup.
- Bounded workflow request duration, provider retries, tool calls, and graph steps.
- Structured provider output with summary, hypotheses, evidence, computed results, limitations, next steps, and citations.
- Provider citations validated against retrieved evidence; numerical output replaced with deterministic results.
- Clarification and insufficient-evidence states for missing scope or data.
- Evidence-only fallback when LLM provider is disabled, unavailable, or returns invalid output.
- Added `/api/investigations/run` and `/api/investigations/{code}`.
- 6 investigation workflow tests + 1 live provider smoke test.

## Phase 4 - Tested Engineering Analytics

Completed:

- Typed analytics services for measurement summaries, OOS rate, trend comparison, tool usage, vibration baseline, diameter performance.
- Validation for finite values, units, spec ordering, sample count, missing data, and zero variance.
- Pp/Ppk from overall sigma only; Cp/Cpk withheld without within-process estimator.
- One-sided specifications return one-sided indices.
- Configurable demonstration policy thresholds via environment variables.
- Analytics responses include inputs, data window, sample count, method, units, tool version, results, and limitations.
- Ranked hypothesis/evidence service with associations labeled as hypotheses, not proven causes.
- Hand-verifiable analytics tests with reference fixtures.

## Phase 3 - Controlled Document Ingestion and Hybrid Evidence Retrieval

Completed:

- Controlled ingestion for PDF, Markdown, and TXT files with validation.
- Storage outside web root with checksums and safe names.
- Text extraction by headings/paragraphs; scanned PDFs flagged.
- Local deterministic sentence-embedding adapter with model identity tracking.
- Hybrid retrieval: exact identifier + lexical + semantic with reciprocal-rank fusion.
- Approval, effective-date, machine, superseded-revision, and embedding-compatibility filters.
- 14 synthetic reference Markdown documents indexed for retrieval testing.

## Phase 2 - Synthetic Manufacturing Dataset

Completed:

- Relational models with foreign keys, explicit units, timestamps, and indexes.
- Deterministic CNC-M04 synthetic seed with degrading pattern.
- Healthy comparison machine CNC-M02.
- One-sided and two-sided specifications.
- 40 batches, 400 measurements, telemetry, tool usage, maintenance events.
- Read-only APIs for dashboard summaries, machines, batches, measurements.

## Phase 1 - Prototype Foundation

Completed:

- FastAPI application with environment-driven settings.
- SQLAlchemy PostgreSQL with connection pre-ping.
- Alembic migration chain (5 revisions).
- Health and readiness endpoints.
- React + Vite + TypeScript frontend shell.
- Docker Compose for PostgreSQL.
- Request ID middleware and consistent error envelopes.

