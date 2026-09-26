"""Standalone UAE CRM (realestate-crm) as source of truth: cursor pulls, webhooks, PATCH write-back."""
from __future__ import annotations

import json
import socket as _socket
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import get_lead_repository
from app.main import app
from app.modules.cowork import connections, realestate_crm
from app.modules.cowork.connections import ConnectionIn, sign
from app.modules.ingestion import events, writeback
from app.modules.store import reset_memory, table

client = TestClient(app, raise_server_exceptions=False)
WS = get_settings().WORKSPACE_ID
CFG = {"base_url": "https://crm.example.com", "api_key": "crm_live_secret123"}


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


def _mock(handler):
    transport = httpx.MockTransport(handler)
    connections.set_client_factory(lambda: httpx.AsyncClient(transport=transport))
    _socket.getaddrinfo = lambda *a, **k: [(2, 1, 6, "", ("104.18.0.1", 443))]
    return httpx.AsyncClient(transport=transport)


def _crm_lead(i: int, **over):
    base = {
        "id": f"crm-{i}",
        "name": f"Lead {i}",
        "first_name": "Lead",
        "last_name": str(i),
        "phone": f"+9715012345{i:02d}",
        "email": None,
        "source": "property_finder",
        "purpose": "buy",
        "property_type": "apartment",
        "bedrooms": 2,
        "areas": ["Dubai Marina", "JBR"],
        "budget_min_aed": 1500000,
        "budget_max_aed": 2500000,
        "timeline": "1_3_months",
        "payment_method": "mortgage",
        "stage": "qualifying",
        "assigned_agent_id": "agent-1",
        "created_at": "2026-09-01T10:00:00Z",
        "updated_at": f"2026-09-20T10:00:{i:02d}Z",
    }
    return {**base, **over}


# ---------------------------------------------------------------- adapter units


def test_normalize_maps_crm_fields_and_skips_deleted_or_opted_out():
    recs = realestate_crm.normalize({"data": [_crm_lead(1), _crm_lead(2, deleted_at="2026-09-21T00:00:00Z"), _crm_lead(3, do_not_contact=True), {"junk": True}]})
    assert [r.external_id for r in recs] == ["crm-1"]
    p = recs[0].payload
    assert p["area"] == "Dubai Marina, JBR" and p["payment"] == "mortgage" and p["crm_assigned_agent_id"] == "agent-1"
    assert recs[0].source_hint == "realestate_crm"


def test_normalize_ignores_non_lead_events_and_own_echo():
    lead = _crm_lead(1)
    assert realestate_crm.normalize({"event": "viewing.created", "lead": lead}) == []
    assert realestate_crm.normalize({"event": "lead.updated", "origin": "ai_agent", "lead": lead}) == []
    assert len(realestate_crm.normalize({"event": "lead.created", "lead": lead})) == 1


def test_write_back_body_only_sends_fields_the_crm_accepts():
    body = realestate_crm.write_back_body(
        {"score": 83.6, "band": "HOT", "stage": "qualified", "purpose": "flip", "budget_max_aed": 2_000_000, "area_preference": ["Palm Jumeirah", ""], "phone": "+971500000000", "score_reasons": ["budget fits", "2 replies"], "status": "x"}
    )
    assert body == {"score": 84, "band": "hot", "stage": "qualified", "budget_max_aed": 2_000_000, "area_preference": ["Palm Jumeirah"], "summary": "budget fits; 2 replies"}
    assert "phone" not in body and "purpose" not in body


# ---------------------------------------------------------------- pull


@pytest.mark.asyncio
async def test_pull_follows_cursor_keeps_watermark_and_syncs_stages():
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer crm_live_secret123"
        q = {k: v[0] for k, v in parse_qs(urlparse(str(request.url)).query).items()}
        calls.append(q)
        if q.get("cursor") == "c2":
            return httpx.Response(200, json={"data": [_crm_lead(3, stage="viewing_booked")], "paging": {"next": None}})
        return httpx.Response(200, json={"data": [_crm_lead(1), _crm_lead(2)], "paging": {"next": "c2"}})

    _mock(handler)
    row = await connections.create_connection(WS, ConnectionIn(provider="realestate_crm", config=CFG), actor="u1")
    raw = await connections.get_connection(WS, row["id"])
    out = await connections.execute_action(WS, raw, "pull_leads", {})
    assert out["fetched"] == 3 and out["published"] == 3 and out["cursor"] is None
    assert out["updated_after"] == "2026-09-20T10:00:03Z"
    assert calls[0] == {"limit": "200"} and calls[1] == {"cursor": "c2", "limit": "200"}

    saved = await connections.get_connection(WS, row["id"])
    assert saved["sync_state"]["updated_after"] == "2026-09-20T10:00:03Z" and saved["sync_state"]["last_pull_at"]

    # the CRM's stage wins on the platform lead
    repo = get_lead_repository(WS)
    leads = {lead["crm_external_id"]: lead for lead in [await repo.get_by_id(i) for i in out["lead_ids"]]}
    assert leads["crm-3"]["stage"] == "viewing_booked" and leads["crm-1"]["stage"] == "qualifying"
    assert out["stage_synced"] >= 1

    # next tick resumes from the watermark
    calls.clear()
    await connections.execute_action(WS, saved, "pull_leads", {})
    assert calls[0] == {"updated_after": "2026-09-20T10:00:03Z", "limit": "200"}


@pytest.mark.asyncio
async def test_partial_walk_keeps_cursor_and_does_not_advance_watermark():
    async def http(method, url, *, headers, body=None):
        n = int(parse_qs(urlparse(url).query).get("cursor", ["c0"])[0][1:])
        return httpx.Response(200, json={"data": [_crm_lead(n)], "paging": {"next": f"c{n + 1}"}})

    items, state = await realestate_crm.fetch_changed_leads(http, CFG, {"updated_after": "2026-01-01T00:00:00Z"}, max_pages=3)
    assert len(items) == 3 and state["cursor"] == "c3" and state["updated_after"] == "2026-01-01T00:00:00Z"


@pytest.mark.asyncio
async def test_pull_failure_never_leaks_api_key():
    _mock(lambda request: httpx.Response(500, text="boom crm_live_secret123"))
    row = await connections.create_connection(WS, ConnectionIn(provider="realestate_crm", config=CFG), actor="u1")
    out = await connections.execute_action(WS, await connections.get_connection(WS, row["id"]), "pull_leads", {})
    assert out["ok"] is False and "crm_live_secret123" not in json.dumps(out)


# ---------------------------------------------------------------- webhook


def test_crm_webhook_lands_lead_events_only_with_valid_signature():
    created = client.post("/api/v1/cowork/connections", json={"provider": "realestate_crm", "config": CFG}).json()
    reveal = client.get(f"/api/v1/cowork/connections/{created['id']}/webhook").json()
    secret, path = reveal["secret"], reveal["url"].split("localhost:8000", 1)[1]
    body = json.dumps({"id": "d1", "event": "lead.created", "created_at": "2026-09-20T10:00:00Z", "lead": _crm_lead(9)}, separators=(",", ":")).encode()
    hdrs = {"content-type": "application/json", "X-Event": "lead.created", "X-Delivery-Id": "d1"}

    assert client.post(path, content=body, headers={**hdrs, "X-Signature-256": "sha256=00"}).status_code == 401
    ok = client.post(path, content=body, headers={**hdrs, "X-Signature-256": sign(secret, body)})
    assert ok.status_code == 200 and ok.json()["landed"] == 1

    other = json.dumps({"id": "d2", "event": "viewing.created", "lead": _crm_lead(9), "viewing": {"id": "v1"}}).encode()
    res = client.post(path, content=other, headers={**hdrs, "X-Signature-256": sign(secret, other)})
    assert res.status_code == 200 and res.json()["landed"] == 0


# ---------------------------------------------------------------- write-back


@pytest.mark.asyncio
async def test_scored_lead_is_patched_back_to_crm_and_echo_does_not_loop():
    patches: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH":
            assert request.headers["authorization"] == "Bearer crm_live_secret123"
            patches.append((request.url.path, json.loads(request.content)))
            return httpx.Response(200, json={"changed": ["ai_score"]})
        return httpx.Response(200, json={"data": [_crm_lead(1)], "paging": {"next": None}})

    http = _mock(handler)
    row = await connections.create_connection(WS, ConnectionIn(provider="realestate_crm", config=CFG), actor="u1")
    out = await connections.execute_action(WS, await connections.get_connection(WS, row["id"]), "pull_leads", {})
    lead_id = out["lead_ids"][0]
    await get_lead_repository(WS).update(lead_id, {"score": 77, "band": "hot", "stage": "qualified"})
    await events.emit(lead_id, "lead.scored", {"score": 77}, workspace_id=WS)

    assert await writeback.run_writeback(WS, client=http) >= 1
    assert patches and patches[-1][0] == "/v1/leads/crm-1"
    assert patches[-1][1]["score"] == 77 and patches[-1][1]["band"] == "hot" and patches[-1][1]["stage"] == "qualified"
    assert "phone" not in patches[-1][1]

    # the CRM echoes our write as lead.updated with nothing changed on our side → no second PATCH
    n = len(patches)
    await events.emit(lead_id, "lead.updated", {"changed_fields": [], "source": "crm"}, workspace_id=WS)
    await writeback.run_writeback(WS, client=http)
    assert len(patches) == n


@pytest.mark.asyncio
async def test_push_lead_upserts_new_and_only_patches_known():
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.method == "POST":
            return httpx.Response(201, json={"lead": _crm_lead(1, id="crm-new"), "created": True})
        return httpx.Response(200, json={})

    _mock(handler)
    row = await connections.create_connection(WS, ConnectionIn(provider="realestate_crm", config=CFG), actor="u1")
    raw = await connections.get_connection(WS, row["id"])
    out = await connections.execute_action(WS, raw, "push_lead", {"lead": {"id": "L1", "first_name": "Omar", "phone": "+971501112233", "score": 61, "band": "warm"}})
    assert out["ok"] and out["crm_lead_id"] == "crm-new"
    assert seen[0] == ("POST", "/v1/leads") and seen[1] == ("PATCH", "/v1/leads/crm-new")

    seen.clear()
    out = await connections.execute_action(WS, raw, "push_lead", {"lead": {"id": "L2", "crm_external_id": "crm-7", "score": 40}})
    assert out["crm_lead_id"] == "crm-7" and seen == [("PATCH", "/v1/leads/crm-7")]


@pytest.mark.asyncio
async def test_connection_test_calls_v1_me():
    paths = []
    _mock(lambda r: (paths.append(r.url.path), httpx.Response(200, json={"agency": {"id": "a"}}))[1])
    row = await connections.create_connection(WS, ConnectionIn(provider="realestate_crm", config=CFG), actor=None)
    out = await connections.test_connection(WS, row["id"])
    assert out["status"] == "ok" and paths == ["/v1/me"]
    assert await table("cowork_connections", WS).get(id=row["id"])
