-- Landmarks + precomputed travel times (architecture §7). Shared reference data, not tenant rows.
create table if not exists public.landmarks (
  id text primary key,
  name_en text not null,
  name_ar text,
  lat double precision not null,
  lng double precision not null,
  kind text
);

create table if not exists public.travel_times (
  id uuid primary key default gen_random_uuid(),
  workspace_id text not null default 'shared',
  from_id text not null,
  to_id text not null references public.landmarks(id) on delete cascade,
  minutes integer not null,
  km double precision not null,
  method text not null check (method in ('osrm','straight_line')),
  computed_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz,
  unique (from_id, to_id)
);

-- Reference data readable by every authenticated user; writes only via service role (batch job).
alter table public.landmarks enable row level security;
alter table public.travel_times enable row level security;
create policy landmarks_read on public.landmarks for select using (true);
create policy travel_times_read on public.travel_times for select using (true);
