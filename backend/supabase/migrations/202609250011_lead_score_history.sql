-- Continuous lead re-scoring: every score move (pull, reply, viewing, silence, opt-out)
-- is appended here so brokers and the Copilot can explain why a lead rose or fell.

create table if not exists public.lead_score_history (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  lead_id uuid not null references public.leads(id) on delete cascade,
  trigger text not null,                 -- e.g. ingestion:gmail, viewing:confirmed, routine:<name>
  provider text,                         -- jev | rules
  previous_score integer,
  score integer not null,
  previous_band text,
  band text not null,
  delta integer not null default 0,
  behaviour_delta integer not null default 0,
  reasons jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists lead_score_history_lead_idx on public.lead_score_history (workspace_id, lead_id, created_at desc);
create index if not exists lead_score_history_ws_created_idx on public.lead_score_history (workspace_id, created_at desc);

alter table public.leads add column if not exists lost_reason text;
alter table public.leads add column if not exists scored_at timestamptz;
