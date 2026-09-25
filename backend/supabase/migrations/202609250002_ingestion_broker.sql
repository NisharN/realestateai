-- Ingestion pipeline (connectors, raw records, field maps, review queue, sources,
-- change log, suppression, outbox offsets) and broker workspace (follow-ups, viewings).
begin;

-- Architecture-shaped lead columns alongside the legacy dashboard columns.
alter table public.leads
  add column if not exists phone_e164 text,
  add column if not exists purpose text,
  add column if not exists budget_min_aed numeric(15,2),
  add column if not exists budget_max_aed numeric(15,2),
  add column if not exists budget_period text,
  add column if not exists community_ids jsonb not null default '[]'::jsonb,
  add column if not exists property_types jsonb not null default '[]'::jsonb,
  add column if not exists bedrooms_min integer,
  add column if not exists payment text,
  add column if not exists language text,
  add column if not exists score integer not null default 0,
  add column if not exists score_reasons jsonb not null default '[]'::jsonb,
  add column if not exists band text,
  add column if not exists stage text not null default 'new',
  add column if not exists consent jsonb not null default '{}'::jsonb,
  add column if not exists crm_external_id text,
  add column if not exists initial_message text,
  add column if not exists notes text,
  add column if not exists extra jsonb not null default '{}'::jsonb,
  add column if not exists buyer_confirmed_fields jsonb not null default '[]'::jsonb,
  add column if not exists broker_edited_fields jsonb not null default '[]'::jsonb,
  add column if not exists opted_out_at timestamptz;

update public.leads set phone_e164 = phone where phone_e164 is null and phone like '+%';
create index if not exists leads_phone_idx on public.leads (workspace_id, phone);
create index if not exists leads_phone_e164_idx on public.leads (workspace_id, phone_e164);
create index if not exists leads_email_idx on public.leads (workspace_id, lower(email));
create index if not exists leads_stage_idx on public.leads (workspace_id, stage, assigned_broker);

alter table public.handoffs
  add column if not exists reassigned_from uuid,
  add column if not exists decline_reason text,
  add column if not exists declined_at timestamptz,
  add column if not exists escalated_at timestamptz;

create table if not exists public.connectors (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  type text not null check (type in ('csv_upload','webhook','google_sheets','portal_email','hubspot','zoho','salesforce','bitrix24','whatsapp','manual')),
  mode text not null default 'push' check (mode in ('pull','push')),
  display_name text not null,
  status text not null default 'active' check (status in ('active','paused','disabled')),
  config jsonb not null default '{}'::jsonb,
  secret text,
  auth_encrypted text,
  schedule_seconds integer,
  cursor text,
  last_run_at timestamptz,
  last_success_at timestamptz,
  last_error text,
  consecutive_failures integer not null default 0,
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists connectors_ws_idx on public.connectors (workspace_id, status);

create table if not exists public.field_maps (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  connector_id uuid not null references public.connectors(id) on delete cascade,
  source_field text not null,
  target_field text,
  transform text,
  approved boolean not null default false,
  approved_by uuid,
  approved_at timestamptz,
  created_at timestamptz not null default now(),
  unique (workspace_id, connector_id, source_field)
);

create table if not exists public.raw_lead_records (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  connector_id uuid references public.connectors(id) on delete set null,
  external_id text,
  content_hash text not null,
  payload jsonb not null,
  source_hint text,
  status text not null default 'landed'
    check (status in ('landed','mapped','cleaned','validated','merged','enriched','published','review','error')),
  attempts integer not null default 0,
  error text,
  lead_id uuid,
  received_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (workspace_id, content_hash)
);
create index if not exists raw_records_status_idx on public.raw_lead_records (workspace_id, status, updated_at);
create index if not exists raw_records_connector_idx on public.raw_lead_records (workspace_id, connector_id, received_at desc);

create table if not exists public.review_queue (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  raw_record_id uuid not null references public.raw_lead_records(id) on delete cascade,
  reason text not null,
  draft jsonb not null default '{}'::jsonb,
  suggested_fix jsonb,
  status text not null default 'open' check (status in ('open','resolved','discarded')),
  resolution text,
  resolved_by uuid,
  resolved_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists review_queue_open_idx on public.review_queue (workspace_id, status, created_at);

create table if not exists public.lead_sources (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  lead_id uuid not null,
  source text not null,
  external_id text,
  listing_ref text,
  raw_record_id uuid references public.raw_lead_records(id) on delete set null,
  first_seen_at timestamptz not null default now(),
  foreign key (workspace_id, lead_id) references public.leads(workspace_id, id) on delete cascade
);
create unique index if not exists lead_sources_unique_idx
  on public.lead_sources (workspace_id, lead_id, source, coalesce(external_id, ''));

create table if not exists public.lead_change_log (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  lead_id uuid not null,
  field text not null,
  old_value jsonb,
  new_value jsonb,
  changed_by text not null,
  user_id uuid,
  raw_record_id uuid,
  at timestamptz not null default now(),
  foreign key (workspace_id, lead_id) references public.leads(workspace_id, id) on delete cascade
);
create index if not exists lead_change_log_lead_idx on public.lead_change_log (workspace_id, lead_id, at);

create table if not exists public.suppression_list (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  phone text,
  email text,
  reason text,
  created_at timestamptz not null default now()
);
create index if not exists suppression_phone_idx on public.suppression_list (workspace_id, phone);
create index if not exists suppression_email_idx on public.suppression_list (workspace_id, lower(email));

create table if not exists public.consumer_offsets (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  consumer text not null,
  event_id uuid not null references public.lead_events(id) on delete cascade,
  processed_at timestamptz not null default now(),
  unique (workspace_id, consumer, event_id)
);

create table if not exists public.followups (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  lead_id uuid not null,
  band text,
  touch integer not null default 1,
  template_key text not null,
  channel text not null default 'whatsapp',
  due_at timestamptz not null,
  status text not null default 'pending' check (status in ('pending','sent','failed','cancelled')),
  cancel_reason text,
  text text,
  error text,
  sent_at timestamptz,
  created_at timestamptz not null default now(),
  foreign key (workspace_id, lead_id) references public.leads(workspace_id, id) on delete cascade
);
create index if not exists followups_due_idx on public.followups (workspace_id, status, due_at);

create table if not exists public.viewings (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  lead_id uuid not null,
  broker_id uuid references public.brokers(id) on delete set null,
  property_id uuid,
  starts_at timestamptz,
  status text not null default 'requested' check (status in ('requested','confirmed','done','no_show','cancelled')),
  notes text,
  created_at timestamptz not null default now(),
  foreign key (workspace_id, lead_id) references public.leads(workspace_id, id) on delete cascade
);
create index if not exists viewings_broker_idx on public.viewings (workspace_id, broker_id, starts_at);

-- RLS: ingestion/admin tables are owner/admin only; broker tables follow lead access.
alter table public.connectors enable row level security;
alter table public.field_maps enable row level security;
alter table public.raw_lead_records enable row level security;
alter table public.review_queue enable row level security;
alter table public.lead_sources enable row level security;
alter table public.lead_change_log enable row level security;
alter table public.suppression_list enable row level security;
alter table public.consumer_offsets enable row level security;
alter table public.followups enable row level security;
alter table public.viewings enable row level security;

create policy connectors_admin_all on public.connectors for all
  using (public.has_workspace_role(workspace_id, array['owner','admin']))
  with check (public.has_workspace_role(workspace_id, array['owner','admin']));
create policy field_maps_admin_all on public.field_maps for all
  using (public.has_workspace_role(workspace_id, array['owner','admin']))
  with check (public.has_workspace_role(workspace_id, array['owner','admin']));
create policy raw_records_admin_all on public.raw_lead_records for all
  using (public.has_workspace_role(workspace_id, array['owner','admin']))
  with check (public.has_workspace_role(workspace_id, array['owner','admin']));
create policy review_queue_admin_all on public.review_queue for all
  using (public.has_workspace_role(workspace_id, array['owner','admin']))
  with check (public.has_workspace_role(workspace_id, array['owner','admin']));
create policy suppression_admin_all on public.suppression_list for all
  using (public.has_workspace_role(workspace_id, array['owner','admin']))
  with check (public.has_workspace_role(workspace_id, array['owner','admin']));
create policy consumer_offsets_admin_all on public.consumer_offsets for all
  using (public.has_workspace_role(workspace_id, array['owner','admin']))
  with check (public.has_workspace_role(workspace_id, array['owner','admin']));

create policy lead_sources_role_select on public.lead_sources for select
  using (exists (select 1 from public.leads l where l.id = lead_id and l.workspace_id = lead_sources.workspace_id and public.can_access_lead(l.workspace_id, l.assigned_broker)));
create policy lead_change_log_role_select on public.lead_change_log for select
  using (exists (select 1 from public.leads l where l.id = lead_id and l.workspace_id = lead_change_log.workspace_id and public.can_access_lead(l.workspace_id, l.assigned_broker)));
create policy followups_role_select on public.followups for select
  using (exists (select 1 from public.leads l where l.id = lead_id and l.workspace_id = followups.workspace_id and public.can_access_lead(l.workspace_id, l.assigned_broker)));
create policy viewings_role_select on public.viewings for select
  using (exists (select 1 from public.leads l where l.id = lead_id and l.workspace_id = viewings.workspace_id and public.can_access_lead(l.workspace_id, l.assigned_broker)));
create policy viewings_broker_write on public.viewings for all
  using (exists (select 1 from public.workspace_members m where m.workspace_id = viewings.workspace_id and m.user_id = auth.uid() and m.status = 'active' and (m.role in ('owner','admin') or m.broker_id = viewings.broker_id)))
  with check (exists (select 1 from public.workspace_members m where m.workspace_id = viewings.workspace_id and m.user_id = auth.uid() and m.status = 'active' and (m.role in ('owner','admin') or m.broker_id = viewings.broker_id)));

commit;
