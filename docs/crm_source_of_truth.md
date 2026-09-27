# Standalone CRM as source of truth

The agent platform does not own CRM data. The standalone UAE CRM
(`NisharN/realestate-crm`) is authoritative for leads, contact details, stages,
assignment, listings, viewings, follow-ups and deals. The platform pulls what it
needs, qualifies and scores it, and writes AI-derived fields back.

Adapter: `backend/app/modules/cowork/realestate_crm.py`, wired into the
`realestate_crm` provider in Operations → Connections.

## Ownership

| Data | Owner | Platform behaviour |
| --- | --- | --- |
| name / phone / e-mail / consent | CRM | never overwritten on merge (`CRM_OWNED`) |
| pipeline stage | CRM | copied onto the platform lead after every pull |
| requirements (purpose, budget, areas, timeline, payment) | CRM, enriched by the AI | filled when empty on either side |
| `ai_score`, `ai_band`, `ai_summary` | AI platform | PATCHed to the CRM on every score change |
| activities / timeline | CRM | AI appends via `POST /v1/leads/{id}/activities` |

## Inbound (CRM → platform)

* **Pull** — `GET /v1/leads?updated_after=…&limit=200`, walking `paging.next`
  (opaque cursor) for at most 10 pages per tick. The cursor and watermark live
  in `cowork_connections.sync_state`; a partial walk keeps the cursor and does
  not advance the watermark, so nothing is skipped.
* **Webhook** — the CRM signs the exact body with `X-Signature-256:
  sha256=<hmac>`; the platform verifies against the connection's webhook
  secret (paste the platform's secret into the CRM webhook form). Only
  `lead.created|updated|contacted` are ingested; `lead.deleted`, opted-out
  leads and events with `origin: ai_agent` (echoes of our own write-back) are
  ignored.
* Every landed record runs through the ingestion pipeline (dedupe on
  `external_id = CRM lead id`, then phone/e-mail) and is re-scored with Jev.

## Outbound (platform → CRM)

* `PATCH /v1/leads/{crm_lead_id}` with only the fields the CRM's strict
  `LeadWriteBack` accepts: `score`, `band`, `stage`, `assigned_broker`,
  `purpose`, `timeline`, `budget_*`, `area_preference`, `summary`.
* Driven by the `crm_writeback` outbox consumer on `lead.scored`,
  `lead.updated` (with changed fields), handoff and reassignment events; a
  re-ingest that changed nothing is not bounced back.
* Leads the platform created itself go through `POST /v1/leads` (idempotent on
  `source=ai_agent, external_id=<platform lead id>`, then phone/e-mail) and the
  returned CRM id is stored on `leads.crm_external_id`.

## Security

* `Authorization: Bearer crm_live_…` API key scoped to `leads:read`,
  `leads:write`, `listings:read`, `viewings:*`, `followups:write`.
* HTTPS only, public hosts only, DNS-pinned connections, redirects not
  followed; failures are reported without the key or credential-bearing URL.
