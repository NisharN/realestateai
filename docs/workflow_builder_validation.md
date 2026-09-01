# Validation: Visual Workflow Builder / Multi-Connector Lead System

All three advisors (technical consultant, PM, broker) converged independently on the same verdict: reject the visual workflow-builder as proposed, ship a hardcoded/templated version instead. This is a rare case of unanimous agreement without negotiation — noted because it's a stronger signal than the earlier rounds that needed compromise.

## The core problem with the proposal

The consultant pointed out the proposal is functionally a from-scratch rebuild of n8n — the exact tool that was deleted from this codebase earlier in this engagement for being redundant overhead next to the Celery scheduler. Building a canvas, trigger/connector/action taxonomy, and execution engine in-house is *more* work than running n8n, not less, and the founder would own every bug in perpetuity with none of n8n's years of connector maintenance behind it.

The PM identified a direct contradiction with the business model: the FDE (forward-deployed engineer) approach exists specifically because brokers pay a premium to NOT configure anything themselves. A self-serve drag-and-drop builder is a primitive for a world with hundreds of self-configuring customers — the opposite of the model being sold. Her diagnostic question: "who clicks 'add trigger' — you, or the agent? If he can't answer cleanly, the feature isn't scoped yet."

The broker confirmed from the user side: she built one Zapier flow in 2021 for lead routing, it broke silently for three weeks, and none of her agents will open a node editor between viewings. "If your product needs a canvas to feel powerful, that's a tell it's built for the demo, not for my Thursday afternoon."

## Connector reality check (technical)

Four of the eight requested connectors are multi-week compliance processes, not engineering tasks:

- CRM (own), CSV/Excel upload, website forms, manual entry — zero approval, buildable immediately.
- Google Sheets — narrow-scope OAuth verification, roughly 1-2 weeks.
- Gmail (read/send) — Google CASA security assessment on top of verification, realistically 4-8 weeks and not cheap.
- WhatsApp Business Cloud API — Meta Business Verification, 2-4+ weeks.
- Meta/Instagram Lead Ads — Meta App Review (`leads_retrieval`) plus Business Verification, 2-4 weeks, can bundle with WhatsApp under one Business Manager.
- Google Ads API — developer token, Basic access review 1-3 weeks, Standard access more scrutiny.

Recommendation: start WhatsApp and Meta Business Verification paperwork immediately in parallel, since the clock — not the code — is the bottleneck. Do not gate pilot launch on any of it.

## Lead-source priority, corrected by the broker

The proposed order (Property Finder/Bayut, WhatsApp, Meta/Instagram Ads, website forms, CSV/CRM, referrals, Google Ads, developer referrals) is value-ranked but not effort- or reality-ranked. The broker's real-volume correction: Property Finder/Bayut first by a mile, WhatsApp second (mostly downstream of the same portal leads plus referrals), referrals/repeat clients third (often the best conversion even if not the biggest count), direct owner relationships fourth. CSV/CRM import should move to priority two, not five — "half my agents' history lives in spreadsheets right now." She flagged Google Search ads as low priority (expensive, often other agencies bidding on the brokerage's own listing names), purchased lead databases as near-worthless and a reputational risk not worth building at all, developer-provided leads as real but usually locked in a developer's own CRM with exclusivity strings — build late — and lead-sharing between brokers as informal (WhatsApp and a phone call) rather than something an integration solves.

## New finding: automated voice needs a hard gate

The broker's original voice concerns (tone, cultural fit, Arabic dialect handling) get worse once a workflow can trigger an outbound call automatically with no human in the loop. Her addition: a workflow firing off a call based on a scoring rule risks dialing a wrong number, a lead another agent already closed, or someone who said don't call — with nobody watching it happen. Requirement: a mandatory human-approval step before any first outbound call, no exceptions, plus a visible kill switch.

## Consolidated recommendation

**Reject:** the canvas/builder UI itself, self-serve workflow creation for brokers/agents, Meta/Google Ads connectors in the near term, purchased lead databases.

**Pilot scope (unchanged 4-6 week window):** CSV/CRM import + manual/referral entry + lead scoring + one hardcoded workflow template (new lead in → score → auto WhatsApp follow-up → escalate to human if hot), no builder, no node editor. Start WhatsApp and Meta Business Verification paperwork in parallel now — as compliance work, not a pilot dependency.

**Phase 2 (post-pilot, proven willingness to pay):** Property Finder/Bayut authorized enquiry import, WhatsApp inbound, website forms — all founder-configured modules, still no self-serve builder.

**Phase 3 (5+ customers with genuinely overlapping, unanticipated needs):** revisit a real builder, and even then scope it as an internal admin tool for the founder configuring customers faster, not a customer-facing canvas.

**Standing requirement whenever voice automation ships:** mandatory human approval before first outbound call, visible kill switch, no exceptions.
