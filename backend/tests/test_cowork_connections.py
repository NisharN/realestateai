"""Co-work v2: provider catalog, connections (redaction, tests, webhooks) and routines."""
from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import get_lead_repository
from app.main import app
from app.modules.cowork import connections, routines
from app.modules.cowork.connections import ConnectionIn, ConnectionPatch, sign
from app.modules.cowork.providers import PROVIDERS, get_provider
from app.modules.cowork.routines import RoutineIn, RoutinePatch, Schedule, Step
from app.modules.store import reset_memory, table

client = TestClient(app, raise_server_exceptions=False)
WS = get_settings().WORKSPACE_ID


@pytest.fixture(autouse=True)
def _clean():
    reset_memory()
    connections.set_client_factory(None)
    yield
    reset_memory()
    connections.set_client_factory(None)


def _mock_http(handler):
    transport = httpx.MockTransport(handler)
    connections.set_client_factory(lambda: httpx.AsyncClient(transport=transport))


# ---------------------------------------------------------------- catalog


def test_provider_catalog_covers_researched_connectors():
    ids = {p.id for p in PROVIDERS}
    assert {"realestate_crm", "propspace", "pixxi", "bitrix24", "hubspot", "zoho_crm", "property_finder", "bayut", "dubizzle", "whatsapp", "gmail", "google_calendar", "slack", "llm"} <= ids
    # feed-only portals must not claim a lead API; Property Finder must carry its certification caveat
    assert "pull_leads" not in get_provider("bayut").capabilities
    assert "pull_leads" not in get_provider("dubizzle").capabilities
    assert get_provider("property_finder").certification
    for p in PROVIDERS:
        assert p.to_public()["fields"] is not None
        if p.inbound_webhook:
            assert "receive_leads" in p.capabilities or "receive_message" in p.capabilities


# ---------------------------------------------------------------- connections


@pytest.mark.asyncio
async def test_create_connection_redacts_secrets_and_validates_keys():
    row = await connections.create_connection(WS, ConnectionIn(provider="propspace", config={"base_url": "https://api.propspace.com", "api_key": "sk-live-123"}), actor="u1")
    assert row["config"]["api_key"] == connections.REDACTED
    assert row["config"]["base_url"] == "https://api.propspace.com"
    assert row["has_webhook_secret"] is False and row["health"] == "untested"
    assert "webhook_secret" not in row
    stored = await connections.get_connection(WS, row["id"])
    assert stored["config"]["api_key"] == "sk-live-123"

    with pytest.raises(ValueError):
        await connections.create_connection(WS, ConnectionIn(provider="propspace", config={"base_url": "https://x.y", "api_key": "k", "evil": "1"}), actor=None)
    with pytest.raises(ValueError):
        await connections.create_connection(WS, ConnectionIn(provider="nope", config={}), actor=None)
    with pytest.raises(ValueError):
        await connections.create_connection(WS, ConnectionIn(provider="propspace", config={"base_url": "http://127.0.0.1/", "api_key": "k"}), actor=None)


@pytest.mark.asyncio
async def test_patch_keeps_secret_when_redacted_placeholder_is_sent_back():
    row = await connections.create_connection(WS, ConnectionIn(provider="whatsapp", config={"phone_number_id": "1", "access_token": "tok-1"}), actor=None)
    patched = await connections.patch_connection(WS, row["id"], ConnectionPatch(config={"phone_number_id": "2", "access_token": connections.REDACTED}))
    stored = await connections.get_connection(WS, row["id"])
    assert stored["config"] == {"phone_number_id": "2", "access_token": "tok-1"}
    assert patched["config"]["access_token"] == connections.REDACTED

    old_secret = stored["webhook_secret"]
    await connections.patch_connection(WS, row["id"], ConnectionPatch(rotate_webhook_secret=True))
    assert (await connections.get_connection(WS, row["id"]))["webhook_secret"] != old_secret

    paused = await connections.patch_connection(WS, row["id"], ConnectionPatch(enabled=False))
    assert paused["health"] == "paused"


@pytest.mark.asyncio
async def test_unconfigured_connection_test_reports_missing_fields_without_network():
    row = await connections.create_connection(WS, ConnectionIn(provider="hubspot", config={}), actor=None)
    out = await connections.test_connection(WS, row["id"])
    assert out["status"] == "failed" and "missing" in out["detail"].lower()
    assert (await connections.get_connection(WS, row["id"]))["last_test_status"] == "failed"


@pytest.mark.asyncio
async def test_http_connection_test_uses_bearer_and_never_leaks_token():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["host"] = request.headers.get("host")
        return httpx.Response(401, json={"message": "bad token sk-live-123"})

    _mock_http(handler)
    row = await connections.create_connection(WS, ConnectionIn(provider="propspace", config={"base_url": "https://api.propspace.com", "api_key": "sk-live-123"}), actor=None)
    out = await connections.test_connection(WS, row["id"])
    assert seen["auth"] == "Bearer sk-live-123" and seen["host"] == "api.propspace.com"  # DNS-pinned URL keeps Host
    assert out["status"] == "failed"
    assert "sk-live-123" not in json.dumps(out)


@pytest.mark.asyncio
async def test_feed_connection_test_counts_listings():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<list><property><id>1</id></property><property><id>2</id></property></list>", headers={"content-type": "application/xml"})

    _mock_http(handler)
    row = await connections.create_connection(WS, ConnectionIn(provider="bayut", config={"feed_url": "https://agency.ae/feeds/bayut.xml"}), actor=None)
    out = await connections.test_connection(WS, row["id"])
    assert out["status"] == "ok" and "2" in out["detail"]


@pytest.mark.asyncio
async def test_llm_connection_test_reports_provider_chain_without_credentials():
    row = await connections.create_connection(WS, ConnectionIn(provider="llm", config={}), actor=None)
    out = await connections.test_connection(WS, row["id"])
    assert out["status"] in ("ok", "failed", "skipped") and out["detail"]


# ---------------------------------------------------------------- webhooks


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["property_finder", "bayut", "dubizzle", "realestate_crm", "whatsapp", "portal_webhook"])
async def test_webhook_dry_run_for_every_inbound_provider(provider):
    row = await connections.create_connection(WS, ConnectionIn(provider=provider, config={}), actor=None)
    out = await connections.test_webhook(WS, row["id"])
    assert out["status"] == "ok", out
    assert out["count"] >= 1 and out["url"].endswith(f"/api/v1/cowork/webhooks/{row['id']}?workspace_id={WS}")
    assert (await connections.get_connection(WS, row["id"]))["last_test_status"] == "ok"


def test_inbound_webhook_end_to_end_lands_raw_records():
    created = client.post("/api/v1/cowork/connections", json={"provider": "property_finder", "config": {}}).json()
    reveal = client.get(f"/api/v1/cowork/connections/{created['id']}/webhook").json()
    secret, url = reveal["secret"], reveal["url"]
    path = url.split("localhost:8000", 1)[1]
    body = json.dumps({"leads": [{"id": "pf-1", "name": "Sara", "phone": "+971501234567", "listing_reference": "PF-77", "message": "Is it still available?"}]}).encode()

    bad = client.post(path, content=body, headers={"X-Signature-256": "sha256=deadbeef", "content-type": "application/json"})
    assert bad.status_code == 401
    assert client.post(path, content=body, headers={"content-type": "application/json"}).status_code == 401

    ok = client.post(path, content=body, headers={"X-Signature-256": sign(secret, body), "content-type": "application/json"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["landed"] == 1

    dup = client.post(path, content=body, headers={"X-Hub-Signature-256": sign(secret, body), "content-type": "application/json"})
    assert dup.json()["duplicates"] == 1

    listed = client.get("/api/v1/cowork/connections").json()["connections"][0]
    assert listed["received_total"] == 1 and listed["last_activity_at"]

    client.patch(f"/api/v1/cowork/connections/{created['id']}", json={"enabled": False})
    assert client.post(path, content=body, headers={"X-Signature-256": sign(secret, body)}).status_code == 409
    assert client.post(f"/api/v1/cowork/webhooks/does-not-exist?workspace_id={WS}", content=body).status_code == 404


def test_connection_api_never_returns_raw_secrets():
    created = client.post("/api/v1/cowork/connections", json={"provider": "slack", "config": {"webhook_url": "https://hooks.slack.com/services/T/B/secret"}})
    assert created.status_code == 201
    dumped = json.dumps(created.json()) + json.dumps(client.get("/api/v1/cowork/connections").json()) + json.dumps(client.get("/api/v1/cowork/overview").json())
    assert "secret" not in dumped.replace("has_webhook_secret", "")
    assert client.get("/api/v1/cowork/connections/catalog").status_code == 200
    bad = client.post("/api/v1/cowork/connections", json={"provider": "slack", "config": {"webhook_url": "https://hooks.slack.com/x", "token": "t"}})
    assert bad.status_code == 422


# ---------------------------------------------------------------- routines


def test_next_run_daily_weekly_interval():
    from datetime import datetime, timezone

    at = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)  # 16:00 Dubai, Friday
    daily = routines.next_run({"kind": "daily", "at": "08:00", "tz": "Asia/Dubai"}, after=at)
    assert daily.startswith("2026-09-26T04:00")
    weekly = routines.next_run({"kind": "weekly", "weekday": 0, "at": "09:00", "tz": "Asia/Dubai"}, after=at)
    assert weekly.startswith("2026-09-28T05:00")
    interval = routines.next_run({"kind": "interval", "seconds": 900}, after=at)
    assert interval.startswith("2026-09-25T12:15")


@pytest.mark.asyncio
async def test_routine_validation_rejects_bad_steps():
    with pytest.raises(ValueError):
        await routines.create_routine(WS, RoutineIn(name="x", schedule=Schedule(kind="interval", seconds=3600), steps=[Step(type="job.run", params={"job_id": "run_routines"})]), actor=None)
    with pytest.raises(ValueError):
        await routines.create_routine(WS, RoutineIn(name="x", schedule=Schedule(kind="daily"), steps=[Step(type="leads.select")]), actor=None)
    slack = await connections.create_connection(WS, ConnectionIn(provider="slack", config={}), actor=None)
    with pytest.raises(ValueError):  # Slack cannot pull listings
        await routines.create_routine(WS, RoutineIn(name="x", schedule=Schedule(kind="daily", at="08:00"), steps=[Step(type="connector.pull_listings", connection_id=slack["id"])]), actor=None)


@pytest.mark.asyncio
async def test_routine_runs_data_llm_and_task_steps_deterministically():
    repo = get_lead_repository(WS)
    hot = await repo.create({"first_name": "Amina", "phone": "+971500000001", "source": "routine_test", "status": "new", "stage": "qualified", "score": 85, "band": "hot", "area_preference": "Dubai Marina"})
    await repo.create({"first_name": "Bob", "phone": "+971500000002", "source": "crm", "status": "new", "stage": "new", "score": 20, "band": "cold"})
    slack = await connections.create_connection(WS, ConnectionIn(provider="slack", config={}), actor=None)

    routine = await routines.create_routine(
        WS,
        RoutineIn(
            name="Morning digest",
            schedule=Schedule(kind="daily", at="08:00"),
            steps=[
                Step(type="leads.select", params={"band": "hot", "source": "routine_test"}),
                Step(type="llm.qualify"),
                Step(type="llm.draft_message", params={"language": "en"}),
                Step(type="llm.summarize"),
                Step(type="tasks.create", params={"title": "Call {first_name}", "due_in_hours": 2}),
                Step(type="connector.notify", connection_id=slack["id"]),
                Step(type="connector.send_message"),
            ],
        ),
        actor="u1",
    )
    assert routine["next_run_at"] and routine["schedule_label"] == "daily · 08:00 Asia/Dubai"

    run = await routines.run_routine(WS, routine["id"], trigger="manual", actor="u1")
    statuses = [s["status"] for s in run["steps"]]
    assert run["status"] == "success", run
    assert statuses == ["success", "simulated", "simulated", "simulated", "success", "simulated", "skipped"]
    assert run["steps"][0]["summary"]["selected"] == 1
    assert run["summary"]["digest"] and "1 lead" in run["summary"]["digest"]
    tasks = await table("cowork_tasks", WS).select()
    assert len(tasks) == 1 and tasks[0]["lead_id"] == hot["id"] and tasks[0]["title"].startswith("Call Amina")
    assert tasks[0]["routine_id"] == routine["id"]

    refreshed = await routines.get_routine(WS, routine["id"])
    assert refreshed["run_count"] == 1 and refreshed["last_status"] == "success"
    assert (await routines.list_runs(WS, routine_id=routine["id"]))[0]["id"] == run["id"]


@pytest.mark.asyncio
async def test_due_routines_and_beat_job_execute_and_reschedule():
    r = await routines.create_routine(WS, RoutineIn(name="tick", schedule=Schedule(kind="interval", seconds=600), steps=[Step(type="listings.validate")]), actor=None)
    assert await routines.due_routines(WS) == []
    await table(routines.TABLE, WS).update({"next_run_at": "2000-01-01T00:00:00+00:00"}, id=r["id"])
    assert [d["id"] for d in await routines.due_routines(WS)] == [r["id"]]
    counts = await routines.run_due(WS)
    assert counts == {"due": 1, "success": 1, "partial": 0, "failed": 0}
    assert (await routines.get_routine(WS, r["id"]))["next_run_at"] > "2026"

    paused = await routines.patch_routine(WS, r["id"], RoutinePatch(enabled=False))
    assert paused["next_run_at"] is None
    await table(routines.TABLE, WS).update({"next_run_at": "2000-01-01T00:00:00+00:00"}, id=r["id"])
    assert await routines.due_routines(WS) == []


@pytest.mark.asyncio
async def test_template_instantiation_binds_existing_connections():
    pf = await connections.create_connection(WS, ConnectionIn(provider="property_finder", config={}), actor=None)
    row = await routines.instantiate_template(WS, "daily_portal_sync", actor=None)
    assert row["enabled"] is False and row["template_id"] == "daily_portal_sync"
    assert row["steps"][0]["connection_id"] == pf["id"]
    assert row["steps"][3]["connection_id"] is None  # no Slack yet
    run = await routines.run_routine(WS, row["id"])
    assert run["steps"][0]["status"] == "simulated"  # PF not configured -> simulated, never claims a live pull
    assert run["steps"][3]["status"] == "skipped"
    with pytest.raises(LookupError):
        await routines.instantiate_template(WS, "nope", actor=None)


def test_routine_api_roundtrip_and_audit_feed():
    cat = client.get("/api/v1/cowork/routines/catalog").json()
    assert {t["id"] for t in cat["templates"]} >= {"daily_portal_sync", "portal_leads_to_crm", "stale_lead_reengage", "viewing_calendar", "weekly_performance"}
    assert all(j["id"] != "run_routines" for j in cat["jobs"])

    created = client.post("/api/v1/cowork/routines/from-template", json={"template_id": "crm_two_way_sync"})
    assert created.status_code == 201, created.text
    rid = created.json()["id"]
    assert client.patch(f"/api/v1/cowork/routines/{rid}", json={"enabled": True}).json()["next_run_at"]
    run = client.post(f"/api/v1/cowork/routines/{rid}/run")
    assert run.status_code == 200 and run.json()["status"] == "success"
    assert client.get(f"/api/v1/cowork/routines/runs?routine_id={rid}").json()[0]["id"] == run.json()["id"]
    feed = client.get("/api/v1/cowork/audit").json()
    assert any(f["kind"] == "routine" and f["subject"] == "CRM two-way sync" for f in feed)
    ov = client.get("/api/v1/cowork/overview").json()
    assert ov["routines"] == {"total": 1, "enabled": 1, "failing": 0}
    bad = client.post("/api/v1/cowork/routines", json={"name": "x", "schedule": {"kind": "daily"}, "steps": [{"type": "leads.select"}]})
    assert bad.status_code == 422
    assert client.delete(f"/api/v1/cowork/routines/{rid}").json()["deleted"] is True
    assert client.get("/api/v1/cowork/routines").json() == []
