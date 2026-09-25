---
name: realestate-demo-runtime-testing
description: Run buyer conversation, WhatsApp signing, and UI regression checks against the local demo.
---

# Local demo runtime testing

Use the repository blueprint for dependencies and service startup. Confirm
`http://localhost:8000/health` reports the intended mock/fallback modes before
creating test leads.

Set frontend `NEXT_PUBLIC_API_URL=http://localhost:8000` and
`NEXT_PUBLIC_DEMO_MODE=true` for local demo testing. Restart Next.js when changing
startup environment values. If demo routes redirect to login, check that the
middleware honors demo mode instead of entering real credentials.

Avoid editing Next.js configuration during a UI recording. If a development
restart invalidates dynamic Leaflet chunks, fully reload once the server settles
and recapture evidence.

Use unique names and phones for each buyer run, and a unique provider message ID
for each WhatsApp event. Repeat the exact raw body and signature to test dedupe.
Use the payload shape in `backend/tests/test_channels_api.py` and HMAC SHA256 of
the raw bytes, not a reserialized body after signing.

Compare visible property card and marker values with the backend response.
Measure all buyer requests rather than only the first turn. Also inspect the
dashboard after qualification: conversation-profile values and legacy lead
columns can diverge, even when the chat itself correctly retains state.

The Voice Conversation modal is available on the buyer page. Check opening,
text fallback, and closing separately. A closed/rejected WebSocket can leave
the text fallback thinking indefinitely; inspect backend connection logs before
attributing the behavior to missing STT/TTS providers.

## Devin Secrets Needed

No production credentials are required for local demo chat or mock outbound
WhatsApp. Signed inbound webhook testing requires `META_APP_SECRET` in the
backend process; use an ephemeral local-only value when explicitly authorized.
Never claim real Meta delivery or production database persistence from mock-mode
results.
