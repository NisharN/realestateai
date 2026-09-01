# Dubai Real Estate AI — Project Plan (POC → Full Product)

**Status:** POC complete (see `docs/poc_scope.md`). This document plans the next version: a real, end-to-end product with live data sources, a real voice agent, a rebuilt frontend, and multi-tenant broker configuration.

**How to use this file:** feed it to whatever coding agent/harness you're using (Claude Code, Cursor, Codex CLI, OpenClaw, etc.) as the top-level brief. It's written to be harness-agnostic — the skill packs referenced below install to multiple harnesses, not just one.

---

## 0. What this document is not

This is a plan, not a backlog of code to paste in blind. Every phase below should start with the engineering loop in Section 4 — think and plan before building — even though the destination is already mapped out here.

---

## 1. Where we are (POC recap)

Full detail in `docs/poc_scope.md` and `docs/dubai-real-estate-ai-product-analysis.md`. Short version:

- **Real:** LangGraph agent pipeline (scoring → qualifier → research → conversation → handoff/nurture), text chat, voice chat (now routed through the same pipeline, fixed from a canned echo), property matching against actually-ingested inventory (fixed from 3 hardcoded demo units), multi-source property ingestion (CSV/CRM/approved feed/RapidAPI/Property Finder), a `/configure` workspace wizard, an in-app `/docs` page.
- **Deferred:** Bayut/Dubizzle live scraping (anti-bot protected — gated behind a feature flag, off by default).
- **Simulated / not yet real:** multi-tenant data isolation (workspace config is real; leads/properties are still one shared pool), WhatsApp sending, dashboard data, auth, billing.

This plan closes those gaps in order of what actually blocks a paying customer.

---

## 2. Where we're going (v2 vision)

A subscription product that a solo agent or small brokerage in Dubai can configure themselves in under a day (self-serve tier), or that you configure for a mid-size brokerage in a single onboarding session (light-FDE tier — see the earlier market analysis for why this beats the Sierra/Decagon enterprise-FDE price point for this market). Concretely, v2 means:

1. Every workspace has its own leads, properties, brokers, and conversations — real multi-tenancy, not shared state.
2. Leads reach the product through a real, bidirectional WhatsApp integration, not just a web widget.
3. Voice conversations run on a real speech-to-speech voice agent, not a transcribe→text-agent→synthesize relay.
4. Property inventory is kept current from real, licensed/legal sources — CSV/CRM/feed/RapidAPI as the backbone, with Bayut/Dubizzle re-enabled only if a legitimate data partnership or licensed API replaces the deferred scraping path.
5. The frontend is rebuilt to a standard worth putting in front of a paying customer or investor, not a portfolio-project chat UI.
6. Basic auth and billing exist so a workspace maps to an actual paying account.

---

## 3. Target architecture

```
                          ┌───────────────────────────────────────────┐
                          │              LEAD SOURCES                  │
                          │  Web widget · WhatsApp · Voice · CSV import │
                          └───────────────────┬─────────────────────────┘
                                              │  (tagged with workspace_id)
                                              ▼
                          ┌───────────────────────────────────────────┐
                          │        WORKSPACE-SCOPED DATA LAYER          │
                          │  leads · properties · brokers · convos      │
                          │  (Postgres/Supabase, RLS by workspace_id)   │
                          └───────────────────┬─────────────────────────┘
                                              │
                                              ▼
                          ┌───────────────────────────────────────────┐
                          │       LANGGRAPH AGENT PIPELINE              │
                          │  Scoring → Qualifier → Research → Conv.     │
                          │  → Handoff / Nurture                        │
                          │  (property matching reads workspace's own   │
                          │   inventory only)                           │
                          └───────────────────┬─────────────────────────┘
                                              │
                    ┌─────────────────────────┼─────────────────────────┐
                    ▼                         ▼                         ▼
          ┌──────────────────┐    ┌───────────────────────┐  ┌──────────────────┐
          │  VOICE AGENT       │    │  WHATSAPP INTEGRATION  │  │  BROKER HANDOFF   │
          │  (speech-to-speech,│    │  (send + receive,      │  │  (real-time       │
          │  see Section 8)    │    │  per-workspace number) │  │  notification)    │
          └──────────────────┘    └───────────────────────┘  └──────────────────┘
                                              │
                                              ▼
                          ┌───────────────────────────────────────────┐
                          │        PROPERTY INGESTION PIPELINE          │
                          │  CSV · CRM export · approved feed · RapidAPI│
                          │  · Property Finder (live) — per workspace   │
                          └───────────────────────────────────────────┘

                          ┌───────────────────────────────────────────┐
                          │            FRONTEND (rebuilt)               │
                          │  Chat · Dashboard (live data) · Configure   │
                          │  · Docs · Auth · Billing                    │
                          └───────────────────────────────────────────┘
```

---

## 4. Engineering methodology — gstack as the team

[gstack](https://github.com/garrytan/gstack) isn't a tech stack — it's a process: **Think → Plan → Build → Review → Test → Ship → Reflect**, implemented as slash-command skills that hand off to each other. Use it as the engineering-team structure for every phase below, supplemented with three other real, independently-maintained skill packs for the parts gstack doesn't specialize in: planning rigor, frontend taste, and web quality.

### 4.1 Skill-to-role mapping

| Role in the loop | Skill pack | What it actually does |
|---|---|---|
| **Planning / brainstorming** | [obra/superpowers](https://github.com/obra/superpowers) | A full agentic-development methodology: composable skills (brainstorming, TDD red-green-refactor, git-worktrees) that auto-trigger without being invoked by name. Use its brainstorming skill to pressure-test a feature idea before gstack's `/office-hours` and `/plan-eng-review` lock in architecture. |
| **Product/CEO framing** | gstack `/office-hours`, `/plan-ceo-review` | Six forcing questions that reframe the request before code; four scope modes (Expansion/Selective Expansion/Hold Scope/Reduction) to decide how big a feature should actually be. |
| **Architecture lock-in** | gstack `/plan-eng-review` | Data flow diagrams, edge cases, test matrix, failure modes — before writing code. |
| **Frontend design system & UI patterns** | [nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) | Design intelligence: UI styles, color palettes, font pairings, UX guidelines, and reasoning rules, usable across Claude Code, Cursor, Codex CLI, and others via `npx skills add nextlevelbuilder/ui-ux-pro-max-skill`. Use this to pick the actual design system for the rebuilt frontend (Section 5), not ad hoc Tailwind classes. |
| **Frontend taste / anti-"AI slop"** | [leonxlnx/taste-skill](https://github.com/leonxlnx/taste-skill) (and its `pbakaus/impeccable`-derived variants, e.g. [h3nryprod01/design-taste](https://github.com/h3nryprod01/design-taste)) | A calibrated sense of good vs. generic layout, typography, color, and motion — the check that stops the rebuild from looking like default shadcn-with-a-gradient. Run this pass after `ui-ux-pro-max` produces the system, before shipping any screen. |
| **Design review against the plan** | gstack `/plan-design-review`, `/design-review` | Rates each design dimension 0-10 against what a 10 looks like; `/design-review` does the same audit live against shipped screens with before/after screenshots. |
| **Web quality / performance gate** | [addyosmani/web-quality-skills](https://github.com/addyosmani/web-quality-skills) | Framework-agnostic Agent Skills that check a project against Lighthouse guidelines and Core Web Vitals. Run this before every `/ship` on frontend work — a rebuilt UI that's slow or fails Core Web Vitals isn't actually better. |
| **Staff-engineer code review** | gstack `/review` | Finds bugs that pass CI but blow up in production; auto-fixes the obvious ones. |
| **QA** | gstack `/qa` | Opens a real browser, clicks through flows, fixes what it finds, writes a regression test. |
| **Security** | gstack `/cso` | OWASP Top 10 + STRIDE threat model — run once multi-tenancy and auth land (Section 9), since that's exactly where cross-workspace data leaks would happen. |
| **Ship** | gstack `/ship`, `/land-and-deploy` | Test + coverage audit + PR, then merge/deploy/verify. |
| **Docs** | gstack `/document-release` | Keeps README/ARCHITECTURE/this file current automatically — point it at `PROJECT.md` and `docs/poc_scope.md` so they don't go stale the way the original README did. |
| **Retro** | gstack `/retro` | Weekly retro once more than one person (or agent) is shipping against this plan. |

### 4.2 The loop, concretely, per feature in the roadmap below

1. **Think:** `superpowers` brainstorming skill (or gstack `/office-hours` if the feature is already well-formed) — don't skip this even for "obvious" features; the original POC's fake voice/matching features are exactly what happens when this step is skipped.
2. **Plan:** gstack `/plan-eng-review` (always) + `/plan-design-review` (if the feature touches UI, invoking `ui-ux-pro-max` + `taste-skill` as inputs).
3. **Build:** implement against the locked plan.
4. **Review:** gstack `/review`, plus `/cso` for anything touching auth/multi-tenancy/payments.
5. **Quality gate:** `web-quality-skills` for frontend work; automated tests (pytest/vitest — see Section 6) for backend work.
6. **QA:** gstack `/qa` against a running staging environment.
7. **Ship:** gstack `/ship` → `/land-and-deploy`.
8. **Document + Reflect:** `/document-release`, then `/retro` at the end of each phase, not each feature.

---

## 5. Frontend rebuild plan

The POC frontend (Section 1) proved the workflow builder concept but was hand-built with ad hoc Tailwind, not a real design system. Rebuild it properly:

1. **Design system first.** Run `ui-ux-pro-max` to select: UI style, color palette, font pairing, and the UX guidelines that fit a trust-heavy, financial-decision product (property buying) — not a generic SaaS dashboard look.
2. **Taste pass.** Run `taste-skill` against every screen before it ships: chat, dashboard, configure wizard, docs. Specifically target the things flagged in the POC review — the voice modal's fake random-bar audio visualizer, the property card's generic layout — and fix them with real design reasoning, not more mock data.
3. **Rebuild screens in this order:** Chat (highest-traffic, most trust-sensitive) → Configure wizard (already has real backend wiring, just needs the design pass) → Dashboard (rebuild *and* wire to live data at the same time — see Section 6.3) → Docs.
4. **Quality gate every screen** with `web-quality-skills` before shipping — Core Web Vitals matter more on this rebuild than the POC, since this version is meant to go in front of real leads.
5. **Component architecture:** break the current monolithic `page.tsx`/`dashboard/page.tsx` files into the `components/chat/`, `components/property-card/`, `components/dashboard/` structure the original docs described but never built — this is table stakes for a team (human or agent) to work on screens independently without merge conflicts.

---

## 6. Backend functionality — what to understand before extending

Before adding anything, a full backend audit against what actually exists (not what the old README claimed) — this is already partially done in `docs/dubai-real-estate-ai-product-analysis.md`. The gaps that matter for v2:

### 6.1 Multi-tenancy (the biggest one)
Add `workspace_id` to `leads`, `properties`, `brokers`, `conversations`, `activities`. Every repository method in `app/database.py` needs a `workspace_id` filter added to every query. Every mock-store equivalent in `app/mock_store.py` needs the same. This is mechanical but must touch every single query — a good candidate for `/plan-eng-review` to enumerate exhaustively before building, since a missed filter is a cross-customer data leak, not just a bug.

### 6.2 Auth
Workspaces need an owner. Simplest defensible v2 approach: Supabase Auth (already using Supabase for data) with row-level security policies keyed on `workspace_id`, rather than building custom auth.

### 6.3 Dashboard on live data
Replace `MOCK_LEADS`/`STATS` in `frontend/app/dashboard/page.tsx` with real calls to `/api/v1/leads/`, filtered by the logged-in user's workspace.

### 6.4 WhatsApp
Real Meta WhatsApp Business API integration: inbound webhook → same agent pipeline lead-ingestion path already used by the web widget; outbound send for AI responses and broker handoff notifications. This is the single most valuable integration for the Dubai market specifically (see the earlier market analysis on WhatsApp being the dominant channel there, unlike the US-market competitors).

### 6.5 Testing
`pytest`/`pytest-asyncio` are already dependencies with nothing using them. Backfill tests for the agent graph and ingestion pipeline before multi-tenancy work starts — that refactor touches every query in the codebase and needs a safety net.

---

## 7. Real data sources plan

Builds on the ingestion pipeline already in place (`docs/property_data_pipeline.md`):

1. **Keep as primary:** CSV/CRM import (broker-controlled, zero legal risk, fastest onboarding), approved feeds, RapidAPI UAE real estate.
2. **Keep as live scraper:** Property Finder only, per the existing deferral of Bayut/Dubizzle.
3. **Investigate for v2:** whether Bayut, Dubizzle, or aggregators like Reidin/Property Monitor offer a licensed data API or partnership — this is the legitimate way to re-enable those sources, not better anti-bot evasion. Treat this as a business-development task, not an engineering one.
4. **New:** a per-workspace scheduled sync (the Celery/Redis/APScheduler dependencies cut from the POC per the product review should come back here, deliberately, once there's an actual job to schedule — nightly CRM re-import, periodic Property Finder refresh).

---

## 8. Voice agent architecture (v2)

The POC fix made voice *functionally correct* (real transcription → real agent response → real synthesis) but it's still a relay, not a true voice agent — three round trips (STT, LLM, TTS) instead of one speech-to-speech model. For v2, evaluate:

- **OpenAI Realtime API** (GA since August 2025, GPT-Realtime 2.1) — native speech-to-speech, can combine voice with tool-calling directly, unified billing if the rest of the stack stays on an OpenAI-compatible path. Likely the strongest default choice for cutting the three-hop latency to one.
- **ElevenLabs Conversational AI** — broadest language/voice coverage and highest voice quality; worth evaluating specifically for Arabic voice quality, which the research didn't confirm either way — verify directly with the vendor before committing.
- **Deepgram Voice Agent API** — mature, enterprise-track-record, competitive for high-volume call-style workflows; a reasonable cost-conscious alternative to OpenAI/ElevenLabs.

Whichever is chosen, keep the current Groq/gTTS path as the free-tier fallback for workspaces that haven't configured a paid voice provider — the graceful-degradation pattern already used throughout this codebase is worth preserving, not replacing.

---

## 9. Multi-tenancy & auth — sequencing note

Do Section 6.1 (data isolation) and 6.2 (auth) together, not sequentially — auth without isolation is meaningless, and isolation without auth has no owner to scope to. Run gstack `/cso` immediately after this phase, before any real customer data goes into the system.

---

## 10. Phased roadmap

| Phase | Scope | Definition of done |
|---|---|---|
| **0 — POC** (done) | Fix fake features, workflow builder, in-app docs | Shipped — see `docs/poc_scope.md` |
| **1 — Data foundation** | Multi-tenancy (6.1), auth (6.2), backfill tests (6.5) | A second workspace's leads/properties are provably invisible to the first; `/cso` finds no cross-tenant leak |
| **2 — Frontend rebuild** | Design system + taste pass + component architecture (Section 5) | Every screen passes `web-quality-skills` gate and a `/design-review` |
| **3 — Real channels** | WhatsApp integration (6.4), dashboard on live data (6.3) | A real WhatsApp message round-trips through the agent pipeline end to end |
| **4 — Voice agent v2** | Evaluate + integrate a speech-to-speech provider (Section 8) | Voice latency measurably lower than the three-hop relay; fallback path still works with no provider configured |
| **5 — Data partnerships** | Investigate licensed Bayut/Dubizzle/aggregator access (Section 7.3) | Either a real integration ships, or a documented decision not to pursue it |
| **6 — Billing** | Map workspace → paying account | A workspace can be created, paid for, and suspended on non-payment |

Each phase runs the full loop in Section 4.2, not just "build."

---

## 11. Setting up the skill packs

```bash
# gstack — the engineering-team process
git clone --single-branch --depth 1 https://github.com/garrytan/gstack.git ~/.claude/skills/gstack && cd ~/.claude/skills/gstack && ./setup

# superpowers — planning/brainstorming/TDD methodology
# see https://github.com/obra/superpowers for current install instructions

# ui-ux-pro-max — design system intelligence (multi-harness)
npx skills add nextlevelbuilder/ui-ux-pro-max-skill

# taste-skill — frontend taste / anti-slop pass
# see https://github.com/leonxlnx/taste-skill for current install instructions

# web-quality-skills — Lighthouse / Core Web Vitals gate
# see https://github.com/addyosmani/web-quality-skills for current install instructions
```

Verify each installed correctly before Phase 1 starts — install steps for community skill packs change; check each repo's own README at install time rather than trusting this list to stay current.

---

## Sources

- [garrytan/gstack](https://github.com/garrytan/gstack)
- [obra/superpowers](https://github.com/obra/superpowers)
- [nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill)
- [leonxlnx/taste-skill](https://github.com/leonxlnx/taste-skill), [h3nryprod01/design-taste](https://github.com/h3nryprod01/design-taste)
- [addyosmani/web-quality-skills](https://github.com/addyosmani/web-quality-skills)
- [Best Voice Agent Platforms 2026 — Inworld](https://inworld.ai/resources/best-voice-agent-platforms)
- [Real-Time Speech-to-Speech APIs Compared — CallMissed](https://www.callmissed.com/en/blog/real-time-speech-apis-compared-best-voice)
- Internal: `docs/poc_scope.md`, `docs/dubai-real-estate-ai-product-analysis.md`, `docs/property_data_pipeline.md`, `docs/scraper_operations.md`
