"""Lead message API, conversation history API, and WhatsApp inbound webhook."""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.modules.llm import gateway as llm_gateway
from app.modules.store import reset_memory, table
from app.services.whatsapp import get_outbox

client = TestClient(app, raise_server_exceptions=False)
WS = get_settings().WORKSPACE_ID


@pytest.fixture(autouse=True)
def _clean():
    reset_memory()
    llm_gateway.reset_gateway()
    get_outbox().clear()
    yield
    reset_memory()
    llm_gateway.reset_gateway()


def _create_lead() -> str:
    response = client.post(
        "/api/v1/leads/ingest",
        json={"source": "crm", "first_name": "Api", "last_name": "Buyer", "phone": "+971501112233"},
    )
    assert response.status_code == 200, response.text
    return response.json()["lead_id"]


def test_message_endpoint_runs_engine_and_is_idempotent():
    lead_id = _create_lead()

    first = client.post(
        f"/api/v1/leads/{lead_id}/message",
        json={"text": "2 bed apartment in dubai marina, 2.5m to buy", "idempotency_key": "abc"},
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["response"] and body["move"] == "suggest" and body["matched_properties"]
    assert body["stage"] in {"suggesting", "discovering"}

    again = client.post(
        f"/api/v1/leads/{lead_id}/message",
        json={"text": "2 bed apartment in dubai marina, 2.5m to buy", "idempotency_key": "abc"},
    )
    assert again.json()["response"] == body["response"]

    history = client.get(f"/api/v1/leads/{lead_id}/conversation")
    assert history.status_code == 200
    assert len(history.json()["messages"]) == 2
    assert history.json()["state"]["turn"] == 1


def test_message_endpoint_404_for_unknown_lead():
    response = client.post("/api/v1/leads/does-not-exist/message", json={"text": "hi"})
    assert response.status_code == 404


def _signed(payload: dict) -> tuple[bytes, dict]:
    body = json.dumps(payload).encode()
    secret = get_settings().META_APP_SECRET.encode()
    sig = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    return body, {"X-Hub-Signature-256": sig, "Content-Type": "application/json"}


def _wa_payload(mid: str, text: str, phone: str = "971509998877") -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "111"},
                            "contacts": [{"wa_id": phone, "profile": {"name": "Sara"}}],
                            "messages": [
                                {"id": mid, "from": phone, "type": "text", "text": {"body": text}, "timestamp": "1"}
                            ],
                        }
                    }
                ]
            }
        ],
    }


def test_whatsapp_webhook_rejects_bad_signature():
    settings = get_settings()
    original = settings.META_APP_SECRET
    settings.META_APP_SECRET = "s3cret"
    try:
        response = client.post(
            "/api/v1/webhooks/whatsapp",
            content=json.dumps(_wa_payload("m1", "hi")),
            headers={"X-Hub-Signature-256": "sha256=bad", "Content-Type": "application/json"},
        )
    finally:
        settings.META_APP_SECRET = original
    assert response.status_code == 401


def test_whatsapp_webhook_creates_lead_replies_and_dedupes():
    settings = get_settings()
    original = settings.META_APP_SECRET
    settings.META_APP_SECRET = "s3cret"
    try:
        body, headers = _signed(_wa_payload("wamid.1", "hello, looking for a villa in dubai hills"))
        first = client.post("/api/v1/webhooks/whatsapp", content=body, headers=headers)
        assert first.status_code == 200, first.text
        assert first.json()["stored"] == 1 and first.json()["replied"] == 1

        again = client.post("/api/v1/webhooks/whatsapp", content=body, headers=headers)
        assert again.json()["stored"] == 0 and again.json()["skipped"] == 1
    finally:
        settings.META_APP_SECRET = original

    outbox = get_outbox().list()
    assert len(outbox) == 1
    assert outbox[0]["to"].endswith("971509998877")

    leads_response = client.get("/api/v1/leads/")
    assert leads_response.status_code == 200, leads_response.text
    leads = leads_response.json()
    wa_leads = [lead for lead in leads if lead.get("phone") == "+971509998877"]
    assert len(wa_leads) == 1 and wa_leads[0]["source"] == "whatsapp"
    assert wa_leads[0]["first_name"] == "Sara"


@pytest.mark.asyncio
async def test_whatsapp_raw_event_is_marked_processed():
    from app.modules.channels.whatsapp_inbound import handle_payload

    result = await handle_payload(_wa_payload("wamid.2", "hi", phone="971501230000"))
    assert result.stored == 1
    event = await table("webhook_events", WS).get(provider="whatsapp", provider_event_id="wamid.2")
    assert event and event["status"] == "processed"
