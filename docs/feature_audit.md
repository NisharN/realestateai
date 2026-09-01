# Feature Audit — Dubai Real Estate AI

Date: 2026-08-15. Scope: every backend and frontend feature currently in the codebase, verdict on whether each is needed, and its actual working status (verified by reading the code — no execution was possible in this session).

## Headline: your "schedule" error, explained

The ingestion-schedule feature is two layers deep and only the top layer is real. `backend/app/api/ingestion.py` fully implements `GET/POST /schedules` and `GET /runs` against real `ingestion_schedules`/`job_runs` tables — that part works. But the Celery task that's supposed to actually run a schedule, `run_ingestion_schedule` in `backend/app/worker.py`, ends with only a comment:

`# Source-specific import execution is intentionally delegated to the existing PropertyIngestionService in a subsequent task implementation.`

It fetches the schedule row and stops — it never calls `PropertyIngestionService`. On top of that, `docker-compose.yml` only defines `backend`, `frontend`, `redis`, and `n8n` — there is no `celery-worker` or `celery-beat` service, so even a correctly-written task has nothing running it. Creating a schedule succeeds (it's just a database insert); anything that expects it to actually import properties on a timer will fail or silently do nothing. That's almost certainly what you hit.

Fix requires two things: finish `run_ingestion_schedule` to call `PropertyIngestionService` for the schedule's source, and add `celery-worker` + `celery-beat` services to docker-compose. I haven't made this change yet — flagging it here since it's the concrete answer to your report.

## Feature-by-feature verdict

| Feature | Status | Verdict |
|---|---|---|
| Multi-tenancy (`workspace_id` scoping) | **Real.** Every repository (Lead, Property, Conversation, Broker, Activity, Workspace) takes `workspace_id` and filters on it, in both the Supabase-backed and mock-store implementations. This was the single biggest gap in PROJECT.md's Phase 1 — it's done. | Needed. Keep. |
| Supabase auth + `RequestContext` | Real. Validates bearer tokens, resolves `workspace_members`, supports the `X-Workspace-ID` header for multi-workspace users, role-gates via `require_roles()`. | Needed. Keep. |
| Billing (Stripe Checkout + Portal) | Real. Owner-only, ties into `WorkspaceLifecycle` (draft/active/grace/read_only/suspended) via `require_service_enabled()`. Matches your subscription-mode plan. | Needed. Keep. |
| Members & invitations | Real. Supabase `invite_user_by_email`, hashed-token `workspace_invitations`, accept flow. | Needed. Keep. |
| Voice pipeline (STT → agent → TTS) | Real, and this was one of the two "fake" features I fixed earlier — it used to echo audio back. Now: Groq Whisper STT (Hugging Face fallback) → real agent response via the same pipeline as text chat → TTS. | Needed. Keep — this is the differentiator vs. text-only competitors. |
| Property matching | Real, the other fixed fake feature. Was hardcoded to 3 fake listings; now scores real inventory against lead preferences (property type, area, budget, amenities) with an LLM-polish pass on the top matches. | Needed. Keep. |
| Configure wizard (workspace setup) | Real. Team/data-sources/channels persist through a real API, CSV import writes real properties, data-source "test" calls a real endpoint. This is your light-FDE onboarding flow. | Needed. Keep — it's the core of the FDE-to-configurable-product pitch. |
| Ingestion scheduling | **Half-real — this is the bug you hit.** API/CRUD layer is real; execution layer (`run_ingestion_schedule`) is an unfinished stub, and docker-compose has no worker/beat process to run it even once finished. | Needed, but currently broken. Fix before relying on it. |
| Dashboard — stat cards | Real. `dashboardApi.summary()` returns live totals/qualified/closed/avg-intent, workspace- and role-scoped. | Needed. Keep. |
| Dashboard — pipeline board & leads table | **Fake.** Still rendering a hardcoded `MOCK_LEADS` array even though the stat cards above them on the same page are live. Inconsistent — a user will see accurate counts next to leads that don't exist. | Needed, but broken. Wire to `leadsApi.list()`. |
| WhatsApp webhook | Correctly stubbed, not fake. `/whatsapp` verifies Meta's HMAC signature (real security work) then explicitly returns 503 "channel_not_configured" rather than pretending to send. Honest incompleteness. | Needed eventually (it's your primary lead channel per the product framing); fine to leave stubbed until Phase 4 send-side work is prioritized. |
| Website-widget webhook | Same pattern — fails closed with 401 "widget_key_required" instead of faking success. | Same as above. |
| Bayut/Dubizzle scraping | Gated off by default behind `ENABLE_BAYUT_DUBIZZLE_SCRAPING` (added earlier per the anti-bot/CAPTCHA finding). Endpoints still exist for anyone who wants to opt in with real proxy infra. | Correctly deferred — leave off by default. |
| Property Finder, CSV/CRM import, approved feed, RapidAPI | Real, enabled. | Needed. Keep. |
| In-app docs page (`/docs`) | Real static content — architecture, feature status, how Configure maps to backend, roadmap. | Cheap and useful for an FDE handoff story. Keep. |
| `n8n` service (docker-compose) + `nurture.json` workflow | Exists but nothing in the backend triggers it. It's a second, disconnected mechanism for scheduled lead nurture, sitting alongside the also-half-built Celery ingestion scheduler. Two schedulers, neither fully wired to the thing users actually asked for (automated nurture messages). | Not needed as-is. Pick one scheduling mechanism (Celery, since it already has the schedules API and DB tables) and drop n8n, or explicitly commit to n8n and rip out the Celery scaffolding. Running both is confusing and doubles your ops surface. |
| `SENTRY_DSN` / `OPENAI_API_KEY` settings | Declared in `config.py`, never read anywhere else in the backend. Dead config — `sentry_sdk` is a dependency but never initialized. | Not needed yet. Either wire up Sentry init or remove the setting until you do. |
| `MAPBOX_ACCESS_TOKEN` / `NEXT_PUBLIC_MAPBOX_TOKEN` (docker-compose) | Frontend maps use Leaflet/OpenStreetMap (free, no token), confirmed earlier — Mapbox was a README claim that was never real. These env vars are leftover cruft. | Not needed. Remove from docker-compose. |
| Duplicate SQL schema (`database_schema.sql` vs `01_database_schema.sql`) | Both files still exist; unclear which is authoritative. | Not needed as two files. Merge into one, delete the other. |
| `requirements.txt` comment about cutting celery/redis | Comment says these were cut "per the product/market review"; five lines later `celery`, `redis`, `stripe`, `sentry-sdk` are all listed as dependencies. Self-contradicting. | Hygiene fix — delete the stale comment. |

## Net read

The product moved a lot since the POC: real auth, real billing, real multi-tenancy, real members/invitations, and both previously-fake features (voice, matching) are genuinely fixed. That's the hard, valuable part and it's in good shape.

What's left is mostly finishing half-built things rather than building new ones: the ingestion scheduler needs its execution half and a worker/beat process; the dashboard needs its pipeline board and leads table switched from mock to `leadsApi.list()`; and there's a handful of small cleanup items (dead config, stale env vars, duplicate schema file, contradictory comment) that cost nothing to fix and would stop confusing whoever touches this next.

I'd sequence it: (1) fix the scheduler since it's the thing that's actively erroring for you, (2) wire the dashboard's leads table to real data since it's actively misleading, (3) decide n8n vs. Celery and drop the loser, (4) sweep the small hygiene items.
