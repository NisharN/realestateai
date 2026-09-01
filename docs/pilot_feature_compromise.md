# Pilot Feature Compromise — Roundtable Outcome

Result of a moderated negotiation between three advisory perspectives (senior Dubai broker, technical consultant, product manager) reconciling prior disagreements on sequencing, listing staleness, Ejari/Form F scope, voice, and which reminders are worth building. Five open tensions from earlier rounds, each resolved to an explicit compromise below.

## Transcript

**PM:** Let's settle sequencing first. Amina, I know Tariq had scheduler, WhatsApp send, budget extraction, reminders, DLD map — parallel, no dependency. I still think that's backwards. If we send a WhatsApp reply before we've parsed the client's budget correctly—

**CONSULTANT:** —it's not "before," it's parallel tracks, they don't block each other—

**PM:** They don't block *each other*, but they block *trust*. First message a lead gets from this thing, if it says "villas from AED 800,000" when the guy typed "1.2M," that's the whole pitch dead in one text. Budget/currency parsing has to be solid before send goes live, even in a demo.

**CONSULTANT:** Fine — that's actually cheap to re-order, it's a two-day extraction module, I'm not going to die on that hill. Budget before send.

**BROKER:** Good, because half my leads write "1.2" meaning million and half mean *dirhams* and I've seen an agent quote a guy 1,200 AED for a two-bed. That mistake is real.

**PM:** Right. But the DLD map — that's the one I actually care about moving. That map screenshot is the thing that gets a broker to forward this to her manager. It cannot sit behind reminders in the build order.

**CONSULTANT:** It's not "behind" reminders, it's parallel—

**PM:** Parallel means it ships whenever, Tariq, and "whenever" for a solo founder means week five. I want a demo-ready DLD map — static, cached transaction data, doesn't need to be live — done in week two, alongside scheduler.

**CONSULTANT:** ...Okay. A stub version, cached quarterly DLD data, no live API polling — that's genuinely a few days, not a rebuild. I can front-load that.

**PM:** Deal. New order: scheduler, budget/currency, WhatsApp send, DLD map demo stub in parallel with send, then reminders.

**BROKER:** Now the one I actually asked for — reposting. Bayut, PF, Dubizzle, my listings sink if I don't refresh them every few days and I don't have time to rewrite them each time.

**CONSULTANT:** I will not touch the actual repost. Automating a submit click on a portal you don't own the API for is the same ToS problem as scraping — get one client's Bayut account flagged and banned and that's a lawsuit magnet, not a feature.

**PM:** Nobody's asking you to auto-post. But a staleness *tracker* — a dashboard that says "this listing is 9 days stale" — that's a to-do list with extra steps. Nobody pays for a reminder to do work they already know they need to do.

**BROKER:** Actually — hold on. The reminder isn't the hard part for me. The hard part is I open the listing and stare at it for ten minutes trying to write a *new* description that doesn't sound identical to the old one, because the portals dock you for duplicate content.

**PM:** So it's not the nudge, it's the blank page.

**BROKER:** Exactly. If it just handed me a fresh variant — new opening line, updated price positioning if the market moved — and I copy-paste it myself, that saves me the actual annoying part.

**CONSULTANT:** That I can build safely — it's generation, not posting, no portal integration, no ToS surface at all. But it needs a trigger to know *when* a listing's gone stale in the first place, so the tracker isn't dead, it just stops being the product and becomes the plumbing.

**PM:** Fine — tracker as backend trigger, copy generator as the feature we put on the tin.

**BROKER:** Next: Ejari, Form F. I asked for this because my RERA license is on the line every time I fill one wrong. I don't want AI *submitting* anything for me.

**PM:** Which is exactly why I want it cut. "Draft-only" is still generating government-form content a broker might trust too much and rubber-stamp.

**BROKER:** But I never asked for pre-fill of my client's actual data into a live form. I asked for something that stops me forgetting a required document at 6pm before a signing.

**CONSULTANT:** So — zero data auto-fill. A checklist and document-prep aid: required fields, required attachments, sequencing of what's needed, no client data pre-populated, nothing that could be "wrong." That has basically no liability surface because it isn't generating anything, it's organizing.

**PM:** ...That I can sell and defend to legal. Checklist yes, pre-fill no.

**BROKER:** That's genuinely what I wanted anyway.

**PM:** Voice. Realtime API. I keep wanting to ship it English-expat-only with a hard fence.

**CONSULTANT:** A hard fence means language/locale detection that reliably rejects Arabic-inflected or code-switched speech before it embarrasses the client. That detection layer is its own R&D project for a solo FDE on a six-week clock.

**BROKER:** And my clients don't stay in one lane — an Emirati client will start in Arabic and drop into English mid-sentence. A fence that mis-detects and lets voice run in the wrong context is worse than no voice.

**PM:** ...Fine. Cut it. Not fenced, not shipped — deferred past the pilot entirely, revisit if the pilot shows demand.

**PM:** Last one — reminders. I said viewing reminders and expired-listing nudges are table stakes, mandate renewal and market reports are the real sell.

**BROKER:** They're not the pitch, sure. But I still need them done. If your tool doesn't do it I'm doing it in a notebook.

**PM:** Then they ship, just not as marketed features — bundled into one "reminders engine" under the hood, mandate renewal and market reports get the demo slide, viewing/expiry reminders ride along for free.

## Consolidated Pilot Scope (4-6 weeks)

| Feature | What ships in the pilot | Why (whose concern it resolves) | Deferred/cut and why |
|---|---|---|---|
| Scheduler | Full build, week 1 | Baseline, uncontested | — |
| Budget/currency extraction | Built before WhatsApp send goes live | PM: trust risk of a wrong quote in the first message | — |
| WhatsApp send | Built after extraction | Consultant's build path preserved, just reordered | — |
| DLD transaction map | Demo-ready static/cached stub, week 2, parallel to send | PM: most screenshot-able, sales-critical asset | Live/real-time DLD polling deferred, static cache is enough for pilot |
| Listing refresh copy generator | Generates new description/price blurb, broker one-taps to copy/repost herself | Broker: kills the "blank page" time-sink; Consultant: no ToS exposure, no auto-posting | Automated repost to Bayut/PF/Dubizzle cut entirely — ban risk |
| Staleness tracker | Built as backend trigger for the copy generator, not a standalone screen | PM's "to-do list" objection resolved by hiding it as plumbing | Standalone staleness dashboard as a marketed feature cut |
| Ejari/Form F prep | Checklist + required-document aid, zero data pre-fill | Broker: protects her RERA license; PM: no liability surface since nothing is generated/could be wrong | Pre-filled forms, e-signature, government API integration all cut |
| Real-time voice | Not built | Consultant: fence is its own R&D project on a tight clock; Broker: mixed Arabic/English calls make a fence unsafe | Entirely deferred past pilot, revisit post-pilot with demand signal |
| Mandate renewal reminders | Built, marketed as differentiator | PM: protects commission revenue directly, real sales weight | — |
| Market reports | Built, marketed as differentiator | PM: proprietary data, hardest to copy | — |
| Viewing reminders / expired-listing nudges | Built, bundled into reminders engine, not separately marketed | Broker: operational relief still needed even if it doesn't sell | Not cut — just not the pitch |
