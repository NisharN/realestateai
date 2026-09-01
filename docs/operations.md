# Production operations

Deploy the frontend to Vercel and create three Railway services from `backend`: web, worker, and beat. Each environment uses a separate Supabase project, Redis instance, Stripe webhook endpoint, Meta application, and provider credentials.

## Migration procedure

1. Back up the target Supabase database.
2. Run migrations in filename order from `backend/supabase/migrations` in staging.
3. Execute the RLS and cross-tenant test matrix with two real auth users.
4. Promote the same migration to production during a monitored window.
5. Roll back by restoring the pre-migration backup. The tenant-key migration is intentionally not reversed with destructive SQL.

## Provider outage response

- OpenAI Realtime: switch the workspace voice provider to transcription/LangGraph/gTTS fallback.
- Groq: stop new AI execution, preserve inbound events, and retry bounded jobs after recovery.
- Meta: acknowledge verified webhooks quickly, queue processing, and replay idempotently using provider event IDs.
- Stripe: keep the last verified lifecycle state and replay signed webhook events after service recovery.

## Data policy

Retain leads and transcripts for 24 months. Do not retain raw audio. Owner-authorized export and deletion jobs must be audited with workspace, actor, correlation, and job identifiers while excluding message bodies and secrets from logs.
