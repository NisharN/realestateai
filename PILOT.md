# PILOT.md — Validated Build Spec

Authoritative scope for the rebuild. Supersedes PROJECT.md where they conflict. Derived from three advisory rounds (Dubai broker, technical consultant, product manager) documented in `docs/feature_audit.md`, `docs/pilot_feature_compromise.md`, and `docs/workflow_builder_validation.md`.

## Operating model

Single-tenant: one deployment per brokerage, configured at deploy time by the founder acting as forward-deployed engineer. Role-based access (owner / admin / agent) applies **within** that one workspace. No cross-tenant isolation problem to get wrong, no RLS requirement, no `X-Workspace-ID` switching.

Data strategy: **mock by default, real opt-in per source.** Every external source sits behind an interface with a `DATA_MODE` switch. The demo runs fully offline on seeded data with zero API keys; individual sources flip to live when credentials exist and approvals clear.

## Primary features (pilot, 4-6 weeks)

1. **Lead ingestion — CSV/CRM import, manual and referral entry.** Zero external approval required, ships immediately. Broker-corrected priority: this is the #2 source in practice, not #5 — most agent history currently lives in spreadsheets.
2. **Structured budget/currency extraction.** Forces explicit currency (AED/USD) and period (total vs. per-year) with a clarifying follow-up on ambiguity. Ships *before* WhatsApp send — delivering a misparsed budget faster only destroys trust faster.
3. **Lead scoring and qualification** against real inventory (already working, retained).
4. **WhatsApp send-side.** Real Meta Cloud API in live mode; an outbox table in mock mode so the demo shows exactly what would have been sent. Replaces the current fails-closed stub.
5. **Scheduler (Celery) + worker/beat services.** Completes `run_ingestion_schedule` and adds the missing container services — this is the direct fix for the reported schedule error.
6. **Reminders engine** — hardcoded workflow templates, no canvas: new-lead follow-up, viewing reminders, mandate renewal reminders, expired-listing nudges. Mandate renewals and market reports are the marketed differentiators; viewing/expiry reminders ride along unmarketed but still ship, because the broker needs them operationally either way.
7. **Listing refresh copy generator.** Staleness tracking as a backend trigger; generates a fresh description variant the broker copies and reposts herself. Solves the real pain (the blank page), not the fake one (the reminder). No automated portal posting — ever.
8. **DLD transaction map.** Leaflet/OpenStreetMap tiles plus cached Dubai Land Department open data for comps and price-objection conversations. Demo-ready early — it is the most screenshot-able asset in the product.
9. **Lead inbox + dashboard on real data.** Fixes the current inconsistency where live stat cards sit above a hardcoded mock leads table.
10. **Ejari/Form F checklist.** Required-documents and sequencing aid with **zero data pre-fill** — organizing, not generating. Protects the broker's RERA license without creating liability surface.

## Explicitly cut

- **Visual workflow builder / canvas.** Rebuilding n8n by hand, contradicts the FDE model (customers pay precisely so they don't configure), and the broker confirmed no agent will open a node editor between viewings. Revisit only at 5+ customers with genuinely unanticipated overlapping needs — and then as an internal admin tool, not a customer-facing canvas.
- **n8n service and `n8n-workflows/`.** Redundant with the Celery scheduler.
- **Automated portal re-posting** to Bayut / Property Finder / Dubizzle. Same ToS exposure as scraping; a banned customer account is an existential trust problem.
- **Purchased lead databases.** Near-worthless in this market per the broker, with reputational risk.
- **Meta / Google Ads connectors** in the near term — multi-week approval processes with no pilot value while waiting.
- **Ejari/Form F pre-fill, e-signature, government API submission.**
- **Dead config**: unused `SENTRY_DSN`, unused `OPENAI_API_KEY`, stale `MAPBOX_ACCESS_TOKEN` references, duplicate SQL schema file, contradictory requirements.txt comment.

## Deferred past pilot

- **Real-time voice (OpenAI Realtime API).** All three advisors agreed. An English-only fence fails because Emirati clients code-switch mid-sentence, and building reliable detection is its own R&D project. Revisit on post-pilot demand signal.
- **Property Finder / Bayut authorized enquiry import** — a partnership/BD conversation before it is an engineering task.
- **WhatsApp inbound, website chat/forms** as founder-configured modules.
- **Market report generation** off DLD data (scope fence: a templated PDF/WhatsApp summary, not a BI product).
- **Scrapers** — retained in the codebase and gated off by default at the user's request, since they may still work; not a pilot dependency and not the recommended path.

## Standing requirements

- **Voice human-approval gate.** Whenever voice automation ships, a human must approve every first outbound call, with a visible kill switch. A workflow auto-dialing on a scoring rule risks wrong numbers, already-closed leads, and do-not-call violations with nobody watching.
- **Portal enquiries enter only through authorized channels** — the brokerage's own account, CRM export, email integration, webhook, or approved API. Never harvested from another broker's account.
- **Start Meta Business Verification and WhatsApp Cloud API approval paperwork immediately, in parallel** with the build. The calendar is the bottleneck, not the code — but nothing in the pilot may block on it.

## Running it

Demo mode needs no keys, no Supabase project, and no login.

```bash
# Backend
cd backend
cp .env.example .env
pip install -r requirements.txt
python seed_demo.py            # shows what the demo contains
uvicorn app.main:app --reload

# Frontend
cd frontend
cp .env.example .env.local
npm install && npm run dev
```

Or the whole stack, including the Celery worker and beat services that were
previously missing:

```bash
docker compose up --build
```

Then: `/dashboard` for the pipeline, `/market` for the comps map, `/automations`
for the workflow templates and message outbox, `/docs` for what's real vs seeded.

`GET /health` reports the effective mode of every data source, so it's always
unambiguous whether an instance is a demo or a live customer deployment.

### Verification status

- Backend: 63 tests passing (`pytest`), including the budget-extraction and
  workflow-template suites added with this build.
- Frontend: `tsc --noEmit` clean.
- End-to-end smoke: 16/16 checks — dashboard totals match the lead list,
  workflow preview count equals execution count, outbox records without
  delivering, listing refresh never auto-posts, voice requests are refused
  while outbound is disabled.
- `npm run vitest` could not execute in the build sandbox (missing native
  rolldown binary for the platform); it should run normally on your machine.

## Compliance lead times (why the order looks like this)

| Connector | Approval needed | Realistic wait |
|---|---|---|
| CSV / Excel / CRM / manual entry | None | Ship today |
| Website forms | None (you own both ends) | Ship today |
| Google Sheets | Narrow-scope OAuth verification | 1-2 weeks |
| WhatsApp Business Cloud API | Meta Business Verification | 2-4+ weeks |
| Meta / Instagram Lead Ads | App Review (`leads_retrieval`) + Business Verification | 2-4 weeks |
| Google Ads API | Developer token, Basic access review | 1-3 weeks |
| Gmail (read/send) | Verification + CASA security assessment | 4-8 weeks, paid |
| Property Finder / Bayut | Partnership / approved API access | BD conversation, unbounded |
