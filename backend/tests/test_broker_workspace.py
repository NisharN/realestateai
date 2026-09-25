"""Phase 4: handoff accept/decline/reassign, follow-up schedules (consent + DND),
Broker Today / pipeline / lead detail / lead edit endpoints."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import mock_store
from app.config import get_settings
from app.database import get_lead_repository
from app.main import app
from app.modules.conversation.state import ConversationState
from app.modules.handoff import followups
from app.modules.handoff.service import REASSIGN_AFTER_MIN, create_handoff, reassign_stale
from app.modules.store import reset_memory, table
from app.services.whatsapp import get_outbox

client = TestClient(app, raise_server_exceptions=False)
WS = get_settings().WORKSPACE_ID
DUBAI = timezone(timedelta(hours=4))


@pytest.fixture(autouse=True)
def _clean():
    seeded = dict(mock_store._leads)
    mock_store._leads.clear()
    reset_memory()
    get_outbox().clear()
    yield
    reset_memory()
    mock_store._leads.clear()
    mock_store._leads.update(seeded)


async def _lead(**over) -> dict:
    data = {"first_name": "Ahmed", "last_name": "Ali", "phone": "+971501234567", "source": "csv_upload", "preferred_language": "en", "status": "new", **over}
    return await get_lead_repository(WS).create(data)


def _state(lead_id: str, **slots) -> ConversationState:
    state = ConversationState(lead_id=lead_id, channel="chat")
    for k, v in {"purpose": "buy", "budget_max_aed": 1_500_000, "community_ids": ["dubai_marina"], "property_type": "apartment", **slots}.items():
        state.set_slot(k, v, source="buyer")
    state.score, state.band = 82, "hot"
    return state


async def _handoff(lead_id: str | None = None):
    lead = await _lead(id=lead_id) if lead_id else await _lead()
    return lead, await create_handoff(_state(lead["id"]), workspace_id=WS, reason="qualified_confirmed")


# -- handoff lifecycle -----------------------------------------------------

async def test_create_handoff_routes_by_area_persists_brief_and_alerts():
    lead, h = await _handoff()
    assert h["status"] == "pending" and h["broker_id"] == "broker-2"  # Marina specialist
    assert h["brief"]["headline"] and h["brief"]["next_step"]
    assert any("broker-2" in str(reason) or "Marina" in str(reason) or "area" in str(reason).lower() for reason in h["routing_reasons"])
    assert get_outbox().list()[-1]["to"] == "971509876543"
    assert (await get_lead_repository(WS).get_by_id(lead["id"]))["assigned_broker"] == "broker-2"


async def test_stale_handoff_reassigns_after_15_minutes_then_escalates():
    lead, h = await _handoff()
    assert await reassign_stale(WS) == []  # not stale yet

    later = datetime.now(timezone.utc) + timedelta(minutes=REASSIGN_AFTER_MIN + 1)
    changed = await reassign_stale(WS, now=later)
    assert len(changed) == 1 and changed[0]["broker_id"] == "broker-1" and changed[0]["reassigned_count"] == 1
    assert changed[0]["tried_broker_ids"] == ["broker-2"]
    assert (await get_lead_repository(WS).get_by_id(lead["id"]))["assigned_broker"] == "broker-1"

    even_later = later + timedelta(minutes=REASSIGN_AFTER_MIN + 1)
    changed = await reassign_stale(WS, now=even_later)
    assert changed[0]["status"] == "escalated"
    types = [e["type"] for e in await table("lead_events", WS).select(lead_id=lead["id"])]
    assert types == ["handoff.created", "handoff.reassigned", "handoff.escalated"]


def test_accept_and_decline_via_api():
    import asyncio

    lead, h = asyncio.get_event_loop().run_until_complete(_handoff())
    wrong = client.post(f"/api/v1/broker/handoffs/{h['id']}/accept", json={"broker_id": "broker-1"})
    assert wrong.status_code == 409

    declined = client.post(f"/api/v1/broker/handoffs/{h['id']}/decline", json={"broker_id": "broker-2", "reason": "on leave"})
    assert declined.status_code == 200
    assert declined.json()["broker_id"] == "broker-1" and declined.json()["status"] == "pending"
    assert declined.json()["decline_reason"] == "on leave"

    accepted = client.post(f"/api/v1/broker/handoffs/{h['id']}/accept", json={"broker_id": "broker-1"})
    assert accepted.status_code == 200 and accepted.json()["status"] == "accepted"
    again = client.post(f"/api/v1/broker/handoffs/{h['id']}/decline", json={"broker_id": "broker-1"})
    assert again.status_code == 409


def test_admin_requires_broker_id_for_handoff_actions():
    assert client.post("/api/v1/broker/handoffs/nope/accept").status_code == 400


# -- follow-ups ------------------------------------------------------------

def test_clamp_to_window_respects_dnd():
    late = datetime(2026, 9, 25, 22, 30, tzinfo=DUBAI)
    early = datetime(2026, 9, 25, 6, 0, tzinfo=DUBAI)
    fine = datetime(2026, 9, 25, 14, 0, tzinfo=DUBAI)
    assert followups.clamp_to_window(late).astimezone(DUBAI) == datetime(2026, 9, 26, 9, 0, tzinfo=DUBAI)
    assert followups.clamp_to_window(early).astimezone(DUBAI) == datetime(2026, 9, 25, 9, 0, tzinfo=DUBAI)
    assert followups.clamp_to_window(fine) == fine
    assert not followups.in_window(late) and followups.in_window(fine)


async def test_schedule_followups_cadence_and_cancellation():
    lead = await _lead()
    rows = await followups.schedule_followups(lead["id"], "warm", workspace_id=WS, now=datetime(2026, 9, 25, 20, 0, tzinfo=DUBAI))
    assert [r["touch"] for r in rows] == [1, 2, 3]
    assert all(followups.in_window(datetime.fromisoformat(r["due_at"])) for r in rows)
    assert len(await followups.schedule_followups(lead["id"], "cold", workspace_id=WS)) == 2  # replaces, not appends
    assert await table("followups", WS).count(lead_id=lead["id"], status="pending") == 2
    assert await followups.cancel_followups(lead["id"], workspace_id=WS, reason="handed_off") == 2
    assert await followups.schedule_followups(lead["id"], "hot", workspace_id=WS) == []


async def test_no_followups_without_consent_or_after_opt_out():
    opted = await _lead(opted_out_at="2026-09-25T00:00:00+00:00", phone="+971500000001")
    assert await followups.schedule_followups(opted["id"], "warm", workspace_id=WS) == []
    no_consent = await _lead(consent={"marketing": False}, phone="+971500000002")
    assert await followups.schedule_followups(no_consent["id"], "warm", workspace_id=WS) == []
    no_phone = await _lead(phone=None, email="x@y.com")
    assert await followups.schedule_followups(no_phone["id"], "warm", workspace_id=WS) == []


async def test_send_due_skips_outside_window_and_rechecks_opt_out():
    lead = await _lead()
    due = datetime(2026, 9, 25, 10, 0, tzinfo=DUBAI)
    await table("followups", WS).insert({"lead_id": lead["id"], "touch": 1, "template_key": "followup_1", "due_at": (due - timedelta(hours=1)).isoformat(), "status": "pending"})
    assert await followups.send_due(WS, now=datetime(2026, 9, 25, 23, 0, tzinfo=DUBAI)) == []
    sent = await followups.send_due(WS, now=due)
    assert len(sent) == 1 and sent[0]["status"] == "sent" and "Ahmed" in sent[0]["text"]
    assert get_outbox().list()[-1]["to"] == "971501234567"

    await table("followups", WS).insert({"lead_id": lead["id"], "touch": 2, "template_key": "followup_2", "due_at": due.isoformat(), "status": "pending"})
    await get_lead_repository(WS).update(lead["id"], {"opted_out_at": "2026-09-25T09:00:00+00:00"})
    assert await followups.send_due(WS, now=due) == []
    assert await table("followups", WS).count(lead_id=lead["id"], status="cancelled") == 1


# -- broker endpoints ------------------------------------------------------

def test_broker_today_pipeline_detail_and_edit():
    import asyncio

    loop = asyncio.get_event_loop()
    lead, h = loop.run_until_complete(_handoff())
    loop.run_until_complete(_lead(phone="+971500000009", first_name="Cold", status="new", intent_score=10))

    today = client.get("/api/v1/broker/today", params={"broker_id": "broker-2"}).json()
    assert today["counts"]["new_handoffs"] == 1 and today["new_handoffs"][0]["lead"]["id"] == lead["id"]
    assert today["new_handoffs"][0]["handoff"]["reassign_after"]

    everyone = client.get("/api/v1/broker/today").json()
    assert everyone["counts"]["new_handoffs"] == 1

    pipe = client.get("/api/v1/broker/pipeline").json()
    stages = {s["stage"]: s["count"] for s in pipe["stages"]}
    assert stages["handed_off"] == 1 and stages["new"] == 1

    detail = client.get(f"/api/v1/broker/leads/{lead['id']}").json()
    assert detail["brief"]["headline"] and detail["handoff"]["id"] == h["id"]
    assert [t["type"] for t in detail["timeline"] if t["kind"] == "event"] == ["handoff.created"]

    edit = client.patch(f"/api/v1/broker/leads/{lead['id']}", json={"budget_max_aed": 1_800_000, "stage": "viewing_booked", "notes": "prefers weekends"})
    assert edit.status_code == 200 and set(edit.json()["changed"]) == {"budget_max_aed", "stage", "notes"}
    detail = client.get(f"/api/v1/broker/leads/{lead['id']}").json()
    assert detail["lead"]["budget_max_aed"] == 1_800_000 and detail["lead"]["stage"] == "viewing_booked"
    changes = [t for t in detail["timeline"] if t["kind"] == "change"]
    assert {c["field"] for c in changes} == {"budget_max_aed", "stage", "notes"} and changes[0]["by"] == "broker"

    assert client.get("/api/v1/broker/leads/missing").status_code == 404
    assert client.post("/api/v1/broker/handoffs/reassign-stale").json() == {"reassigned": 0, "escalated": 0}


# -- PR #8 review regressions ----------------------------------------------

async def test_failed_send_stays_pending_and_due_rows_come_first():
    from unittest.mock import patch

    from app.services.whatsapp import OutboundMessage

    lead = await _lead()
    due = datetime(2026, 9, 25, 10, 0, tzinfo=DUBAI)
    fu = table("followups", WS)
    for touch in range(1, 4):
        await fu.insert({"lead_id": lead["id"], "touch": touch, "template_key": "followup_1", "due_at": (due + timedelta(days=touch)).isoformat(), "status": "pending"})
    await fu.insert({"lead_id": lead["id"], "touch": 9, "template_key": "followup_1", "due_at": (due - timedelta(hours=1)).isoformat(), "status": "pending"})

    async def failing(*_args, **_kwargs):
        return OutboundMessage(id="m1", to="x", body="y", status="failed", error="provider down")

    with patch("app.modules.handoff.followups.get_whatsapp_service") as svc:
        svc.return_value.send_text = failing
        assert await followups.send_due(WS, now=due, limit=2) == []
    row = (await fu.select(touch=9))[0]
    assert row["status"] == "pending" and row["attempts"] == 1 and "provider down" in row["error"]

    sent = await followups.send_due(WS, now=due, limit=2)
    assert [s["touch"] for s in sent] == [9]


def test_agent_without_broker_profile_gets_403_and_no_unassigned_followups():
    import asyncio

    from app.auth import RequestContext, WorkspaceRole, get_request_context

    loop = asyncio.get_event_loop()
    lead = loop.run_until_complete(_lead())
    loop.run_until_complete(table("followups", WS).insert({"lead_id": lead["id"], "touch": 1, "template_key": "followup_1", "due_at": "2026-09-25T06:00:00+00:00", "status": "pending"}))

    async def unprofiled():
        return RequestContext(user_id="u", workspace_id=WS, role=WorkspaceRole.AGENT, broker_id=None)

    async def agent():
        return RequestContext(user_id="u", workspace_id=WS, role=WorkspaceRole.AGENT, broker_id="broker-2")

    try:
        app.dependency_overrides[get_request_context] = unprofiled
        assert client.get("/api/v1/broker/today").status_code == 403
        assert client.get("/api/v1/broker/pipeline").status_code == 403
        assert client.get(f"/api/v1/broker/leads/{lead['id']}").status_code in (403, 404)
        app.dependency_overrides[get_request_context] = agent
        assert client.get("/api/v1/broker/followups").json() == []
        assert client.get("/api/v1/broker/today").json()["counts"]["followups_due"] == 0
    finally:
        app.dependency_overrides.clear()
    assert client.get("/api/v1/broker/followups").json() != []


def test_viewings_api_lifecycle_and_stage_sync():
    import asyncio

    loop = asyncio.get_event_loop()
    lead, h = loop.run_until_complete(_handoff())
    starts = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

    created = client.post("/api/v1/broker/viewings", json={"lead_id": lead["id"], "property_id": "prop-1", "starts_at": starts, "confirmed": False})
    assert created.status_code == 201, created.text
    v = created.json()
    assert v["status"] == "requested" and v["source"] == "broker" and v["broker_id"] == h["broker_id"]

    dup = client.post("/api/v1/broker/viewings", json={"lead_id": lead["id"], "property_id": "prop-1", "starts_at": starts, "confirmed": False}).json()
    assert dup["id"] == v["id"]

    listed = client.get("/api/v1/broker/viewings", params={"lead_id": lead["id"], "status": "requested"}).json()
    assert [x["id"] for x in listed] == [v["id"]]
    assert client.get("/api/v1/broker/today").json()["counts"]["viewings"] == 1

    bad = client.patch(f"/api/v1/broker/viewings/{v['id']}", json={"status": "done"})
    assert bad.status_code == 409

    ok = client.patch(f"/api/v1/broker/viewings/{v['id']}", json={"status": "confirmed", "notes": "meet at lobby"})
    assert ok.status_code == 200 and ok.json()["status"] == "confirmed" and ok.json()["notes"] == "meet at lobby"
    detail = client.get(f"/api/v1/broker/leads/{lead['id']}").json()
    assert detail["lead"]["stage"] == "viewing_booked"
    assert [x["status"] for x in detail["viewings"]] == ["confirmed"]
    assert any(t.get("type") == "viewing.confirmed" for t in detail["timeline"])

    done = client.patch(f"/api/v1/broker/viewings/{v['id']}", json={"status": "done"})
    assert done.status_code == 200
    assert client.get("/api/v1/broker/today").json()["counts"]["viewings"] == 0
    assert client.patch("/api/v1/broker/viewings/missing", json={"status": "done"}).status_code == 404
    assert client.post("/api/v1/broker/viewings", json={"lead_id": "missing", "starts_at": starts}).status_code == 404
