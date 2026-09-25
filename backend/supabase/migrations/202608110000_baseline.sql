-- v1 baseline: the tables that existed before the tenant foundation migration.
-- Idempotent (create ... if not exists) so it is a no-op on databases that
-- were provisioned by hand, and lets a fresh project apply the full chain.
begin;

create extension if not exists "pgcrypto";

create table if not exists public.workspaces (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  status text not null default 'draft',
  settings jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.brokers (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  email text,
  phone text,
  specialization jsonb not null default '[]'::jsonb,
  max_leads integer not null default 10,
  active_leads integer not null default 0,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.properties (
  id uuid primary key default gen_random_uuid(),
  title text,
  description text,
  property_type text,
  area text,
  developer text,
  price numeric(15,2),
  price_per_sqft numeric(12,2),
  size_sqft numeric(12,2),
  bedrooms integer,
  bathrooms integer,
  amenities jsonb not null default '[]'::jsonb,
  images jsonb not null default '[]'::jsonb,
  map_lat double precision,
  map_lng double precision,
  source text,
  source_id text,
  source_url text,
  is_active boolean not null default true,
  scraped_at timestamptz,
  last_refreshed_at timestamptz,
  refresh_count integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.leads (
  id uuid primary key default gen_random_uuid(),
  first_name text,
  last_name text,
  email text,
  phone text,
  source text,
  status text not null default 'new',
  intent_score integer not null default 0,
  property_type text,
  area_preference text,
  timeline text,
  preferred_language text,
  initial_message text,
  conversation_history jsonb not null default '[]'::jsonb,
  assigned_broker uuid references public.brokers(id),
  last_contact_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.conversations (
  id uuid primary key default gen_random_uuid(),
  lead_id uuid not null references public.leads(id) on delete cascade,
  channel text,
  messages jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.activities (
  id uuid primary key default gen_random_uuid(),
  lead_id uuid not null references public.leads(id) on delete cascade,
  activity_type text,
  description text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.lead_property_matches (
  id uuid primary key default gen_random_uuid(),
  lead_id uuid not null references public.leads(id) on delete cascade,
  property_id uuid not null references public.properties(id) on delete cascade,
  score numeric(6,2),
  reasons jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

commit;
