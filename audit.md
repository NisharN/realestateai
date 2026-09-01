# Project Audit: Dubai Real Estate AI

Date: July 28, 2026

## Executive Summary

This project has a strong prototype shape, but it is not yet a production-ready real estate lead platform.

The biggest issue is not that the code is completely broken. The bigger problem is that the repo presents itself as a full multi-agent, scraping, CRM, WhatsApp, voice, and dashboard platform, while a meaningful part of the implementation is still demo logic, mock data, placeholder fallbacks, or incomplete integrations.

Right now the project is best described as:

- A polished frontend demo that builds successfully
- A partially working FastAPI backend with mock-friendly fallbacks
- A believable but not fully real AI workflow
- Several production-critical paths that are incomplete or misleading

If someone deploys this as-is and expects the README promises to be true, they will hit failures, false positives, silent fallback behavior, and misleading outputs.

## What Each Folder Is Doing

### `backend/`

Purpose:
- FastAPI API server
- lead ingestion and conversation endpoints
- scraper entrypoints
- voice service
- agent orchestration
- data access layer

Reality:
- This is the real application core
- It is usable for demo flows
- It is not yet a fully trustworthy production backend

Important subfolders:

- `backend/app/api/`
  - HTTP and WebSocket routes
  - Main product behavior lives here

- `backend/app/agents/`
  - Contains the LangGraph orchestrator
  - This is the intended AI workflow brain
  - Most of the “multi-agent” behavior is implemented inside one file, not as truly separate operational agents

- `backend/app/scrapers/`
  - Playwright scrapers for Bayut, PropertyFinder, Dubizzle
  - Includes synthetic listing fallback behavior when scraping fails

- `backend/app/services/`
  - Voice service logic
  - Most important file here is `voice_service.py`

- `backend/app/models/`
  - Pydantic schemas for API responses and requests

- `backend/app/database.py`
  - Repository layer
  - Switches between Supabase and in-memory mock repositories

- `backend/mock_store.py`
  - In-memory demo persistence and demo properties/brokers
  - Useful for development, dangerous if mistaken for production behavior

### `frontend/`

Purpose:
- Next.js chat UI
- dashboard UI
- map modal
- voice modal

Reality:
- This is the strongest part of the repo from a presentation standpoint
- The app builds successfully in production mode
- But some frontend behavior assumes backend data shapes that do not actually match real property records
- The dashboard is mostly static mock data, not a real CRM dashboard

Important subfolders:

- `frontend/app/page.tsx`
  - Main chat experience
  - Lead capture, messaging, map modal, voice modal all converge here

- `frontend/app/dashboard/page.tsx`
  - Broker dashboard UI
  - Currently a static demo, not backed by live API data

- `frontend/lib/api.ts`
  - Frontend API client
  - This is where some request/response mismatches appear

### `docs/`

Purpose:
- Project explanation

Reality:
- Mostly aspirational documentation
- It describes a larger system than the repo currently implements

### `n8n-workflows/`

Purpose:
- Lead nurture automation

Reality:
- Concept only
- The JSON workflow is not integrated into the running backend
- Useful as an idea, not as a guaranteed working part of the product

### `scripts/`

Purpose:
- Setup and bootstrap scripts

Reality:
- `setup.sh` is outdated and references files/paths that do not exist in the current repo state
- This is one of the places that will confuse new setup attempts

## Actual Workflow in the Current Codebase

### 1. Lead intake

Main path:
- Frontend sends lead data to `POST /api/v1/leads/ingest`
- Backend creates a lead record
- Agent graph runs immediately

Status:
- Implemented
- Works best in mock/demo mode

Issues:
- lead ingestion stores the lead before any validation beyond schema basics
- no deduplication strategy
- no phone normalization
- no spam filtering
- no consent/compliance tracking

### 2. AI orchestration

Main path:
- `backend/app/agents/orchestrator.py`
- scoring -> qualifier -> research -> conversation -> handoff or nurture

Status:
- Implemented as a graph
- But not fully grounded in real data sources

What is real:
- LangGraph structure exists
- Groq integration exists
- fallback behavior is defensive

What is not truly production-grade:
- research uses mock property lists instead of querying real database inventory
- scoring and qualification are heavily prompt-driven without guardrails
- conversation/handoff logic is simplistic
- no durable agent memory beyond conversation history stored on the lead

### 3. Property matching

Main path:
- expected to happen in `research_agent`

Status:
- Conceptually present
- Operationally still demo logic

Problem:
- matching does not use the real `properties` table
- it compares against hardcoded mock properties
- this means “AI property matching” is not actually matching live scraped inventory

### 4. Conversation continuation

Main path:
- `POST /api/v1/leads/{lead_id}/message`

Status:
- Implemented

Problem:
- it rebuilds conversation state from stored history and re-runs the full graph from the graph entrypoint
- because the graph entrypoint is `scoring`, later conversation turns may re-run unrelated early-stage logic instead of continuing from the correct stage
- this is a major workflow design flaw

### 5. Human handoff

Main path:
- set `needs_human = True`
- try broker assignment

Status:
- Partially implemented

Problem:
- a broker brief is constructed in memory but never persisted or sent anywhere
- there is no real broker notification channel
- no CRM task creation
- no SLA enforcement

### 6. Scraping

Main path:
- `POST /api/v1/properties/scrape/bayut`
- `POST /api/v1/properties/scrape/propertyfinder`

Status:
- Code exists
- Live reliability is doubtful

Problem:
- selectors are fragile
- anti-bot bypass is optimistic
- when scraping fails, the code silently falls back to synthetic listings
- that is great for demos and terrible for production truthfulness

### 7. Voice

Main path:
- WebSocket `/api/v1/voice/conversation/{lead_id}`
- STT -> response -> TTS

Status:
- Only partially real

Problem:
- voice flow does not call the same conversation pipeline in the audio path
- `process_audio_stream()` mostly echoes a canned response instead of the real lead-matching workflow
- TTS fallback wraps MP3 bytes inside a WAV header, which is not a correct media conversion

### 8. Dashboard

Main path:
- `/dashboard`

Status:
- Frontend-only demo

Problem:
- uses mock stats and mock leads
- not integrated with backend APIs
- gives the impression of a CRM that does not yet exist

## What Is Working Well

- The repo structure is understandable
- The frontend production build succeeds
- The lead ingestion and chat shape are coherent
- The backend is designed to remain runnable even when Supabase or Groq are missing
- The mock repository approach is useful for local demos
- Pydantic models and repository layering are a good base
- The project has a clear product vision

## Major Production Failure Points

### 1. Conversation messages restart the whole graph

Why this fails:
- `agent_graph` always starts at `scoring`
- sending a new lead message should continue at the conversation stage or a persisted workflow state
- instead, later turns can be re-routed unexpectedly

Impact:
- inconsistent conversation behavior
- repeated scoring
- unstable user experience

Severity:
- Critical

### 2. Research agent does not use real property inventory

Why this fails:
- property matching is based on hardcoded mock property data
- real scraped and stored properties are ignored during matching

Impact:
- users can be shown recommendations disconnected from your real inventory
- “AI matching” is misleading

Severity:
- Critical

### 3. Scraper endpoints can return fake inventory silently

Why this fails:
- `scrape_*_safe()` falls back to synthesized listings when real scraping fails
- the API does not force clear differentiation between synthetic and real operational results

Impact:
- false inventory in database
- sales team can act on fake listings
- production trust damage

Severity:
- Critical

### 4. Frontend and backend request shape mismatch on scrape endpoints

Why this fails:
- frontend `propertiesApi.scrapeBayut()` sends JSON body
- backend endpoint defines plain function parameters, not a Pydantic body model
- request may not behave as the frontend expects

Impact:
- scrape trigger from frontend likely unreliable

Severity:
- High

### 5. Lead assignment API shape mismatch

Why this fails:
- frontend sends `{ broker_id: ... }` JSON
- backend `assign_lead()` expects `broker_id: str` directly as a function parameter

Impact:
- assign action will fail or parse incorrectly when wired to UI

Severity:
- High

### 6. WhatsApp webhook does not send responses back to WhatsApp

Why this fails:
- inbound webhook processing exists
- outbound WhatsApp response is still `TODO`

Impact:
- webhook may ingest or process the message, but the user never receives the bot reply on WhatsApp

Severity:
- High

### 7. Voice path is not the same as the chat path

Why this fails:
- voice processing produces generic responses instead of real agent-orchestrated lead handling

Impact:
- voice and chat will diverge in behavior
- inconsistent product experience

Severity:
- High

### 8. TTS fallback is technically incorrect

Why this fails:
- gTTS returns MP3
- code wraps MP3 bytes in a WAV header rather than actually transcoding

Impact:
- playback incompatibility
- corrupted or misdetected audio in some clients

Severity:
- High

### 9. Setup script is stale

Why this fails:
- references `02_env_example`, which does not exist
- creates folders that do not match the current repo’s actual implementation

Impact:
- first-time setup confusion
- loss of trust immediately after clone

Severity:
- High

### 10. Security defaults are not production-safe

Why this fails:
- CORS allows `*`
- raw exception text is returned to clients
- webhook validation is minimal
- no auth on sensitive routes

Impact:
- security exposure
- internal errors leaked to users

Severity:
- High

## Medium-Risk Issues

### 1. Mock mode is too invisible

The system silently downgrades into mock repositories and demo behavior. That is useful for development, but dangerous if operators think they are using live data.

What should happen instead:
- expose environment mode clearly
- return explicit flags such as `data_mode: mock`
- log loudly on startup

### 2. Dashboard is not connected to real backend data

This is okay for a demo, but not okay if advertised as a working CRM dashboard.

### 3. Database layer uses sync-style Supabase calls inside async endpoints

This may be acceptable at low volume, but it can become a bottleneck.

### 4. No tests are present for the real business flows

You have dependencies for testing, but there are no actual backend tests covering:
- lead ingest
- conversation continuation
- broker handoff
- scraper normalization
- voice fallback behavior

### 5. Docker story is incomplete

The Dockerfiles exist, but the backend image pulls large browser and TTS dependencies, increasing build fragility and startup cost. It is more like a heavy demo container than a lean production service.

### 6. README overpromises relative to current code

This is a trust problem. The gap between repo claims and actual implementation is large.

## Things Already Added That Are Useful

Keep these:

- repository abstraction in `backend/app/database.py`
- mock store for local demo mode
- LangGraph-based orchestration scaffold
- scraper normalization layer
- frontend chat UX
- production buildable Next.js app
- SQL schema as a starting point

These are genuinely helpful foundations.

## Things Already Added That Should Be Reworked or Removed

### Rework, not remove

- synthetic scraper fallback
  - keep for local demo only
  - never blend into production inventory

- mock property matching inside orchestrator
  - replace with real repository-backed search

- voice fallback stack
  - keep the idea
  - fix the actual media pipeline

### Remove or sharply reduce

- aspirational README claims that are not implemented
- stale setup instructions
- unused or not-yet-integrated production-looking dependencies:
  - `celery`
  - `redis`
  - `apscheduler`
  - maybe `scrapy`
  - maybe `python-socketio`

Right now these add complexity without clear integrated value in the current codebase.

Only keep them if you are actively about to wire them in.

## Likely Unnecessary Right Now

- `redis` service in `docker-compose.yml`
  - not used by current runtime paths

- `celery` and `apscheduler`
  - no worker flow is wired in

- `n8n` container by default
  - useful later, but not required for the current core app

- broad image remote pattern in Next config
  - too permissive for production

## Missing Things You Need Before Production

### Product correctness

- real property search in the research agent
- real broker handoff persistence and notification
- true conversation state management
- deduplication and normalization for leads
- outbound WhatsApp sending
- actual CRM dashboard wiring

### Reliability

- tests for critical API flows
- health checks that test real dependencies
- startup validation for required services
- explicit “mock mode” indicator
- proper retries and timeouts around external APIs

### Security

- route authentication and role authorization
- restricted CORS
- no raw exception leakage
- webhook signature verification where applicable
- rate limiting
- secrets handling documentation

### Data

- migration strategy
- seeded dev fixtures separate from production behavior
- audit logs
- idempotency for webhook and lead ingestion flows

### Operations

- `.env.example`
- deployment guide matching real code
- logging/monitoring strategy
- background job system only if actually used

## Folder-by-Folder Judgment

### `backend/app/api`
- Needed
- Core of the product
- Must be hardened

### `backend/app/agents`
- Needed
- But needs real state and real inventory integration

### `backend/app/scrapers`
- Needed if scraping is truly part of the business
- Must stop silently pretending fake data is real

### `backend/app/services`
- Needed
- Voice service needs major correction

### `backend/app/mock_store.py`
- Needed for development
- Should never be mistaken for production persistence

### `frontend/app/dashboard`
- Keep only if you plan to wire it soon
- Otherwise it currently acts more like demo marketing than product

### `n8n-workflows`
- Optional
- Keep as future automation reference
- Do not present as already integrated

### `scripts/setup.sh`
- Needs rewrite
- Current version is misleading

## Recommended Order of Fixes

### Phase 1: Fix truthfulness and broken workflow

1. Stop using synthetic scraper results in production paths
2. Make conversation continuation start from the correct stage, not from scoring
3. Replace mock property matching with repository-backed search
4. Fix frontend/backend payload mismatches
5. Remove or mark clearly all demo-only behavior

### Phase 2: Make core backend genuinely usable

1. Implement real broker handoff persistence
2. Implement outbound WhatsApp responses
3. Add lead deduplication and validation
4. Add tests for ingest, message, handoff, and search flows
5. Add auth and safe error handling

### Phase 3: Make supporting surfaces real

1. Wire dashboard to backend APIs
2. Fix voice pipeline so it uses the same AI workflow as chat
3. Rewrite setup/deployment docs
4. Trim unused dependencies and services

## Final Verdict

You are not “going wrong” because the idea is bad. The idea is actually clear and ambitious.

Where you are going wrong is this:

- you built a convincing product shell faster than the real operational core
- demo fallbacks are mixed too closely with production behavior
- several parts are presented as integrated when they are still placeholders
- the system currently optimizes for looking complete rather than being reliably correct

The most important shift now is:

Build less surface area, but make the core path fully real.

That core path should be:

1. ingest real lead
2. store in real database
3. continue real conversation state
4. match against real property inventory
5. assign real broker
6. notify through real channel

Once that path is solid, everything else becomes easier.

## Validation Notes

What I verified directly:

- frontend production build succeeded on July 28, 2026
- repo structure and runtime files were reviewed end to end
- API, orchestration, scraping, voice, schema, Docker, and setup files were inspected

What I could not fully verify in this environment:

- backend runtime execution with installed Python dependencies
- live Supabase integration
- live scraper success against target websites
- live WhatsApp, Groq, or voice service integrations

