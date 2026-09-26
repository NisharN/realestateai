-- Per-connection incremental sync state (opaque cursor / updated_after watermark) for changed-since pulls.
alter table public.cowork_connections add column if not exists sync_state jsonb not null default '{}'::jsonb;
