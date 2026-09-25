-- Conversation engine, normalized messages, handoffs, lead events, gazetteer.
begin;

create extension if not exists pg_trgm;

create table if not exists public.conversation_states (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  lead_id uuid not null,
  conversation_id uuid,
  stage text not null default 'greeting',
  language text not null default 'en' check (language in ('en','ar')),
  score integer not null default 0,
  band text not null default 'cold' check (band in ('hot','warm','cold')),
  turn integer not null default 0,
  version integer not null default 0,
  state jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (workspace_id, lead_id),
  foreign key (workspace_id, lead_id) references public.leads(workspace_id, id) on delete cascade
);

create table if not exists public.messages (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  lead_id uuid not null,
  conversation_id uuid,
  turn integer not null default 0,
  role text not null check (role in ('user','assistant','system','broker')),
  channel text not null default 'chat',
  text text not null,
  idempotency_key text,
  meta jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  foreign key (workspace_id, lead_id) references public.leads(workspace_id, id) on delete cascade
);
create index if not exists messages_lead_idx on public.messages (workspace_id, lead_id, created_at);
create unique index if not exists messages_idem_idx
  on public.messages (workspace_id, lead_id, role, idempotency_key)
  where idempotency_key is not null;

create table if not exists public.handoffs (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  lead_id uuid not null,
  broker_id uuid references public.brokers(id) on delete set null,
  broker_name text,
  status text not null default 'pending' check (status in ('pending','accepted','reassigned','escalated','unassigned','closed')),
  reason text,
  routing_reasons jsonb not null default '[]'::jsonb,
  tried_broker_ids jsonb not null default '[]'::jsonb,
  brief jsonb not null default '{}'::jsonb,
  score integer not null default 0,
  band text,
  language text,
  slot_text text,
  reassign_after timestamptz,
  accepted_at timestamptz,
  reassigned_count integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  foreign key (workspace_id, lead_id) references public.leads(workspace_id, id) on delete cascade
);
create index if not exists handoffs_pending_idx on public.handoffs (workspace_id, status, reassign_after);

create table if not exists public.lead_events (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  lead_id uuid not null,
  type text not null,
  payload jsonb not null default '{}'::jsonb,
  published_at timestamptz,
  created_at timestamptz not null default now(),
  foreign key (workspace_id, lead_id) references public.leads(workspace_id, id) on delete cascade
);
create index if not exists lead_events_outbox_idx on public.lead_events (published_at, created_at) where published_at is null;

create table if not exists public.communities (
  id text primary key,
  name_en text not null,
  name_ar text,
  lat double precision,
  lng double precision,
  tier text,
  created_at timestamptz not null default now()
);
create table if not exists public.community_aliases (
  alias text primary key,
  community_id text not null references public.communities(id) on delete cascade
);
create index if not exists community_aliases_trgm_idx on public.community_aliases using gin (alias gin_trgm_ops);

alter table public.conversation_states enable row level security;
alter table public.messages enable row level security;
alter table public.handoffs enable row level security;
alter table public.lead_events enable row level security;

create policy conversation_states_role_select on public.conversation_states for select using (exists (select 1 from public.leads l where l.id = lead_id and l.workspace_id = conversation_states.workspace_id and public.can_access_lead(l.workspace_id, l.assigned_broker)));
create policy messages_role_select on public.messages for select using (exists (select 1 from public.leads l where l.id = lead_id and l.workspace_id = messages.workspace_id and public.can_access_lead(l.workspace_id, l.assigned_broker)));
create policy handoffs_role_select on public.handoffs for select using (exists (select 1 from public.leads l where l.id = lead_id and l.workspace_id = handoffs.workspace_id and public.can_access_lead(l.workspace_id, l.assigned_broker)));
create policy handoffs_broker_accept on public.handoffs for update
  using (exists (select 1 from public.workspace_members m where m.workspace_id = handoffs.workspace_id and m.user_id = auth.uid() and m.status = 'active' and (m.role in ('owner','admin') or m.broker_id = handoffs.broker_id)))
  with check (exists (select 1 from public.workspace_members m where m.workspace_id = handoffs.workspace_id and m.user_id = auth.uid() and m.status = 'active' and (m.role in ('owner','admin') or m.broker_id = handoffs.broker_id)));
create policy lead_events_admin_select on public.lead_events for select using (public.has_workspace_role(workspace_id, array['owner','admin']));

commit;
