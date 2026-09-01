# POC Scope — Broker Configuration Proof of Concept

Date: August 9, 2026

## The pain this proves out

Two things stand between this project and a sellable product: the AI pipeline has to actually work end to end (not echo canned lines), and a broker/agency has to be able to configure their own instance — team, listings, channel — without you doing it by hand over a call every time. This POC proves both are solvable without a full production rebuild.

## In scope

**Fixes (make the fake-working features real):**
- Voice conversations route through the real LangGraph agent pipeline instead of a canned echo.
- Property matching scores leads against actually-ingested inventory (CSV/CRM/feed/RapidAPI/Property Finder) instead of 3 hardcoded demo units, with a clearly-labeled demo fallback when a workspace has no listings yet.

**New: workspace configuration ("light FDE" workflow builder)**
- A `Workspace` concept: one broker/agency's team roster, enabled data sources, and channel settings.
- A guided in-product wizard (`/configure`) to set this up: Team & Roles → Data Pipeline → Channels → Review & Launch.
- Backend endpoints to create/read/update a workspace and to "test" a data source connection.

**Cuts (per the market/product analysis)**
- Bayut/Dubizzle stealth scraping demoted to "deferred" — not removed, but no longer the recommended default path (your own ops docs confirm both are anti-bot-blocked).
- Unused dependencies trimmed from `requirements.txt` (Celery, Redis, APScheduler — nothing in the codebase schedules jobs with them).
- Duplicate SQL schema file flagged for manual removal (not auto-deleted — see note at the end).

**In-app documentation**
- A `/docs` page inside the product itself explaining what's real vs. simulated in this POC, the architecture, and the path to production.

## Explicitly out of scope (this is a POC, not the product)

- Real multi-tenant data isolation. Workspace *configuration* is real and saved; leads/properties remain a single shared pool underneath. Production needs tenant-scoped queries everywhere.
- Real WhatsApp Business API sending. The channel step collects a WhatsApp number and stores it — no message actually sends.
- Authentication/login and billing/subscription enforcement.
- Fixing Bayut/Dubizzle scraping itself (deferred, not solved).
- Automated tests and CI (flagged as a gap in the earlier analysis; still a gap here — I have no way to execute `npm`/`pytest` in this environment to verify, see the review notes).

## A note on verification

I don't have a working code-execution sandbox in this session (Node/npm and Python are unavailable here), so these changes are verified by careful manual code review — reading every changed file end to end for correctness — not by running `npm run build`, `pytest`, or opening a browser. Before you treat this as working code, run it locally (`npm run dev` / `uvicorn app.main:app --reload`) and click through it once. I'll flag anything I'm not fully confident about in the final review notes.

## Manual cleanup needed (not done automatically)

`backend/database_schema.sql` duplicates `backend/01_database_schema.sql` and now also lacks the new `workspaces` table added to the numbered file. Delete `database_schema.sql` once you've confirmed `01_database_schema.sql` is the one your Supabase project actually uses.
