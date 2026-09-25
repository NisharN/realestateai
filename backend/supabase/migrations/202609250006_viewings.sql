-- Phase 8: viewing requests/bookings carry provenance and a modification timestamp.
alter table public.viewings add column if not exists source text not null default 'broker';
alter table public.viewings add column if not exists updated_at timestamptz not null default now();
create index if not exists viewings_ws_lead_idx on public.viewings (workspace_id, lead_id, status);
create index if not exists viewings_ws_broker_start_idx on public.viewings (workspace_id, broker_id, starts_at);
