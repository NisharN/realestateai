"""Co-work v2: structured lead extraction (Gmail / Meta), continuous re-scoring,
analytics + Copilot, broker routine steps and the independent voice-note connector."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import socket as _socket
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import get_lead_repository
from app.main import app
from app.modules.agents import rescoring
from app.modules.analytics.queries import AnalyticsQuery, parse_question, run_query
from app.modules.cowork import connections, routines
from app.modules.cowork.connections import ConnectionIn
from app.modules.cowork.lead_extraction import (
    extract_lead,
    extract_lead_rules,
    gmail_message_text,
    meta_lead_payload,
)
from app.modules.cowork.providers import get_provider
from app.modules.cowork.routines import RoutineIn, Schedule, Step
from app.modules.store import reset_memory, table

client = TestClient(app, raise_server_exceptions=False)
WS = get_settings().WORKSPACE_ID
AUTH = {"Authorization": "Bearer demo-owner"}


@pytest.fixture(autouse=True)
def _clean():
    from app import mock_store

    saved = dict(mock_store._leads)
    real_gai = _socket.getaddrinfo
    reset_memory()
    connections.set_client_factory(None)
    yield
    mock_store._leads.clear()
    mock_store._leads.update(saved)
    _socket.getaddrinfo = real_gai
    reset_memory()
    connections.set_client_factory(None)


def _mock_http(handler):
    transport = httpx.MockTransport(handler)
    connections.set_client_factory(lambda: httpx.AsyncClient(transport=transport))
    _socket.getaddrinfo = lambda *a, **k: [(2, 1, 6, "", ("104.18.0.1", 443))]


def _ago(hours: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


# ---------------------------------------------------------------- extraction


def test_bayut_email_is_parsed_into_structured_lead():
    body = """<html><body><p>You have a new lead for your listing <b>Ref: BAY-88213</b></p>
    <p>Name: Fatima Al Zarooni<br>Phone: 050 123 4567<br>Email: fatima.z@example.com</p>
    <p>Message: Hi, I'm looking to buy a 2 bedroom apartment in Palm Jumeirah, budget around 3.2M AED.</p>
    </body></html>"""
    lead = extract_lead_rules("New enquiry on Bayut", body, "noreply@bayut.com")
    assert lead.phone == "+971501234567"
    assert lead.email == "fatima.z@example.com"
    assert lead.listing_reference == "BAY-88213"
    assert lead.area == "Palm Jumeirah"
    assert lead.property_type == "apartment"
    assert lead.bedrooms == "2"
    assert lead.budget_max_aed == 3_200_000
    assert lead.purpose == "buy"
    assert lead.source == "bayut"
    assert lead.name and "Fatima" in lead.name


def test_portal_sender_is_never_taken_as_buyer_email_and_missing_contact_is_flagged():
    lead = extract_lead_rules("Property Finder lead", "Someone viewed your listing.", "leads@propertyfinder.ae")
    assert lead.email is None
    assert lead.phone is None
    assert lead.confidence < 0.5


@pytest.mark.asyncio
async def test_extract_lead_falls_back_to_rules_when_llm_unavailable():
    lead = await extract_lead("Dubizzle enquiry", "Call me on +971 55 987 6543 about the villa in Dubai Hills", "no-reply@dubizzle.com", use_llm=True)
    assert lead.phone == "+971559876543"
    assert lead.area == "Dubai Hills Estate"
    assert lead.property_type == "villa"


def test_gmail_mime_decoding_handles_multipart_base64():
    text = base64.urlsafe_b64encode(b"Name: Omar\nPhone: +971 50 111 2222\nBudget 1.5m rent").decode()
    msg = {
        "payload": {
            "headers": [{"name": "Subject", "value": "New lead"}, {"name": "From", "value": "Bayut <noreply@bayut.com>"}],
            "mimeType": "multipart/alternative",
            "parts": [{"mimeType": "text/plain", "body": {"data": text}}],
        }
    }
    subject, sender, body = gmail_message_text(msg)
    assert subject == "New lead" and "bayut.com" in sender and "Omar" in body
    lead = extract_lead_rules(subject, body, sender)
    assert lead.phone == "+971501112222" and lead.budget_max_aed == 1_500_000 and lead.purpose == "rent"


def test_meta_field_data_maps_to_common_lead_payload():
    lead = {
        "id": "lg_123",
        "created_time": "2026-09-25T08:00:00+0000",
        "ad_id": "ad_1",
        "campaign_name": "Palm Jumeirah launch",
        "field_data": [
            {"name": "full_name", "values": ["Sara Khan"]},
            {"name": "phone_number", "values": ["+971561234567"]},
            {"name": "email", "values": ["sara@example.com"]},
            {"name": "which_area_are_you_interested_in?", "values": ["Palm Jumeirah"]},
            {"name": "budget", "values": ["2,500,000"]},
        ],
    }
    p = meta_lead_payload(lead, form_id="form_9", page_id="page_1")
    assert p["external_id"] == "lg_123"
    assert p["phone"] == "+971561234567"
    assert p["email"] == "sara@example.com"
    assert p["first_name"] == "Sara" and p["last_name"] == "Khan"
    assert p["area_preference"] == "Palm Jumeirah"
    assert p["budget_max_aed"] == 2_500_000
    assert p["source"] == "meta_lead_ads"
    assert p["campaign"]["form_id"] == "form_9"


# ---------------------------------------------------------------- Meta webhook + pull


@pytest.mark.asyncio
async def test_meta_webhook_verifies_app_secret_and_resolves_lead_through_graph():
    conn = await connections.create_connection(
        WS,
        ConnectionIn(provider="meta_lead_ads", config={"page_id": "page_1", "access_token": "EAAB-token", "app_secret": "app-secret"}),
        actor="u1",
    )
    graph_calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        graph_calls.append(request.url.path)
        assert "EAAB-token" not in str(request.url)  # token travels in the header, never the URL
        return httpx.Response(200, json={"id": "lg_777", "created_time": "2026-09-25T08:00:00+0000", "field_data": [{"name": "full_name", "values": ["Ali Raza"]}, {"name": "phone_number", "values": ["+971509998877"]}]})

    _mock_http(handler)
    body = json.dumps({"object": "page", "entry": [{"id": "page_1", "changes": [{"field": "leadgen", "value": {"leadgen_id": "lg_777", "form_id": "form_1", "page_id": "page_1"}}]}]}).encode()
    good = "sha256=" + hmac.new(b"app-secret", body, hashlib.sha256).hexdigest()

    r = client.post(f"/api/v1/cowork/webhooks/{conn['id']}?workspace_id={WS}", content=body, headers={"X-Hub-Signature-256": "sha256=deadbeef", "Content-Type": "application/json"})
    assert r.status_code == 401
    r = client.post(f"/api/v1/cowork/webhooks/{conn['id']}?workspace_id={WS}", content=body, headers={"X-Hub-Signature-256": good, "Content-Type": "application/json"})
    assert r.status_code == 200, r.text
    assert graph_calls and any("lg_777" in p for p in graph_calls)
    raws = await table("raw_lead_records", WS).select()
    assert any((row.get("payload") or {}).get("phone") == "+971509998877" for row in raws)


@pytest.mark.asyncio
async def test_meta_scheduled_pull_dedupes_and_lands_leads():
    conn = await connections.create_connection(WS, ConnectionIn(provider="meta_lead_ads", config={"page_id": "page_1", "access_token": "tok"}), actor="u1")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/leadgen_forms"):
            return httpx.Response(200, json={"data": [{"id": "form_1", "status": "ACTIVE"}, {"id": "form_2", "status": "ARCHIVED"}]})
        if request.url.path.endswith("/form_1/leads"):
            lead = {"id": "lg_1", "created_time": "2026-09-25T08:00:00+0000", "field_data": [{"name": "full_name", "values": ["Ali"]}, {"name": "phone_number", "values": ["+971501111111"]}]}
            return httpx.Response(200, json={"data": [lead, lead]})
        return httpx.Response(404, json={})

    _mock_http(handler)
    row = await connections.get_connection(WS, conn["id"])
    out = await connections.execute_action(WS, row, "pull_leads", {})
    assert out["ok"], out
    assert out["fetched"] == 2
    leads = await get_lead_repository(WS).list_all(limit=500)
    assert len([lead for lead in leads if lead.get("phone") == "+971501111111"]) == 1


# ---------------------------------------------------------------- re-scoring


@pytest.mark.asyncio
async def test_rescoring_moves_score_up_for_engagement_and_down_for_silence_or_no_show():
    repo = get_lead_repository(WS)
    engaged = await repo.create({"first_name": "Eng", "phone": "+971500000011", "source": "t", "status": "new", "stage": "qualified", "score": 55, "band": "warm", "purpose": "buy", "budget_max_aed": 2_000_000, "timeline": "1-3 months", "area_preference": "Dubai Marina", "last_contact_at": _ago(2), "last_message": "yes I'd love a viewing this weekend"})
    await table("viewings", WS).insert({"id": "v1", "lead_id": engaged["id"], "status": "confirmed", "starts_at": _ago(-24), "created_at": _ago(1)})
    silent = await repo.create({"first_name": "Sil", "phone": "+971500000012", "source": "t", "status": "new", "stage": "qualifying", "score": 55, "band": "warm", "purpose": "buy", "budget_max_aed": 2_000_000, "timeline": "1-3 months", "last_contact_at": _ago(24 * 20)})
    await table("viewings", WS).insert({"id": "v2", "lead_id": silent["id"], "status": "no_show", "starts_at": _ago(48), "created_at": _ago(72)})
    opted = await repo.create({"first_name": "Out", "phone": "+971500000013", "source": "t", "status": "new", "stage": "opted_out", "score": 80, "band": "hot", "purpose": "buy", "budget_max_aed": 9_000_000, "timeline": "asap"})

    up = await rescoring.rescore_lead(await repo.get_by_id(engaged["id"]), workspace_id=WS, trigger="test")
    down = await rescoring.rescore_lead(await repo.get_by_id(silent["id"]), workspace_id=WS, trigger="test")
    out = await rescoring.rescore_lead(await repo.get_by_id(opted["id"]), workspace_id=WS, trigger="test")

    assert up["score"] > down["score"]
    assert down["score"] < 55
    assert out["band"] == "cold" and out["score"] < 40
    history = await table(rescoring.HISTORY_TABLE, WS).select()
    assert {h["lead_id"] for h in history} == {engaged["id"], silent["id"], opted["id"]}
    assert all(h["trigger"] == "test" for h in history)


@pytest.mark.asyncio
async def test_pull_triggers_rescoring_of_published_leads():
    conn = await connections.create_connection(WS, ConnectionIn(provider="broker_api", config={"base_url": "https://partner.example.com", "api_key": "k"}), actor="u1")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "p1", "name": "Rami Haddad", "phone": "+971502223344", "budget": 4_000_000, "area": "Palm Jumeirah", "purpose": "buy", "timeline": "asap"}]})

    _mock_http(handler)
    row = await connections.get_connection(WS, conn["id"])
    out = await connections.execute_action(WS, row, "pull_leads", {})
    assert out["ok"] and out["published"] >= 1, out
    history = await table(rescoring.HISTORY_TABLE, WS).select()
    assert history and history[0]["trigger"].startswith("ingest:")
    lead = next(lead for lead in await get_lead_repository(WS).list_all(limit=500) if lead.get("phone") == "+971502223344")
    assert lead["score"] >= 40  # budget + area + timeline → at least warm


# ---------------------------------------------------------------- analytics + Copilot


async def _seed_pipeline() -> None:
    from app import mock_store

    mock_store._leads.clear()
    repo = get_lead_repository(WS)
    rows = [
        {"first_name": "Palm1", "phone": "+971500000101", "source": "bayut", "stage": "qualified", "score": 88, "band": "hot", "area_preference": "Palm Jumeirah", "purpose": "buy", "budget_max_aed": 5_000_000, "last_contact_at": _ago(100), "created_at": _ago(24)},
        {"first_name": "Palm2", "phone": "+971500000102", "source": "meta_lead_ads", "stage": "new", "score": 45, "band": "warm", "area_preference": "Palm Jumeirah", "purpose": "invest", "budget_max_aed": 3_500_000, "last_contact_at": _ago(1), "created_at": _ago(2)},
        {"first_name": "Marina", "phone": "+971500000103", "source": "property_finder", "stage": "qualifying", "score": 72, "band": "hot", "area_preference": "Dubai Marina", "purpose": "rent", "budget_max_aed": 150_000, "last_contact_at": _ago(2), "created_at": _ago(200)},
        {"first_name": "Cold", "phone": "+971500000104", "source": "website", "stage": "new", "score": 12, "band": "cold", "area_preference": "JVC", "purpose": "buy", "budget_max_aed": 800_000, "last_contact_at": _ago(500), "created_at": _ago(600)},
    ]
    for r in rows:
        await repo.create({**r, "status": "new"})


def test_parse_question_maps_broker_language_to_typed_queries():
    q = parse_question("top 5 leads this week")
    assert q.metric == "top_leads" and q.limit == 5 and q.days == 7
    q = parse_question("who wants Palm Jumeirah")
    assert q.metric == "leads_for_area" and q.area == "Palm Jumeirah"
    q = parse_question("hot leads that went quiet for 3 days")
    assert q.metric == "stale_leads" and q.band == "hot" and q.stale_hours == 72
    q = parse_question("investors with budget over 3M")
    assert q.purpose == "invest" and q.min_budget_aed == 3_000_000
    q = parse_question("which source brings the hottest leads")
    assert q.metric == "source_mix"
    q = parse_question("which areas are most in demand")
    assert q.metric == "area_demand"


@pytest.mark.asyncio
async def test_analytics_queries_return_matching_leads():
    await _seed_pipeline()
    palm = await run_query(AnalyticsQuery(metric="leads_for_area", area="Palm Jumeirah", limit=10), workspace_id=WS)
    assert {r["name"] for r in palm.rows} == {"Palm1", "Palm2"}
    stale = await run_query(AnalyticsQuery(metric="stale_leads", band="hot", stale_hours=72), workspace_id=WS)
    assert [r["name"] for r in stale.rows] == ["Palm1"]
    top = await run_query(AnalyticsQuery(metric="top_leads", limit=2, days=365), workspace_id=WS)
    assert [r["name"] for r in top.rows] == ["Palm1", "Marina"]
    demand = await run_query(AnalyticsQuery(metric="area_demand", days=365), workspace_id=WS)
    assert demand.rows[0]["area"] == "Palm Jumeirah" and demand.rows[0]["leads"] == 2
    mix = await run_query(AnalyticsQuery(metric="source_mix", days=365), workspace_id=WS)
    assert {r["source"] for r in mix.rows} >= {"bayut", "meta_lead_ads"}


@pytest.mark.asyncio
async def test_copilot_ask_endpoint_answers_and_scopes_agents():
    await _seed_pipeline()
    r = client.post("/api/v1/analytics/ask", json={"question": "who wants Palm Jumeirah"}, headers=AUTH)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["query"]["metric"] == "leads_for_area"
    assert len(data["rows"]) == 2
    assert data["summary"] and data["suggested_actions"]
    assert all("phone" not in r or r["phone"] for r in data["rows"])

    r = client.get("/api/v1/analytics/questions", headers=AUTH)
    assert r.status_code == 200 and len(r.json()["questions"]) >= 5



# ---------------------------------------------------------------- routine steps


@pytest.mark.asyncio
async def test_routine_analytics_followups_and_auto_reject_steps():
    await _seed_pipeline()
    routine = await routines.create_routine(
        WS,
        RoutineIn(
            name="Palm + hygiene",
            schedule=Schedule(kind="daily", at="08:00"),
            steps=[
                Step(type="analytics.query", params={"question": "who wants Palm Jumeirah"}),
                Step(type="followups.schedule"),
                Step(type="leads.select", params={"band": "cold", "limit": 50}),
                Step(type="leads.reject", params={"max_score": 30, "stale_hours": 336}),
            ],
        ),
        actor="u1",
    )
    run = await routines.run_routine(WS, routine["id"], trigger="manual", actor="u1")
    assert run["status"] == "success", run
    s0, s1, _s2, s3 = run["steps"]
    assert s0["summary"]["metric"] == "leads_for_area" and s0["summary"]["selected"] == 2
    assert s1["summary"]["scheduled"] == 1 and s1["summary"]["broker_owned"] == 1  # hot leads are called, not drip-messaged
    assert s3["summary"]["closed"] == 1 and s3["summary"]["protected"] == 0
    cold = next(lead for lead in await get_lead_repository(WS).list_all(limit=500) if lead["first_name"] == "Cold")
    assert cold["stage"] == "lost"
    pending = await table("followups", WS).select(status="pending")
    assert {p["lead_id"] for p in pending} and all(p["lead_id"] != cold["id"] for p in pending)


@pytest.mark.asyncio
async def test_listings_refresh_expires_stale_portal_listings_only():
    props = table("properties", WS)
    await props.insert({"id": "p_old", "title": "Old", "source": "property_finder", "status": "active", "updated_at": _ago(24 * 30), "price_aed": 1_000_000})
    await props.insert({"id": "p_manual", "title": "Manual", "source": "manual", "status": "active", "updated_at": _ago(24 * 30), "price_aed": 1_000_000})
    await props.insert({"id": "p_new", "title": "New", "source": "bayut", "status": "active", "updated_at": _ago(2), "price_aed": 900_000, "previous_price_aed": 1_000_000})
    routine = await routines.create_routine(WS, RoutineIn(name="refresh", schedule=Schedule(kind="daily", at="23:00"), steps=[Step(type="listings.refresh", params={"stale_days": 14})]), actor="u1")
    run = await routines.run_routine(WS, routine["id"])
    summary = run["steps"][0]["summary"]
    assert summary["expired"] == 1 and summary["price_changes"] == 1
    assert (await props.get(id="p_old"))["status"] == "expired"
    assert (await props.get(id="p_manual"))["status"] == "active"


# ---------------------------------------------------------------- voice notes


def test_voice_notes_is_an_independent_connector():
    spec = get_provider("voice_notes")
    assert spec and spec.capabilities == ("send_voice_note",)
    assert "send_message" not in spec.capabilities
    assert get_provider("whatsapp") and "send_voice_note" not in get_provider("whatsapp").capabilities
    assert routines.STEP_TYPES["voice.send_note"]["capability"] == "send_voice_note"


@pytest.mark.asyncio
async def test_voice_note_fails_without_tts_and_never_sends_text(monkeypatch):
    from app.services import voice_service

    async def no_tts(self, text, language="en"):
        return None

    monkeypatch.setattr(voice_service.VoiceService, "text_to_speech", no_tts)
    calls: list[str] = []
    _mock_http(lambda request: (calls.append(request.url.path), httpx.Response(200, json={"id": "m"}))[1])

    conn = await connections.create_connection(WS, ConnectionIn(provider="voice_notes", config={"phone_number_id": "123", "access_token": "tok"}), actor="u1")
    row = await connections.get_connection(WS, conn["id"])
    out = await connections.execute_action(WS, row, "send_voice_note", {"to": "+971500000001", "text": "Hi, this is Amina from Palm Realty", "language": "en"})
    assert out["ok"] is False and "TTS" in out["error"]
    assert calls == []  # no WhatsApp text/media call was made

    out = await connections.execute_action(WS, row, "send_message", {"to": "+971500000001", "text": "x"})
    assert out["ok"] is False and "cannot send_message" in out["error"]


@pytest.mark.asyncio
async def test_voice_note_uploads_audio_and_sends_whatsapp_audio_message(monkeypatch):
    from app.services import voice_service

    async def fake_tts(self, text, language="en"):
        return b"RIFF....fake-audio"

    monkeypatch.setattr(voice_service.VoiceService, "text_to_speech", fake_tts)
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/media"):
            seen.append(("media", request.headers.get("content-type", "")))
            return httpx.Response(200, json={"id": "media_1"})
        if request.url.path.endswith("/messages"):
            payload = json.loads(request.content)
            seen.append(("message", payload["type"]))
            assert payload["audio"]["id"] == "media_1" and "text" not in payload
            return httpx.Response(200, json={"messages": [{"id": "wamid.1"}]})
        return httpx.Response(404)

    _mock_http(handler)
    conn = await connections.create_connection(WS, ConnectionIn(provider="voice_notes", config={"phone_number_id": "123", "access_token": "tok"}), actor="u1")
    row = await connections.get_connection(WS, conn["id"])
    out = await connections.execute_action(WS, row, "send_voice_note", {"to": "+971500000001", "text": "Hello from Palm Realty", "language": "en"})
    assert out["ok"], out
    assert [s[0] for s in seen] == ["media", "message"] and seen[1][1] == "audio"
    assert "multipart/form-data" in seen[0][1]


@pytest.mark.asyncio
async def test_voice_send_note_routine_step_reports_failures_without_text_fallback(monkeypatch):
    from app.services import voice_service

    async def no_tts(self, text, language="en"):
        return None

    monkeypatch.setattr(voice_service.VoiceService, "text_to_speech", no_tts)
    _mock_http(lambda request: httpx.Response(200, json={"id": "m"}))
    repo = get_lead_repository(WS)
    await repo.create({"first_name": "Warm", "phone": "+971500000021", "source": "vn", "status": "new", "stage": "qualified", "score": 50, "band": "warm", "language": "en"})
    voice = await connections.create_connection(WS, ConnectionIn(provider="voice_notes", config={"phone_number_id": "123", "access_token": "tok"}), actor="u1")
    routine = await routines.create_routine(
        WS,
        RoutineIn(name="vn", schedule=Schedule(kind="daily", at="16:00"), steps=[Step(type="leads.select", params={"source": "vn"}), Step(type="voice.send_note", connection_id=voice["id"], params={"template": "Hi {first_name}, Amina here."})]),
        actor="u1",
    )
    run = await routines.run_routine(WS, routine["id"])
    step = run["steps"][1]
    assert step["status"] == "failed"
    assert step["summary"]["text_fallback"] is False and step["summary"]["failed"] == 1
