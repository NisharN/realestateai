-- Tenant foundation for the invite-only v2 pilot.
begin;

create extension if not exists "pgcrypto";

alter table public.workspaces
  add column if not exists lifecycle_status text not null default 'draft'
    check (lifecycle_status in ('draft','active','grace','read_only','suspended')),
  add column if not exists grace_ends_at timestamptz,
  add column if not exists stripe_customer_id text,
  add column if not exists stripe_subscription_id text,
  add column if not exists is_demo boolean not null default false;

insert into public.workspaces (id, name, status, lifecycle_status, is_demo)
values ('00000000-0000-0000-0000-000000000001', 'Legacy pilot workspace', 'draft', 'draft', true)
on conflict (id) do nothing;

alter table public.brokers add column if not exists workspace_id uuid references public.workspaces(id);
alter table public.properties add column if not exists workspace_id uuid references public.workspaces(id);
alter table public.leads add column if not exists workspace_id uuid references public.workspaces(id);
alter table public.conversations add column if not exists workspace_id uuid references public.workspaces(id);
alter table public.activities add column if not exists workspace_id uuid references public.workspaces(id);
alter table public.lead_property_matches add column if not exists workspace_id uuid references public.workspaces(id);

update public.brokers set workspace_id = '00000000-0000-0000-0000-000000000001' where workspace_id is null;
update public.properties set workspace_id = '00000000-0000-0000-0000-000000000001' where workspace_id is null;
update public.leads set workspace_id = '00000000-0000-0000-0000-000000000001' where workspace_id is null;
update public.conversations c set workspace_id = l.workspace_id from public.leads l where c.lead_id = l.id and c.workspace_id is null;
update public.activities a set workspace_id = l.workspace_id from public.leads l where a.lead_id = l.id and a.workspace_id is null;
update public.lead_property_matches m set workspace_id = l.workspace_id from public.leads l where m.lead_id = l.id and m.workspace_id is null;

alter table public.brokers alter column workspace_id set not null;
alter table public.properties alter column workspace_id set not null;
alter table public.leads alter column workspace_id set not null;
alter table public.conversations alter column workspace_id set not null;
alter table public.activities alter column workspace_id set not null;
alter table public.lead_property_matches alter column workspace_id set not null;

alter table public.brokers drop constraint if exists brokers_email_key;
alter table public.brokers add constraint brokers_workspace_id_id_key unique (workspace_id, id);
alter table public.properties add constraint properties_workspace_id_id_key unique (workspace_id, id);
alter table public.leads add constraint leads_workspace_id_id_key unique (workspace_id, id);

alter table public.leads drop constraint if exists leads_assigned_broker_fkey;
alter table public.leads add constraint leads_workspace_broker_fkey
  foreign key (workspace_id, assigned_broker) references public.brokers(workspace_id, id);
alter table public.conversations drop constraint if exists conversations_lead_id_fkey;
alter table public.conversations add constraint conversations_workspace_lead_fkey
  foreign key (workspace_id, lead_id) references public.leads(workspace_id, id) on delete cascade;
alter table public.activities drop constraint if exists activities_lead_id_fkey;
alter table public.activities add constraint activities_workspace_lead_fkey
  foreign key (workspace_id, lead_id) references public.leads(workspace_id, id) on delete cascade;
alter table public.lead_property_matches drop constraint if exists lead_property_matches_lead_id_fkey;
alter table public.lead_property_matches drop constraint if exists lead_property_matches_property_id_fkey;
alter table public.lead_property_matches add constraint matches_workspace_lead_fkey
  foreign key (workspace_id, lead_id) references public.leads(workspace_id, id) on delete cascade;
alter table public.lead_property_matches add constraint matches_workspace_property_fkey
  foreign key (workspace_id, property_id) references public.properties(workspace_id, id) on delete cascade;

create unique index if not exists brokers_workspace_email_uidx on public.brokers(workspace_id, lower(email));
create unique index if not exists properties_workspace_source_id_uidx
  on public.properties(workspace_id, source, source_id) where source_id is not null;
create unique index if not exists properties_workspace_source_url_uidx
  on public.properties(workspace_id, source, source_url) where source_url is not null;
create index if not exists leads_workspace_status_idx on public.leads(workspace_id, status, created_at desc);
create index if not exists leads_workspace_broker_idx on public.leads(workspace_id, assigned_broker);

create table if not exists public.workspace_members (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  broker_id uuid,
  role text not null check (role in ('owner','admin','agent')),
  status text not null default 'active' check (status in ('invited','active','disabled')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (workspace_id, user_id),
  foreign key (workspace_id, broker_id) references public.brokers(workspace_id, id)
);

create table if not exists public.workspace_invitations (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  email text not null,
  role text not null check (role in ('owner','admin','agent')),
  token_hash text not null unique,
  invited_by uuid not null references auth.users(id),
  expires_at timestamptz not null,
  accepted_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists public.channel_connections (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  provider text not null check (provider in ('whatsapp','web_widget')),
  provider_account_id text,
  public_key_hash text,
  encrypted_credentials text,
  status text not null default 'pending' check (status in ('pending','active','error','disabled')),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (provider, provider_account_id)
);

create table if not exists public.webhook_events (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid references public.workspaces(id) on delete cascade,
  provider text not null,
  provider_event_id text not null,
  event_type text not null,
  status text not null default 'received',
  received_at timestamptz not null default now(),
  processed_at timestamptz,
  error_code text,
  unique (provider, provider_event_id)
);

create table if not exists public.ingestion_schedules (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  source text not null,
  cron_expression text not null,
  config jsonb not null default '{}'::jsonb,
  enabled boolean not null default true,
  consecutive_failures integer not null default 0,
  next_run_at timestamptz,
  last_success_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.job_runs (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  schedule_id uuid references public.ingestion_schedules(id) on delete set null,
  idempotency_key text not null,
  status text not null check (status in ('queued','running','succeeded','failed')),
  attempts integer not null default 0,
  started_at timestamptz,
  finished_at timestamptz,
  error_code text,
  summary jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (workspace_id, idempotency_key)
);

create table if not exists public.voice_sessions (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  lead_id uuid not null,
  provider text not null,
  language text not null check (language in ('en','ar')),
  status text not null,
  transcript jsonb not null default '[]'::jsonb,
  tool_events jsonb not null default '[]'::jsonb,
  latency_ms integer,
  fallback_used boolean not null default false,
  started_at timestamptz not null default now(),
  ended_at timestamptz,
  foreign key (workspace_id, lead_id) references public.leads(workspace_id, id) on delete cascade
);

create or replace function public.is_workspace_member(target_workspace uuid)
returns boolean language sql stable security definer set search_path = public
as $$
  select exists (
    select 1 from public.workspace_members
    where workspace_id = target_workspace and user_id = auth.uid() and status = 'active'
  );
$$;

create or replace function public.has_workspace_role(target_workspace uuid, allowed_roles text[])
returns boolean language sql stable security definer set search_path = public
as $$
  select exists (
    select 1 from public.workspace_members
    where workspace_id = target_workspace and user_id = auth.uid()
      and status = 'active' and role = any(allowed_roles)
  );
$$;

create or replace function public.can_access_lead(target_workspace uuid, target_broker uuid)
returns boolean language sql stable security definer set search_path = public
as $$
  select exists (
    select 1 from public.workspace_members
    where workspace_id = target_workspace and user_id = auth.uid() and status = 'active'
      and (role in ('owner','admin') or (role = 'agent' and broker_id = target_broker))
  );
$$;

alter table public.workspaces enable row level security;
alter table public.workspace_members enable row level security;
alter table public.workspace_invitations enable row level security;
alter table public.brokers enable row level security;
alter table public.properties enable row level security;
alter table public.leads enable row level security;
alter table public.conversations enable row level security;
alter table public.activities enable row level security;
alter table public.lead_property_matches enable row level security;
alter table public.channel_connections enable row level security;
alter table public.ingestion_schedules enable row level security;
alter table public.job_runs enable row level security;
alter table public.voice_sessions enable row level security;

create policy workspaces_member_select on public.workspaces for select using (public.is_workspace_member(id));
create or replace function public.protect_workspace_system_fields()
returns trigger language plpgsql security definer set search_path = public
as $$
begin
  if auth.role() <> 'service_role' and (
    new.lifecycle_status is distinct from old.lifecycle_status or
    new.stripe_customer_id is distinct from old.stripe_customer_id or
    new.stripe_subscription_id is distinct from old.stripe_subscription_id or
    new.grace_ends_at is distinct from old.grace_ends_at or
    new.is_demo is distinct from old.is_demo
  ) then
    raise exception 'workspace system fields require service role' using errcode = '42501';
  end if;
  return new;
end;
$$;

drop trigger if exists protect_workspace_system_fields on public.workspaces;
create trigger protect_workspace_system_fields
before update on public.workspaces
for each row execute function public.protect_workspace_system_fields();

create policy workspaces_admin_update on public.workspaces for update
  using (public.has_workspace_role(id, array['owner','admin']))
  with check (public.has_workspace_role(id, array['owner','admin']));
create policy members_scoped_select on public.workspace_members for select using (
  user_id = auth.uid() or public.has_workspace_role(workspace_id, array['owner','admin'])
);
create policy members_owner_write on public.workspace_members for all
  using (public.has_workspace_role(workspace_id, array['owner']))
  with check (public.has_workspace_role(workspace_id, array['owner']));
create policy members_admin_insert on public.workspace_members for insert
  with check (role <> 'owner' and public.has_workspace_role(workspace_id, array['owner','admin']));
create policy members_admin_update on public.workspace_members for update
  using (role <> 'owner' and public.has_workspace_role(workspace_id, array['owner','admin']))
  with check (role <> 'owner' and public.has_workspace_role(workspace_id, array['owner','admin']));
create policy members_admin_delete on public.workspace_members for delete
  using (role <> 'owner' and public.has_workspace_role(workspace_id, array['owner','admin']));
create policy invitations_admin_all on public.workspace_invitations for all using (public.has_workspace_role(workspace_id, array['owner','admin'])) with check (public.has_workspace_role(workspace_id, array['owner','admin']));
create policy brokers_member_select on public.brokers for select using (public.is_workspace_member(workspace_id));
create policy brokers_admin_write on public.brokers for all using (public.has_workspace_role(workspace_id, array['owner','admin'])) with check (public.has_workspace_role(workspace_id, array['owner','admin']));
create policy properties_member_select on public.properties for select using (public.is_workspace_member(workspace_id));
create policy properties_admin_write on public.properties for all using (public.has_workspace_role(workspace_id, array['owner','admin'])) with check (public.has_workspace_role(workspace_id, array['owner','admin']));
create policy leads_role_select on public.leads for select using (public.can_access_lead(workspace_id, assigned_broker));
create policy leads_admin_write on public.leads for all using (public.has_workspace_role(workspace_id, array['owner','admin'])) with check (public.has_workspace_role(workspace_id, array['owner','admin']));
create policy conversations_role_select on public.conversations for select using (exists (select 1 from public.leads l where l.id = lead_id and l.workspace_id = conversations.workspace_id and public.can_access_lead(l.workspace_id, l.assigned_broker)));
create policy conversations_role_write on public.conversations for all using (exists (select 1 from public.leads l where l.id = lead_id and l.workspace_id = conversations.workspace_id and public.can_access_lead(l.workspace_id, l.assigned_broker))) with check (exists (select 1 from public.leads l where l.id = lead_id and l.workspace_id = conversations.workspace_id and public.can_access_lead(l.workspace_id, l.assigned_broker)));
create policy activities_role_select on public.activities for select using (exists (select 1 from public.leads l where l.id = lead_id and l.workspace_id = activities.workspace_id and public.can_access_lead(l.workspace_id, l.assigned_broker)));
create policy matches_role_select on public.lead_property_matches for select using (exists (select 1 from public.leads l where l.id = lead_id and l.workspace_id = lead_property_matches.workspace_id and public.can_access_lead(l.workspace_id, l.assigned_broker)));
create policy channels_admin_all on public.channel_connections for all using (public.has_workspace_role(workspace_id, array['owner','admin'])) with check (public.has_workspace_role(workspace_id, array['owner','admin']));
create policy schedules_admin_all on public.ingestion_schedules for all using (public.has_workspace_role(workspace_id, array['owner','admin'])) with check (public.has_workspace_role(workspace_id, array['owner','admin']));
create policy jobs_admin_select on public.job_runs for select using (public.has_workspace_role(workspace_id, array['owner','admin']));
create policy voice_role_select on public.voice_sessions for select using (exists (select 1 from public.leads l where l.id = lead_id and l.workspace_id = voice_sessions.workspace_id and public.can_access_lead(l.workspace_id, l.assigned_broker)));

commit;
