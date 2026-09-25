"""Phase 7: PDPL export/erasure/consent/retention and fault-injection flags."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import mock_store
from app.config import get_settings
from app.main import app
from app.modules.conversation.engine import handle_turn
from app.modules.ingestion.connectors.base import land
from app.modules.ingestion.connectors.csv_upload import parse_csv
from app.modules.ingestion.models import RawRecord
from app.modules.ingestion.pipeline.processor import process_many, process_record
from app.modules.llm import gateway as llm_gateway
from app.modules.privacy.service import erase_lead, retention_purge
from app.modules.store import reset_memory, table
from app.services.voice_service import VoiceService

client = TestClient(app, raise_server_exceptions=False)
WS = get_settings().WORKSPACE_ID
CSV = b"Full Name,Mobile,Email,Budget,Area,Type,Beds,Purpose\nAhmed Ali,050 123 4567,ahmed@example.com,1.2m,Dubai Marina,Apartment,2,buy\n"


@pytest.fixture(autouse=True)
def _clean():
    seeded = dict(mock_store._leads)
    mock_store._leads.clear()
    reset_memory()
    yield
    reset_memory()
    mock_store._leads.clear()
    mock_store._leads.update(seeded)


async def _ingest_and_chat() -> str:
    result = await land(parse_csv(CSV, filename="l.csv"), connector_id="csv", workspace_id=WS)
    outcomes = await process_many(result.ids, workspace_id=WS)
    lead_id = outcomes[0].lead_id
    assert lead_id
    await handle_turn(lead_id, "2 bed in marina, 1.2m to buy", workspace_id=WS)
    return lead_id


# -- export / erase ---------------------------------------------------------

def test_export_bundles_everything_and_logs_request():
    lead_id = asyncio.run(_ingest_and_chat())
    r = client.get(f"/api/v1/admin/privacy/leads/{lead_id}/export")
    assert r.status_code == 200, r.text
    bundle = r.json()
    assert bundle["lead"]["id"] == lead_id and bundle["lead"]["phone"] == "+971501234567"
    assert bundle["messages"] and bundle["conversation_states"] and bundle["raw_lead_records"]
    reqs = client.get("/api/v1/admin/privacy/requests").json()["requests"]
    assert reqs[0]["kind"] == "export" and reqs[0]["status"] == "completed"
    assert client.get("/api/v1/admin/privacy/leads/nope/export").status_code == 404


def test_erase_scrubs_pii_deletes_linked_rows_and_suppresses_reimport():
    async def run():
        lead_id = await _ingest_and_chat()
        out = await erase_lead(lead_id, WS, requested_by="admin")
        assert out and out["deleted"]["messages"] >= 1
        lead = await mock_store.MockLeadRepository(WS).get_by_id(lead_id)
        assert lead["phone"] is None and lead["email"] is None and lead["status"] == "erased"
        assert lead["first_name"] == "[erased]" and lead.get("erased_at")
        assert await table("messages", WS).select(lead_id=lead_id) == []
        assert await table("conversation_states", WS).select(lead_id=lead_id) == []
        assert await table("raw_lead_records", WS).select(lead_id=lead_id) == []
        assert (await table("privacy_requests", WS).select())[0]["status"] == "completed"
        # a later import of the same person lands in review, not in the pipeline
        again = await land(
            [RawRecord(external_id="x1", payload={"phone": "+971 50 123 4567", "name": "Ahmed"})],
            connector_id="csv", workspace_id=WS,
        )
        assert (await process_record(again.ids[0], workspace_id=WS)).status == "review"
        return lead_id

    lead_id = asyncio.run(run())
    assert client.delete(f"/api/v1/admin/privacy/leads/{lead_id}").status_code == 200  # idempotent
    assert client.delete("/api/v1/admin/privacy/leads/nope").status_code == 404


def test_consent_ledger_appends_and_opt_out_sets_marker():
    lead_id = asyncio.run(_ingest_and_chat())
    r = client.post(f"/api/v1/admin/privacy/leads/{lead_id}/consent", json={"purpose": "marketing", "granted": True})
    assert r.status_code == 200 and r.json()["consent"]["marketing"] is True
    r = client.post(f"/api/v1/admin/privacy/leads/{lead_id}/consent", json={"purpose": "marketing", "granted": False})
    consent = r.json()["consent"]
    assert consent["marketing"] is False and len(consent["history"]) == 2
    lead = asyncio.run(mock_store.MockLeadRepository(WS).get_by_id(lead_id))
    assert lead["opted_out_at"] and lead["consent_marketing"] is False
    events = asyncio.run(table("lead_events", WS).select(lead_id=lead_id, type="consent.recorded"))
    assert len(events) == 2


def test_retention_purge_drops_old_raw_and_erases_idle_leads_only():
    async def run():
        lead_id = await _ingest_and_chat()
        raw = table("raw_lead_records", WS)
        old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
        await raw.insert({"connector_id": "csv", "status": "published", "payload": {}, "created_at": old})
        fresh_before = await raw.count()
        # nothing is old enough for the lead cutoff (730d) -> only raw purge
        first = await retention_purge(WS)
        assert first == {"raw_records_deleted": 1, "leads_erased": 0}
        assert await raw.count() == fresh_before - 1

        repo = mock_store.MockLeadRepository(WS)
        stale = (datetime.now(timezone.utc) - timedelta(days=800)).isoformat()
        mock_store._leads[lead_id].update({"updated_at": stale, "created_at": stale})
        assigned = await repo.create({"name": "Kept", "phone": "+971500000099", "assigned_broker": "b1", "status": "new"})
        mock_store._leads[assigned["id"]].update({"updated_at": stale, "created_at": stale})
        second = await retention_purge(WS)
        assert second["leads_erased"] == 1
        assert (await repo.get_by_id(lead_id))["status"] == "erased"
        assert (await repo.get_by_id(assigned["id"]))["status"] == "new"

    asyncio.run(run())


def test_privacy_endpoints_require_admin(monkeypatch):
    monkeypatch.setattr(get_settings(), "DEMO_ROLE", "agent")
    assert client.get("/api/v1/admin/privacy/requests").status_code == 403


# -- fault injection --------------------------------------------------------

@pytest.mark.asyncio
async def test_fault_llm_all_falls_back_to_deterministic_reply(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "FAULT_LLM_ALL", True)
    monkeypatch.setattr(llm_gateway, "_gateway", None)
    lead = await mock_store.MockLeadRepository(WS).create({"name": "F", "phone": "+971500000011", "status": "new", "score": 0})
    r = await handle_turn(lead["id"], "2 bed apartment in JVC, 1.2m to buy", workspace_id=WS)
    assert r.reply and "template:llm_unavailable" in r.fallbacks
    monkeypatch.setattr(llm_gateway, "_gateway", None)


@pytest.mark.asyncio
async def test_fault_stt_and_tts_return_fallback_signals(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "FAULT_STT", True)
    monkeypatch.setattr(settings, "FAULT_TTS", True)
    service = VoiceService()
    t = await service.transcribe(b"RIFF....", "en")
    assert t.text == "" and t.provider is None and "FAULT_STT" in (t.error or "")
    assert await service.text_to_speech("hello", "en") is None


@pytest.mark.asyncio
async def test_fault_db_slow_adds_latency(monkeypatch):
    monkeypatch.setattr(get_settings(), "FAULT_DB_SLOW_MS", 50)
    loop = asyncio.get_event_loop()
    started = loop.time()
    await table("lead_events", WS).count()
    assert loop.time() - started >= 0.045
