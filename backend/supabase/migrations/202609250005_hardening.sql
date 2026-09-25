-- Phase 7 hardening: follow-up retry bookkeeping.
alter table public.followups add column if not exists attempts integer not null default 0;
