-- Co-work v2: provider connections (CRM / portal / messaging / e-mail / calendar / AI)
-- and routines (scheduled workflows composed of connector, data and LLM steps).

create table if not exists public.cowork_connections (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  provider text not null,
  display_name text not null,
  config jsonb not null default '{}'::jsonb,          -- secrets stored here; never returned raw by the API
  status text not null default 'active' check (status in ('active','paused')),
  webhook_secret text,
  last_test_at timestamptz,
  last_test_status text check (last_test_status in ('ok','failed','skipped')),
  last_test_detail text,
  last_error text,
  last_activity_at timestamptz,
  received_total integer not null default 0,
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz
);
create index if not exists cowork_connections_ws_idx on public.cowork_connections (workspace_id, provider);

create table if not exists public.cowork_routines (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  name text not null,
  description text,
  schedule jsonb not null,
  steps jsonb not null default '[]'::jsonb,
  enabled boolean not null default true,
  template_id text,
  broker_id uuid,
  run_count integer not null default 0,
  last_run_at timestamptz,
  last_status text check (last_status in ('success','partial','failed')),
  next_run_at timestamptz,
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz
);
create index if not exists cowork_routines_due_idx on public.cowork_routines (workspace_id, enabled, next_run_at);

create table if not exists public.cowork_routine_runs (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  routine_id uuid references public.cowork_routines(id) on delete set null,
  routine_name text,
  trigger text not null,
  actor text,
  status text not null check (status in ('running','success','partial','failed')),
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  duration_ms integer,
  steps jsonb not null default '[]'::jsonb,
  summary jsonb not null default '{}'::jsonb,
  error text,
  created_at timestamptz not null default now()
);
create index if not exists cowork_routine_runs_ws_idx on public.cowork_routine_runs (workspace_id, started_at desc);

alter table public.cowork_tasks add column if not exists routine_id uuid;

alter table public.cowork_connections enable row level security;
alter table public.cowork_routines enable row level security;
alter table public.cowork_routine_runs enable row level security;

create policy cowork_connections_admin_all on public.cowork_connections for all
  using (public.has_workspace_role(workspace_id, array['owner','admin']))
  with check (public.has_workspace_role(workspace_id, array['owner','admin']));
create policy cowork_routines_admin_all on public.cowork_routines for all
  using (public.has_workspace_role(workspace_id, array['owner','admin']))
  with check (public.has_workspace_role(workspace_id, array['owner','admin']));
create policy cowork_routine_runs_admin_all on public.cowork_routine_runs for all
  using (public.has_workspace_role(workspace_id, array['owner','admin']))
  with check (public.has_workspace_role(workspace_id, array['owner','admin']));
