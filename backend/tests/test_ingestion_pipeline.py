"""Phase 1 ingestion: land → map → clean → validate → merge → publish, idempotency,
review queue, connectors, field maps, admin/data-health endpoints."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import mock_store
from app.config import get_settings
from app.database import get_lead_repository
from app.main import app
from app.modules.ingestion import events
from app.modules.ingestion.connectors.base import land
from app.modules.ingestion.connectors.crm_pull import poll_connector
from app.modules.ingestion.connectors.csv_upload import parse_csv
from app.modules.ingestion.connectors.webhook import SignatureError, WebhookConnector
from app.modules.ingestion.field_maps import suggest_field_map
from app.modules.ingestion.models import CanonicalLead, RawRecord
from app.modules.ingestion.pipeline.processor import (
    process_many,
    process_record,
    retry_errors,
)
from app.modules.ingestion.pipeline.stages import (
    clean_phone,
    clean_record,
    map_record,
    validate_record,
)
from app.modules.store import reset_memory, table

client = TestClient(app, raise_server_exceptions=False)
WS = get_settings().WORKSPACE_ID

CSV = (
    b"Full Name,Mobile,Email,Budget,Area,Type,Beds,Purpose\n"
    b"Ahmed Ali,050 123 4567,ahmed@example.com,1.2m,Dubai Marina,Apartment,2,buy\n"
    b"Sara Khan,+971 55 765 4321,sara@example.com,AED 120k per year,JVC,apartment,1,rent\n"
    b"No Contact,,,,Downtown,villa,,buy\n"
)


@pytest.fixture(autouse=True)
def _clean():
    seeded = dict(mock_store._leads)
    mock_store._leads.clear()
    reset_memory()
    yield
    reset_memory()
    mock_store._leads.clear()
    mock_store._leads.update(seeded)


async def _run_csv(body: bytes = CSV, connector_id: str = "conn-csv"):
    records = parse_csv(body, filename="leads.csv")
    result = await land(records, connector_id=connector_id, workspace_id=WS)
    outcomes = await process_many(result.ids, workspace_id=WS)
    return result, outcomes


# -- normalization ---------------------------------------------------------

@pytest.mark.parametrize("raw", ["050 123 4567", "+971501234567", "00971 50 1234567", "971501234567"])
def test_uae_phone_variants_normalize_identically(raw):
    assert clean_phone(raw) == "+971501234567"


def test_invalid_phone_is_dropped():
    assert clean_phone("12345") is None
    assert clean_phone("hello") is None


@pytest.mark.parametrize("raw", ["1.2m", "AED 1,200,000", "1.2 million dirhams"])
def test_budget_variants_normalize_to_same_value(raw):
    lead = clean_record(CanonicalLead(budget_raw=raw, purpose="buy"))
    assert lead.budget_max_aed == 1_200_000
    assert lead.budget_period is None or lead.budget_period == "total"


def test_yearly_rent_budget():
    lead = clean_record(CanonicalLead(budget_raw="120k per year"))
    assert lead.budget_max_aed == 120_000
    assert lead.budget_period == "year"


def test_area_resolves_via_gazetteer_and_email_lowercased():
    lead = clean_record(CanonicalLead(area_raw="dubai marina", email="  Ahmed@Example.COM "))
    assert "dubai_marina" in lead.community_ids
    assert lead.email == "ahmed@example.com"


# -- map / validate --------------------------------------------------------

def test_field_map_suggestions_from_headers_and_samples():
    headers = ["Full Name", "Mobile", "E-mail", "Budget", "Area", "Weird Column"]
    samples = {"Weird Column": ["a@b.com", "c@d.ae"]}
    suggestion = {s["source_field"]: s["target_field"] for s in suggest_field_map(headers, samples)}
    assert suggestion["Full Name"] == "full_name"
    assert suggestion["Mobile"] == "phone"
    assert suggestion["E-mail"] == "email"
    assert suggestion["Budget"] == "budget"
    assert suggestion["Area"] == "area"
    assert suggestion["Weird Column"] is None  # email already taken by a stronger header
    alone = {s["source_field"]: s["target_field"] for s in suggest_field_map(["Col A"], {"Col A": ["+971501234567", "0509876543"]})}
    assert alone["Col A"] == "phone"


def test_map_splits_full_name_and_keeps_unmapped_in_extra():
    lead = map_record({"Full Name": "Ahmed Ali Khan", "Mobile": "0501234567", "Zzq": "spring"}, None)
    assert (lead.first_name, lead.last_name) == ("Ahmed", "Ali Khan")
    assert lead.extra.get("Zzq") == "spring"


def test_validate_requires_contact_and_sane_budget():
    assert not validate_record(CanonicalLead(first_name="x")).ok
    assert validate_record(CanonicalLead(phone_e164="+971501234567")).ok
    bad = validate_record(CanonicalLead(phone_e164="+971501234567", purpose="buy", budget_max_aed=5_000))
    assert not bad.ok and any("budget" in r for r in bad.reasons)
    assert not validate_record(CanonicalLead(phone_e164="+971501234567"), suppression={"+971501234567"}).ok


# -- pipeline end to end ---------------------------------------------------

async def test_csv_upload_twice_creates_zero_new_leads():
    first, outcomes = await _run_csv()
    assert len(first.landed) == 3 and first.duplicates == 0
    leads = await get_lead_repository(WS).list_all()
    assert len(leads) == 2  # third row has no contact → review
    assert {o.status for o in outcomes} == {"published", "review"}

    second, outcomes2 = await _run_csv()
    assert second.landed == [] and second.duplicates == 3
    assert outcomes2 == []
    assert len(await get_lead_repository(WS).list_all()) == 2


async def test_csv_lead_fields_are_normalized_and_status_published():
    await _run_csv()
    lead = await get_lead_repository(WS).get_by_phone("+971501234567")
    assert lead is not None
    assert lead["first_name"] == "Ahmed" and lead["email"] == "ahmed@example.com"
    assert lead["budget_max_aed"] == 1_200_000 and lead["budget_max"] == 1_200_000
    assert "dubai_marina" in lead["community_ids"] and lead["area_preference"]
    assert lead["purpose"] == "buy" and lead["property_type"] == "apartment"
    raw = await table("raw_lead_records", WS).select(lead_id=lead["id"])
    assert raw and raw[0]["status"] == "published"


async def test_missing_contact_goes_to_review_not_dropped():
    await _run_csv()
    review = await table("review_queue", WS).select(status="open")
    assert len(review) == 1 and "contact" in review[0]["reason"]
    raw = await table("raw_lead_records", WS).get(id=review[0]["raw_record_id"])
    assert raw["status"] == "review"


async def test_same_person_from_two_sources_merges_into_one_lead_with_two_sources():
    await _run_csv()
    records = await WebhookConnector(None).handle_push({}, json.dumps({"id": "hs-1", "phone": "+971 50 123 4567", "email": None, "budget": "1.5m", "area": "JBR"}).encode())
    result = await land(records, connector_id="conn-hs", workspace_id=WS)
    (outcome,) = await process_many(result.ids, workspace_id=WS)
    assert outcome.status == "published" and outcome.created is False

    leads = await get_lead_repository(WS).list_all()
    assert len(leads) == 2
    lead = await get_lead_repository(WS).get_by_phone("+971501234567")
    assert lead["email"] == "ahmed@example.com"  # null never overwrites
    assert lead["budget_max_aed"] == 1_500_000
    sources = await table("lead_sources", WS).select(lead_id=lead["id"])
    assert len(sources) == 2
    types = [e["type"] for e in await table("lead_events", WS).select(lead_id=lead["id"])]
    assert [t for t in types if t != "lead.scored"] == ["lead.created", "lead.updated"]
    assert "lead.scored" in types  # every pull re-scores
    changes = await table("lead_change_log", WS).select(lead_id=lead["id"])
    assert any(c["field"] == "budget_max_aed" for c in changes)


async def test_email_match_when_phone_missing():
    await _run_csv()
    records = await WebhookConnector(None).handle_push({}, json.dumps({"email": "SARA@example.com", "message": "still looking"}).encode())
    result = await land(records, connector_id="conn-web", workspace_id=WS)
    (outcome,) = await process_many(result.ids, workspace_id=WS)
    assert outcome.created is False
    assert len(await get_lead_repository(WS).list_all()) == 2


async def test_buyer_confirmed_values_survive_crm_update():
    await _run_csv()
    repo = get_lead_repository(WS)
    lead = await repo.get_by_phone("+971501234567")
    await repo.update(lead["id"], {"budget_max_aed": 900_000, "buyer_confirmed_fields": ["budget_max_aed"]})
    records = await WebhookConnector(None).handle_push({}, json.dumps({"phone": "+971501234567", "budget": "2m"}).encode())
    result = await land(records, connector_id="conn-crm", workspace_id=WS)
    await process_many(result.ids, workspace_id=WS)
    assert (await repo.get_by_id(lead["id"]))["budget_max_aed"] == 900_000


async def test_pipeline_failure_retries_then_reviews(monkeypatch):
    calls = {"n": 0}

    def boom(*a, **k):
        calls["n"] += 1
        raise RuntimeError("enrich exploded")

    monkeypatch.setattr("app.modules.ingestion.pipeline.processor.clean_record", boom)
    records = parse_csv(CSV)
    result = await land(records[:1], connector_id="c", workspace_id=WS)
    outcome = await process_record(result.ids[0], workspace_id=WS)
    assert outcome.status == "error"
    row = await table("raw_lead_records", WS).get(id=result.ids[0])
    assert row["attempts"] == 1 and "exploded" in row["error"]

    for _ in range(4):
        await retry_errors(WS)
    row = await table("raw_lead_records", WS).get(id=result.ids[0])
    assert row["status"] == "review" and row["attempts"] == 5
    assert calls["n"] == 5


async def test_outbox_consumer_is_idempotent():
    await _run_csv()
    seen: list[str] = []

    async def handler(event):
        seen.append(event["id"])

    first = await events.consume(WS, "test", handler)
    assert first >= 2  # lead.created/updated plus lead.scored per pull
    assert await events.consume(WS, "test", handler) == 0
    assert len(seen) == first


# -- connectors ------------------------------------------------------------

def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def test_webhook_signature_required_when_secret_set():
    body = json.dumps({"phone": "+971501234567"}).encode()
    conn = WebhookConnector("s3cret")
    with pytest.raises(SignatureError):
        await conn.handle_push({"x-signature-256": "sha256=deadbeef"}, body)
    records = await conn.handle_push({"x-signature-256": _sign("s3cret", body)}, body)
    assert len(records) == 1


async def test_webhook_accepts_list_and_records_wrapper():
    conn = WebhookConnector(None)
    assert len(await conn.handle_push({}, json.dumps([{"a": 1}, {"a": 2}]).encode())) == 2
    assert len(await conn.handle_push({}, json.dumps({"records": [{"a": 1}]}).encode())) == 1


# -- HTTP surface ----------------------------------------------------------

def test_csv_upload_endpoint_and_admin_data_health():
    resp = client.post("/api/v1/ingest/csv", files={"file": ("leads.csv", CSV, "text/csv")})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["rows"] == 3 and body["published"] == 2 and body["review"] == 1
    assert any(s["target_field"] == "phone" for s in body["field_map_suggestions"])

    again = client.post("/api/v1/ingest/csv", files={"file": ("leads.csv", CSV, "text/csv")}, params={"connector_id": body["connector_id"]})
    assert again.status_code == 201 and again.json()["duplicates"] == 3 and again.json()["landed"] == 0

    health = client.get("/api/v1/admin/data-health").json()
    assert health["totals"]["published"] == 2 and health["totals"]["review"] == 1

    review = client.get("/api/v1/admin/review-queue").json()
    assert len(review) == 1
    fixed = client.post(f"/api/v1/admin/review-queue/{review[0]['id']}/resolve", json={"action": "retry", "fixed_payload": {"Mobile": "+971 52 000 0000"}})
    assert fixed.status_code == 200 and fixed.json()["status"] == "published"
    assert client.get("/api/v1/admin/review-queue").json() == []


def test_webhook_endpoint_rejects_bad_signature_and_lands_good_one():
    created = client.post("/api/v1/admin/connectors", json={"type": "webhook", "display_name": "Website"}).json()
    secret, cid = created["secret"], created["id"]
    body = json.dumps({"id": "w-1", "phone": "0501112222", "name": "Web Lead"}).encode()

    bad = client.post(f"/api/v1/ingest/webhook/{cid}?workspace_id={WS}", content=body, headers={"x-signature-256": "sha256=00"})
    assert bad.status_code == 401

    ok = client.post(f"/api/v1/ingest/webhook/{cid}?workspace_id={WS}", content=body, headers={"x-signature-256": _sign(secret, body)})
    assert ok.status_code == 200 and ok.json()["landed"] == 1
    dup = client.post(f"/api/v1/ingest/webhook/{cid}?workspace_id={WS}", content=body, headers={"x-signature-256": _sign(secret, body)})
    assert dup.json()["duplicates"] == 1

    rotated = client.patch(f"/api/v1/admin/connectors/{cid}", json={"rotate_secret": True}).json()
    assert rotated["secret"] != secret
    stale = client.post(f"/api/v1/ingest/webhook/{cid}?workspace_id={WS}", content=body, headers={"x-signature-256": _sign(secret, body)})
    assert stale.status_code == 401


def test_field_map_put_and_get():
    created = client.post("/api/v1/admin/connectors", json={"type": "csv_upload", "display_name": "Portal export"}).json()
    put = client.put(f"/api/v1/admin/connectors/{created['id']}/field-map", json={"mappings": [{"source_field": "Tel", "target_field": "phone"}, {"source_field": "Notes", "target_field": None}]})
    assert put.status_code == 200
    got = client.get(f"/api/v1/admin/connectors/{created['id']}/field-map").json()
    assert {m["source_field"]: m["target_field"] for m in got["approved"]} == {"Tel": "phone", "Notes": None}


# -- CRM pull connector -----------------------------------------------------

async def test_crm_pull_pages_lands_and_advances_cursor():
    pages = {
        None: {"data": {"items": [{"id": 1, "Name": "Ali Khan", "Mobile": "0501234567", "updated_at": "2026-01-01T00:00:00"}]}, "paging": {"next": "c2"}},
        "c2": {"data": {"items": [{"id": 2, "Name": "Sara Noor", "Mobile": "0507654321", "updated_at": "2026-01-02T00:00:00"}]}, "paging": {}},
    }
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.headers) | {"cursor": request.url.params.get("updated_after", "")})
        return httpx.Response(200, json=pages[request.url.params.get("updated_after") or None])

    created = client.post("/api/v1/admin/connectors", json={"type": "generic_crm", "credential": "tok", "config": {"url": "https://crm.test/leads", "records_path": "data.items", "next_cursor_path": "paging.next"}}).json()
    assert "secret" not in created and created["has_secret"] and created["mode"] == "pull"

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        first = await poll_connector(created["id"], workspace_id=WS, client=http)
        assert first["fetched"] == 2 and first["landed"] == 2 and first["cursor"] == "c2"
        assert seen[0]["authorization"] == "Bearer tok" and seen[1]["cursor"] == "c2"
        again = await poll_connector(created["id"], workspace_id=WS, client=http)
        assert again["landed"] == 0 and again["duplicates"] == 1  # resumes from cursor; page already landed

    outcomes = await process_many(first["raw_ids"], workspace_id=WS)
    assert [o.status for o in outcomes] == ["published", "published"]
    leads = await get_lead_repository(WS).list_all()
    assert {l["phone"] for l in leads} == {"+971501234567", "+971507654321"}
    assert {l["source"] for l in leads} == {"crm"} and {l["crm_external_id"] for l in leads} == {"1", "2"}


async def test_crm_pull_failure_records_run_and_pauses_after_five():
    created = client.post("/api/v1/admin/connectors", json={"type": "hubspot", "config": {"url": "https://crm.test/x"}}).json()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500))) as http:
        for _ in range(5):
            res = await poll_connector(created["id"], workspace_id=WS, client=http)
    assert "error" in res
    row = client.get(f"/api/v1/admin/connectors/{created['id']}").json()
    assert row["status"] == "paused" and row["consecutive_failures"] == 5


def test_crm_url_must_be_public_https():
    from app.modules.ingestion.connectors.crm_pull import validate_crm_url

    assert validate_crm_url("https://api.hubapi.com/crm/v3/objects/contacts")
    for bad in ("http://crm.example.com/x", "https://localhost/x", "https://10.0.0.5/x", "https://169.254.169.254/latest", "https://[::1]/x", "https://internal/x"):
        with pytest.raises(ValueError):
            validate_crm_url(bad)
    r = client.post("/api/v1/admin/connectors", json={"type": "generic_crm", "config": {"url": "http://127.0.0.1:8000/leads"}})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "invalid_crm_url"


async def test_crm_pull_changed_since_pages_until_exhausted_and_hides_token_in_errors():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        after = request.url.params.get("since")
        calls.append(after or "")
        if after == "2026-01-02":
            return httpx.Response(200, json=[])
        if after == "2026-01-01":
            return httpx.Response(200, json=[{"key": "b", "Mobile": "0502222222", "ts": "2026-01-02"}])
        return httpx.Response(200, json=[{"key": "a", "Mobile": "0501111111", "ts": "2026-01-01"}])

    created = client.post("/api/v1/admin/connectors", json={"type": "generic_crm", "credential": "supersecret", "config": {"url": "https://crm.test/leads", "cursor_param": "since", "cursor_field": "ts", "id_field": "key"}}).json()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        res = await poll_connector(created["id"], workspace_id=WS, client=http)
    assert res["landed"] == 2 and res["cursor"] == "2026-01-02" and calls == ["", "2026-01-01", "2026-01-02"]
    outcomes = await process_many(res["raw_ids"], workspace_id=WS)
    leads = await get_lead_repository(WS).list_all()
    assert {l["crm_external_id"] for l in leads if l.get("crm_external_id")} >= {"a", "b"} and all(o.status == "published" for o in outcomes)

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(401))) as http:
        res = await poll_connector(created["id"], workspace_id=WS, client=http)
    row = client.get(f"/api/v1/admin/connectors/{created['id']}").json()
    assert res["error"] == "CRM returned HTTP 401" and "supersecret" not in json.dumps(row)


async def test_stranded_landed_records_are_picked_up():
    from app.modules.ingestion.pipeline.processor import process_stranded

    result = await land([RawRecord(external_id="s1", payload={"Mobile": "0503333333", "Name": "Stranded"}, source_hint="csv")], connector_id=None, workspace_id=WS)
    assert len(result.ids) == 1
    assert await process_stranded(WS, older_than_seconds=600) == []  # too fresh
    outcomes = await process_stranded(WS, older_than_seconds=0)
    assert [o.status for o in outcomes] == ["published"]


def test_crm_url_dns_resolution_rejects_internal_addresses(monkeypatch):
    import socket as _socket

    from app.modules.ingestion.connectors.crm_pull import validate_crm_url

    monkeypatch.setattr(_socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("10.1.2.3", 443))])
    with pytest.raises(ValueError):
        validate_crm_url("https://crm.evil.example/x", resolve=True)
    monkeypatch.setattr(_socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("104.18.0.1", 443))])
    assert validate_crm_url("https://crm.good.example/x", resolve=True)


def test_connector_patch_validates_crm_url():
    created = client.post("/api/v1/admin/connectors", json={"type": "generic_crm", "config": {"url": "https://crm.test/leads"}}).json()
    r = client.patch(f"/api/v1/admin/connectors/{created['id']}", json={"config": {"url": "https://192.168.1.1/leads"}})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "invalid_crm_url"
    assert client.get(f"/api/v1/admin/connectors/{created['id']}").json()["config"]["url"] == "https://crm.test/leads"


# -- CRM write-back consumer -------------------------------------------------

async def test_crm_writeback_patches_crm_once_per_event():
    from app.modules.ingestion.writeback import run_writeback

    patches: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=[{"id": "crm-9", "Mobile": "0507777777", "Name": "Wb Lead"}])
        patches.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200, json={"ok": True})

    created = client.post("/api/v1/admin/connectors", json={"type": "generic_crm", "credential": "tok", "config": {"url": "https://crm.test/leads", "write_back_url": "https://crm.test/leads/{id}", "write_back_fields": ["score", "stage", "secret_col"]}}).json()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        res = await poll_connector(created["id"], workspace_id=WS, client=http)
        outcomes = await process_many(res["raw_ids"], workspace_id=WS)
        assert outcomes[0].status == "published"
        lead_id = outcomes[0].lead_id
        await table("lead_events", WS).insert({"lead_id": lead_id, "type": "lead.updated", "payload": {"by": "test"}})
        assert await run_writeback(WS, client=http) >= 1
        again = await run_writeback(WS, client=http)
    assert len(patches) == 1 and patches[0][0] == "https://crm.test/leads/crm-9"
    assert set(patches[0][1]) <= {"score", "stage"} and "secret_col" not in patches[0][1]
    assert again == 0  # offsets: redelivery is a no-op


async def test_crm_writeback_escapes_external_id_in_url():
    from app.modules.ingestion.connectors.crm_pull import CrmPullConnector

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={})

    connector = {"id": "c1", "type": "generic_crm", "config": {"url": "https://crm.test/leads", "write_back_url": "https://crm.test/leads/{id}"}}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await CrmPullConnector(connector, client=http).write_back({"crm_external_id": "../x?admin=1#f"}, {"score": 1})
    assert seen == ["https://crm.test/leads/..%2Fx%3Fadmin%3D1%23f"]

    connector["config"]["write_back_url"] = "https://{id}.crm.test/leads"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(ValueError):
            await CrmPullConnector(connector, client=http).write_back({"crm_external_id": "evil"}, {"score": 1})


async def test_crm_writeback_skips_leads_without_writeback_connector():
    from app.modules.ingestion.writeback import run_writeback

    lead = await get_lead_repository(WS).create({"name": "Manual", "phone": "+971501230000", "source": "website"})
    await table("lead_events", WS).insert({"lead_id": lead["id"], "type": "lead.updated", "payload": {}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500))) as http:
        assert await run_writeback(WS, client=http) == 1  # consumed, nothing sent, no error


async def test_crm_writeback_routes_each_crm_its_own_external_id():
    from app.modules.ingestion.writeback import run_writeback

    patches: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if request.method == "GET":
            ext = "a-1" if host == "crm-a.test" else "b-2"
            return httpx.Response(200, json=[{"id": ext, "Mobile": "0507777777", "Name": "Same Person"}])
        patches.append(str(request.url))
        return httpx.Response(200, json={})

    ids = []
    for host in ("crm-a.test", "crm-b.test"):
        cfg = {"url": f"https://{host}/leads", "write_back_url": f"https://{host}/leads/{{id}}"}
        ids.append(client.post("/api/v1/admin/connectors", json={"type": "generic_crm", "credential": "tok", "config": cfg}).json()["id"])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        lead_ids = set()
        for cid in ids:
            res = await poll_connector(cid, workspace_id=WS, client=http)
            lead_ids |= {o.lead_id for o in await process_many(res["raw_ids"], workspace_id=WS)}
        assert len(lead_ids) == 1  # merged on phone
        await table("lead_events", WS).insert({"lead_id": lead_ids.pop(), "type": "lead.scored", "payload": {}})
        await run_writeback(WS, client=http)
    assert set(patches) == {"https://crm-a.test/leads/a-1", "https://crm-b.test/leads/b-2"}


async def test_pending_events_are_not_capped_by_processed_prefix():
    lead = await get_lead_repository(WS).create({"name": "Many", "phone": "+971501239999", "source": "website"})
    seen: list[str] = []

    async def handler(event):
        seen.append(event["id"])

    for _ in range(450):
        await events.emit(lead["id"], "lead.updated", {}, workspace_id=WS)
    while await events.consume(WS, "t", handler, limit=100):
        pass
    await events.emit(lead["id"], "lead.updated", {"n": 451}, workspace_id=WS)
    assert await events.consume(WS, "t", handler, limit=100) == 1
    assert len(seen) == 451 and len(set(seen)) == 451


# -- PR #8 review regressions ----------------------------------------------

def test_field_map_invalid_target_keeps_approved_map():
    created = client.post("/api/v1/admin/connectors", json={"type": "csv_upload", "display_name": "Portal export"}).json()
    ok = client.put(f"/api/v1/admin/connectors/{created['id']}/field-map", json={"mappings": [{"source_field": "Tel", "target_field": "phone"}]})
    assert ok.status_code == 200
    bad = client.put(f"/api/v1/admin/connectors/{created['id']}/field-map", json={"mappings": [{"source_field": "Tel", "target_field": "not_a_field"}]})
    assert bad.status_code == 400
    got = client.get(f"/api/v1/admin/connectors/{created['id']}/field-map").json()
    assert {m["source_field"]: m["target_field"] for m in got["approved"]} == {"Tel": "phone"}


def test_webhook_without_stored_secret_is_rejected():
    created = client.post("/api/v1/admin/connectors", json={"type": "webhook", "display_name": "Website"}).json()
    asyncio.get_event_loop().run_until_complete(table("connectors", WS).update({"secret": None}, id=created["id"]))
    body = json.dumps({"id": "w-9", "phone": "0501112222"}).encode()
    resp = client.post(f"/api/v1/ingest/webhook/{created['id']}?workspace_id={WS}", content=body)
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "connector_unsigned"


def test_connector_config_credentials_are_redacted():
    created = client.post(
        "/api/v1/admin/connectors",
        json={"type": "generic_crm", "credential": "tok", "config": {"url": "https://crm.test/leads", "auth_header": "X-Api-Key", "extra_params": {"api_key": "plain-text-key"}, "webhook_token": "t0k"}},
    ).json()
    assert "secret" not in created
    assert created["config"]["extra_params"]["api_key"] == "[redacted]"
    assert created["config"]["webhook_token"] == "[redacted]"
    assert created["config"]["auth_header"] == "X-Api-Key" and created["config"]["url"] == "https://crm.test/leads"
    listed = client.get("/api/v1/admin/connectors").json()
    assert all(c["config"].get("webhook_token") in (None, "[redacted]") for c in listed)


def test_csv_upload_rejects_oversized_file_before_parsing():
    from app.api import ingest as ingest_api

    big = b"phone\n" + b"0501234567\n" * (ingest_api.MAX_CSV_BYTES // 11 + 10)
    resp = client.post("/api/v1/ingest/csv", files={"file": ("big.csv", big, "text/csv")})
    assert resp.status_code == 413


async def test_suppressed_phone_and_email_go_to_review():
    await table("suppression_list", WS).insert({"id": "s1", "phone": "+971501110000", "email": None, "reason": "opt_out", "created_at": "2026-01-01T00:00:00+00:00"})
    await table("suppression_list", WS).insert({"id": "s2", "phone": None, "email": "no@example.com", "reason": "opt_out", "created_at": "2026-01-01T00:00:00+00:00"})
    result = await land([RawRecord(external_id="p1", payload={"phone": "0501110000", "name": "Sup"}), RawRecord(external_id="e1", payload={"email": "NO@example.com", "name": "Sup2"})], connector_id="csv", workspace_id=WS)
    outcomes = [await process_record(rid, workspace_id=WS) for rid in result.ids]
    assert [o.status for o in outcomes] == ["review", "review"]
    assert await get_lead_repository(WS).list_all(limit=10) == []


async def test_opted_out_lead_is_not_enriched_by_reimport():
    lead = await get_lead_repository(WS).create({"phone": "+971502220000", "first_name": "Out", "source": "csv_upload", "opted_out_at": "2026-01-01T00:00:00+00:00"})
    result = await land([RawRecord(external_id="r1", payload={"phone": "0502220000", "name": "Out", "budget": "2M"})], connector_id="csv", workspace_id=WS)
    outcome = await process_record(result.ids[0], workspace_id=WS)
    assert outcome.status == "review" and "suppressed" in outcome.reasons
    assert (await get_lead_repository(WS).get_by_id(lead["id"])).get("budget_max_aed") is None


async def test_repeat_crm_update_does_not_duplicate_lead_sources():
    for i in range(2):
        result = await land([RawRecord(external_id="crm-7", payload={"id": "crm-7", "phone": "0503330000", "name": "Rep", "budget": f"{i + 1}M"})], connector_id="crm", workspace_id=WS)
        outcome = await process_record(result.ids[0], workspace_id=WS)
        assert outcome.status == "published"
    assert await table("lead_sources", WS).count(external_id="crm-7") == 1


async def test_broker_edited_fields_survive_crm_merge():
    lead = await get_lead_repository(WS).create({"phone": "+971504440000", "first_name": "Bro", "source": "csv_upload", "budget_max_aed": 900_000, "broker_edited_fields": ["budget_max_aed"]})
    result = await land([RawRecord(external_id="b1", payload={"phone": "0504440000", "name": "Bro", "budget": "3M"})], connector_id="csv", workspace_id=WS)
    await process_record(result.ids[0], workspace_id=WS)
    assert (await get_lead_repository(WS).get_by_id(lead["id"]))["budget_max_aed"] == 900_000


def test_pin_crm_url_connects_to_checked_address(monkeypatch):
    import socket

    from app.modules.ingestion.connectors.crm_pull import pin_crm_url

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))])
    pinned = pin_crm_url("https://crm.example.com/leads?x=1")
    assert pinned.url == "https://93.184.216.34/leads?x=1"
    assert pinned.headers == {"Host": "crm.example.com"} and pinned.extensions == {"sni_hostname": "crm.example.com"}

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)), (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443))])
    with pytest.raises(ValueError):
        pin_crm_url("https://crm.example.com/leads")


async def test_suppression_normalizes_local_phones():
    from app.modules.ingestion.pipeline.processor import suppress_contact

    await suppress_contact(WS, phone="0501110000", email=None, reason="opt_out")
    assert (await table("suppression_list", WS).select())[0]["phone"] == "+971501110000"
    result = await land([RawRecord(external_id="p2", payload={"phone": "+971 50 111 0000", "name": "Sup"})], connector_id="csv", workspace_id=WS)
    assert (await process_record(result.ids[0], workspace_id=WS)).status == "review"


def test_merge_updates_protects_mirrors_of_broker_edits():
    from app.modules.ingestion.pipeline.processor import merge_updates

    existing = {"id": "l", "budget_max_aed": 0, "budget_max": 0, "broker_edited_fields": ["budget_max_aed"]}
    updates, _ = merge_updates(existing, {"budget_max_aed": 3_000_000, "budget_max": 3_000_000})
    assert "budget_max" not in updates and "budget_max_aed" not in updates


def test_connector_url_credentials_are_redacted():
    from app.api.admin import _redact_config

    out = _redact_config({"url": "https://user:pw@crm.test/leads?api_key=abc&page=1"})
    assert out["url"] == "https://[redacted]@crm.test/leads?api_key=[redacted]&page=1"
