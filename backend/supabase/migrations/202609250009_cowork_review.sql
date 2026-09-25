-- Co-work review follow-ups (PR #22):
--  * automation audit rows survive rule deletion (set null, name is kept)
--  * one durable claim per (automation, event) with attempt counting so failed
--    actions can be retried without replaying successful ones
--  * per-job execution lease so overlapping workers cannot run the same job

alter table public.cowork_automation_runs
  drop constraint if exists cowork_automation_runs_automation_id_fkey;
alter table public.cowork_automation_runs
  alter column automation_id drop not null;
alter table public.cowork_automation_runs
  add constraint cowork_automation_runs_automation_id_fkey
  foreign key (automation_id) references public.cowork_automations(id) on delete set null;

alter table public.cowork_automation_runs
  add column if not exists attempts integer not null default 1,
  add column if not exists updated_at timestamptz;
alter table public.cowork_automation_runs
  drop constraint if exists cowork_automation_runs_status_check;
alter table public.cowork_automation_runs
  add constraint cowork_automation_runs_status_check
  check (status in ('running','fired','failed'));

create unique index if not exists cowork_automation_runs_claim_idx
  on public.cowork_automation_runs (workspace_id, automation_id, event_id)
  where automation_id is not null and event_id is not null;
create index if not exists cowork_automation_runs_retry_idx
  on public.cowork_automation_runs (workspace_id, status, created_at);

create table if not exists public.cowork_job_leases (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  job_id text not null,
  holder text not null,
  lease_until timestamptz not null,
  updated_at timestamptz not null default now(),
  unique (workspace_id, job_id)
);

alter table public.cowork_job_leases enable row level security;
create policy cowork_job_leases_admin_all on public.cowork_job_leases for all
  using (public.has_workspace_role(workspace_id, array['owner','admin']))
  with check (public.has_workspace_role(workspace_id, array['owner','admin']));
