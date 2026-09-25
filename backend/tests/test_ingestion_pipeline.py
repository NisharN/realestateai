"""Phase 1 ingestion: land → map → clean → validate → merge → publish, idempotency,
review queue, connectors, field maps, admin/data-health endpoints."""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app import mock_store
from app.config import get_settings
from app.database import get_lead_repository
from app.main import app
from app.modules.ingestion import events
from app.modules.ingestion.connectors.base import land
from app.modules.ingestion.connectors.csv_upload import parse_csv
from app.modules.ingestion.connectors.webhook import SignatureError, WebhookConnector
from app.modules.ingestion.field_maps import suggest_field_map
from app.modules.ingestion.models import CanonicalLead
from app.modules.ingestion.pipeline.processor import process_many, process_record, retry_errors
from app.modules.ingestion.pipeline.stages import clean_phone, clean_record, map_record, validate_record
from app.modules.store import reset_memory, table

client = TestClient(app, raise_server_exceptions=False)
WS = get_settings().WORKSPACE_ID

CSV = (
    "Full Name,Mobile,Email,Budget,Area,Type,Beds,Purpose\n"
    "Ahmed Ali,050 123 4567,ahmed@example.com,1.2m,Dubai Marina,Apartment,2,buy\n"
    "Sara Khan,+971 55 765 4321,sara@example.com,AED 120k per year,JVC,apartment,1,rent\n"
    "No Contact,,,,Downtown,villa,,buy\n"
).encode()


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
    assert types == ["lead.created", "lead.updated"]
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

    assert await events.consume(WS, "test", handler) == 2
    assert await events.consume(WS, "test", handler) == 0
    assert len(seen) == 2


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
