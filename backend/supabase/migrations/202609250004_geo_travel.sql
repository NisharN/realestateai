-- Landmarks + precomputed travel times (architecture §7). Shared reference data, not tenant rows.
create table if not exists public.landmarks (
  id text primary key,
  workspace_id text not null default 'shared',
  name_en text not null,
  name_ar text,
  lat double precision not null,
  lng double precision not null,
  kind text
);

insert into public.landmarks (id, name_en, name_ar, lat, lng, kind) values
  ('dxb', 'Dubai International Airport (DXB)', 'مطار دبي الدولي', 25.2532, 55.3657, 'airport'),
  ('dwc', 'Al Maktoum International (DWC)', 'مطار آل مكتوم الدولي', 24.8964, 55.1614, 'airport'),
  ('downtown', 'Downtown / Burj Khalifa', 'وسط المدينة / برج خليفة', 25.1972, 55.2744, 'district'),
  ('difc', 'DIFC', 'مركز دبي المالي العالمي', 25.211, 55.28, 'business'),
  ('marina', 'Dubai Marina', 'مرسى دبي', 25.0805, 55.1403, 'district'),
  ('dubai_mall', 'Dubai Mall', 'دبي مول', 25.1985, 55.2796, 'mall'),
  ('moe', 'Mall of the Emirates', 'مول الإمارات', 25.1181, 55.2004, 'mall'),
  ('jbr_beach', 'JBR Beach', 'شاطئ جي بي آر', 25.0783, 55.1336, 'beach'),
  ('expo_city', 'Expo City Dubai', 'مدينة إكسبو دبي', 24.961, 55.151, 'district'),
  ('internet_city', 'Dubai Internet City', 'مدينة دبي للإنترنت', 25.095, 55.159, 'business'),
  ('jafza', 'Jebel Ali Free Zone', 'المنطقة الحرة بجبل علي', 25.009, 55.068, 'business'),
  ('healthcare_city', 'Dubai Healthcare City', 'مدينة دبي الطبية', 25.23, 55.32, 'hospital')
on conflict (id) do update set name_en = excluded.name_en, name_ar = excluded.name_ar, lat = excluded.lat, lng = excluded.lng, kind = excluded.kind;

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

-- No insert/update/delete policies exist, so RLS already blocks client writes; revoke the
-- grants too so only the service role (batch job) can change published travel data.
revoke insert, update, delete on public.landmarks from anon, authenticated;
revoke insert, update, delete on public.travel_times from anon, authenticated;
