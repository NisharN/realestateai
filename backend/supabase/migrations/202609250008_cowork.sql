-- Co-work: job settings + run history, task automations + firings, broker tasks.

create table if not exists public.cowork_job_settings (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  job_id text not null,
  enabled boolean,
  interval_s integer,
  updated_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  unique (workspace_id, job_id)
);

create table if not exists public.cowork_job_runs (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  job_id text not null,
  trigger text not null check (trigger in ('schedule','manual','automation')),
  actor text,
  status text not null check (status in ('running','success','failed')),
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  duration_ms integer,
  summary jsonb not null default '{}'::jsonb,
  error text,
  created_at timestamptz not null default now()
);
create index if not exists cowork_job_runs_ws_idx on public.cowork_job_runs (workspace_id, job_id, started_at desc);

create table if not exists public.cowork_automations (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  name text not null,
  description text,
  trigger text not null,
  conditions jsonb not null default '[]'::jsonb,
  action text not null,
  action_params jsonb not null default '{}'::jsonb,
  enabled boolean not null default true,
  run_count integer not null default 0,
  last_run_at timestamptz,
  last_status text,
  created_by text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.cowork_automation_runs (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  automation_id uuid not null references public.cowork_automations(id) on delete cascade,
  automation_name text,
  event_id uuid,
  event_type text,
  lead_id uuid,
  status text not null check (status in ('fired','failed')),
  result jsonb not null default '{}'::jsonb,
  error text,
  created_at timestamptz not null default now()
);
create index if not exists cowork_automation_runs_ws_idx on public.cowork_automation_runs (workspace_id, created_at desc);

create table if not exists public.cowork_tasks (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  lead_id uuid,
  broker_id uuid,
  automation_id uuid,
  title text not null,
  due_in_hours integer not null default 24,
  status text not null default 'open' check (status in ('open','done','dismissed')),
  created_at timestamptz not null default now(),
  updated_at timestamptz
);
create index if not exists cowork_tasks_ws_idx on public.cowork_tasks (workspace_id, status, created_at desc);

alter table public.cowork_job_settings enable row level security;
alter table public.cowork_job_runs enable row level security;
alter table public.cowork_automations enable row level security;
alter table public.cowork_automation_runs enable row level security;
alter table public.cowork_tasks enable row level security;

create policy cowork_job_settings_admin_all on public.cowork_job_settings for all
  using (public.has_workspace_role(workspace_id, array['owner','admin']))
  with check (public.has_workspace_role(workspace_id, array['owner','admin']));
create policy cowork_job_runs_admin_all on public.cowork_job_runs for all
  using (public.has_workspace_role(workspace_id, array['owner','admin']))
  with check (public.has_workspace_role(workspace_id, array['owner','admin']));
create policy cowork_automations_admin_all on public.cowork_automations for all
  using (public.has_workspace_role(workspace_id, array['owner','admin']))
  with check (public.has_workspace_role(workspace_id, array['owner','admin']));
create policy cowork_automation_runs_admin_all on public.cowork_automation_runs for all
  using (public.has_workspace_role(workspace_id, array['owner','admin']))
  with check (public.has_workspace_role(workspace_id, array['owner','admin']));
create policy cowork_tasks_admin_all on public.cowork_tasks for all
  using (public.has_workspace_role(workspace_id, array['owner','admin']))
  with check (public.has_workspace_role(workspace_id, array['owner','admin']));
