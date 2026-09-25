# Deployment runbook

One stack per brokerage (`WORKSPACE_ID`). Everything below is `docker compose`
on a single host; the same env vars apply to Railway/Fly/ECS if you split the
services out.

Services: `backend` (FastAPI), `celery-worker`, `celery-beat`, `redis`,
`frontend` (Next.js). Optional profiles: `db` (local Postgres with migrations,
for tests), `osrm` (see `osrm.md`).

## 1. Prerequisites

| Dependency          | Needed for                                   | Without it                                   |
|---------------------|----------------------------------------------|----------------------------------------------|
| Supabase project    | all persistence + auth + RLS                 | in-memory store, data lost on restart        |
| Redis               | Celery (schedules, follow-ups, write-back)   | worker/beat cannot start                     |
| Groq API key        | LLM extraction/phrasing, Whisper STT         | deterministic templates, browser STT         |
| Meta WhatsApp app   | WhatsApp channel                             | web chat + voice only                        |
| CRM credentials     | CRM pull + write-back                        | CSV/webhook intake only                      |
| OSRM data           | real travel times                            | labelled straight-line estimates             |
| Piper voices        | server TTS                                   | browser speech synthesis                     |

## 2. Database

Apply `backend/supabase/migrations/*.sql` **in filename order** with the
Supabase SQL editor or `supabase db push`. The chain starts with
`202608110000_baseline.sql` and is idempotent, so re-running is safe.

Rehearse on a throwaway Postgres first — this is exactly what CI-less
verification looks like:

```bash
docker compose --profile db up -d postgres
docker compose logs -f postgres | grep -E "applying|ERROR"
docker compose exec postgres psql -U postgres -d realestateai -c \
  "select count(*) filter (where rowsecurity) as rls, count(*) as tables from pg_tables where schemaname='public'"
docker compose --profile db down -v
```

Every table must have RLS enabled (`rls == tables`). Then run the cross-tenant
matrix from `docs/operations.md` with two real auth users.

## 3. Environment

Copy and fill; **never** commit this file.

```bash
APP_ENV=production            # disables DEMO_AUTH regardless of its value
WORKSPACE_ID=<uuid>           # from public.workspaces
WORKSPACE_NAME=<brokerage>
CORS_ORIGINS=https://app.<brokerage>.ae
SUPABASE_URL=...
SUPABASE_KEY=...              # anon key (frontend + user-scoped calls)
SUPABASE_SERVICE_KEY=...      # backend only
REDIS_URL=redis://redis:6379/0
GROQ_API_KEY=...
LLM_PROVIDERS=groq            # add ",secondary" / ",ollama" once configured
WEBHOOK_SIGNING_SECRET=<32+ random bytes>   # required for /api/v1/ingest/webhook/{connector_id}
WHATSAPP_ACCESS_TOKEN=... WHATSAPP_PHONE_NUMBER_ID=... WHATSAPP_VERIFY_TOKEN=... META_APP_SECRET=...
DATA_MODE_PROPERTIES=live DATA_MODE_WHATSAPP=live
RETENTION_RAW_DAYS=90 RETENTION_LEAD_DAYS=730
NEXT_PUBLIC_API_URL=https://api.<brokerage>.ae
```

Leave every `FAULT_*` unset in production.

```bash
docker compose up -d --build
curl -s localhost:8000/health | jq
```

`/health` reports each dependency as `configured` or `mock`; a live instance
must show no `mock` entries.

## 4. First-run checklist

1. Invite the owner via the admin UI (Supabase auth email).
2. Add brokers and set specialisms/areas so routing has somewhere to go.
3. Upload the listings CSV (or configure the properties feed) — recommendations
   only ever come from stored inventory.
4. Configure the CRM connector (admin → Connectors → test connection → run now)
   and check the review queue.
5. Seed travel times: `python -m scripts.osrm_precompute --straight-line`,
   then follow `osrm.md`.
6. Register the WhatsApp webhook URL `https://api.../api/v1/webhooks/whatsapp` with the
   verify token; send a test message and confirm the reply.
7. Run the offline evals against the deployed image:
   `docker compose exec backend python -m scripts.run_evals` (46/46 expected).

## 5. Scheduled work (Celery beat)

| Task                            | Interval | What it does                                              |
|---------------------------------|----------|-----------------------------------------------------------|
| dispatch-due-ingestion-schedules| 60 s     | enqueue due connector schedules                           |
| poll-pull-connectors            | 60 s     | CRM pull (changed-since paging)                           |
| retry-ingestion-errors          | 2 min    | re-process stranded raw records                           |
| send-due-followups              | 5 min    | buyer follow-ups; failed sends stay due                   |
| run-workflow-templates          | 5 min    | workflow builder templates                                |
| reassign-stale-handoffs         | 60 s     | broker didn't accept within `HANDOFF_REASSIGN_MINUTES`    |
| crm-writeback                   | 60 s     | idempotent outbox → CRM                                   |
| retention-purge                 | 24 h     | PDPL: drop raw payloads > `RETENTION_RAW_DAYS`, erase idle unconverted leads > `RETENTION_LEAD_DAYS` |

Run any of them on demand:
`docker compose exec celery-worker celery -A app.worker.celery_app call app.worker.retention_purge`.

## 6. PDPL data-subject requests (admin/owner only)

```
GET    /api/v1/admin/privacy/leads/{lead_id}/export   → full JSON of everything stored for the lead
DELETE /api/v1/admin/privacy/leads/{lead_id}          → erase PII, add contacts to suppression, keep id + aggregates
POST   /api/v1/admin/privacy/leads/{lead_id}/consent  → {"purpose":"marketing","granted":false,...}
GET    /api/v1/admin/privacy/requests                 → audit log
POST   /api/v1/admin/privacy/retention/run            → run the purge now
```

Each request is written to `privacy_requests` **before** any mutation, so an
interrupted erase is visible as `in_progress` and can be re-run (idempotent).

## 7. Fault drills

Run each before the pilot, on staging, with the voice and chat UIs open:

| Flag                 | Expected behaviour                                                        |
|----------------------|---------------------------------------------------------------------------|
| `FAULT_LLM_ALL=true` | every turn still gets a reply from templates; no `error_fallback` moves   |
| `FAULT_STT=true`     | voice UI shows "didn't catch that", browser STT / typing still works      |
| `FAULT_TTS=true`     | replies are spoken by the browser (`speak` frames instead of `audio`)     |
| `FAULT_DB_SLOW_MS=800` | chat replies still arrive inside `TURN_DEADLINE_CHAT_S`; voice may fall back to text |

Automated equivalents live in `backend/tests/test_privacy_faults.py`.

## 8. Upgrade

```bash
git pull
# apply any new files in backend/supabase/migrations first (step 2)
docker compose build backend frontend
docker compose up -d
docker compose exec backend python -m scripts.run_evals
```

Roll back by checking out the previous tag and `docker compose up -d --build`;
migrations are additive and do not need reversing.

## 9. Monitoring

- `GET /health` every 30 s (any `mock` in production → page).
- Celery: `celery -A app.worker.celery_app inspect ping`.
- Admin → Data health: review-queue depth, stranded raw records, stale listings.
- Logs never contain message bodies, phone numbers, or secrets; anything that
  looks like one is a bug — see `docs/operations.md`.
