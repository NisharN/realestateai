-- Phase 7 hardening: follow-up retry bookkeeping.
alter table public.followups add column if not exists attempts integer not null default 0;

-- PDPL: audit trail for export/erasure requests, erasure marker on leads.
create table if not exists public.privacy_requests (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  lead_id uuid not null,
  kind text not null check (kind in ('export', 'erase')),
  status text not null default 'in_progress',
  reason text,
  requested_by text,
  detail jsonb,
  created_at timestamptz not null default now(),
  completed_at timestamptz
);
create index if not exists privacy_requests_ws_idx on public.privacy_requests (workspace_id, created_at desc);
alter table public.privacy_requests enable row level security;
drop policy if exists privacy_requests_ws on public.privacy_requests;
create policy privacy_requests_ws on public.privacy_requests for all
  using (public.has_workspace_role(workspace_id, array['owner','admin']))
  with check (public.has_workspace_role(workspace_id, array['owner','admin']));
alter table public.leads add column if not exists erased_at timestamptz;
