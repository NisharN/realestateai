"""Adapter for the standalone UAE real-estate CRM (``NisharN/realestate-crm``).

The CRM is the system of record. This module speaks its ``/v1`` contract exactly:

    GET   /v1/leads?updated_after=<iso>|cursor=<opaque>&limit=N   -> {"data": [...], "paging": {"next": ...}}
    POST  /v1/leads                                                -> create-or-merge (single object or {"leads": [...]})
    PATCH /v1/leads/{id}                                           -> score / band / stage / qualification write-back
    POST  /v1/leads/{id}/activities                                -> timeline entry
    GET   /v1/listings, /v1/viewings; POST/PATCH /v1/viewings; POST /v1/followups

Auth is ``Authorization: Bearer crm_live_...``. Inbound webhooks are signed with
``X-Signature-256: sha256=<hmac>`` over the exact body and carry ``X-Event``.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from app.modules.ingestion.models import RawRecord
from app.modules.leads.stages import PIPELINE_STAGES

logger = logging.getLogger(__name__)

PROVIDER = "realestate_crm"
PAGE_LIMIT = 200
MAX_PAGES = 10
LEAD_EVENTS = ("lead.created", "lead.updated", "lead.contacted")
WRITE_BACK_FIELDS = ("score", "band", "stage", "assigned_broker", "purpose", "timeline", "budget_min_aed", "budget_max_aed", "area_preference")

Http = Callable[..., Awaitable[httpx.Response]]


def base_url(cfg: dict[str, Any]) -> str:
    return str(cfg.get("base_url") or "").rstrip("/")


def headers(cfg: dict[str, Any]) -> dict[str, str]:
    key = cfg.get("api_key") or cfg.get("access_token")
    return {"Authorization": f"Bearer {key}"} if key else {}


# ------------------------------------------------------------------ CRM -> platform


def lead_payload(item: dict[str, Any]) -> dict[str, Any]:
    """Shape one serialized CRM lead into the raw payload the ingestion field-mapper understands."""
    areas = item.get("areas")
    payload: dict[str, Any] = {
        "external_id": item.get("id"),
        "first_name": item.get("first_name"),
        "last_name": item.get("last_name"),
        "name": item.get("name"),
        "phone": item.get("phone"),
        "email": item.get("email"),
        "language": item.get("language"),
        "purpose": item.get("purpose"),
        "property_type": item.get("property_type"),
        "bedrooms": item.get("bedrooms"),
        "area": ", ".join(str(a) for a in areas if a) if isinstance(areas, list) else areas,
        "budget_min_aed": item.get("budget_min_aed"),
        "budget_max_aed": item.get("budget_max_aed"),
        "timeline": item.get("timeline"),
        "payment": item.get("payment_method"),
        "listing_reference": item.get("listing_reference"),
        "message": item.get("notes"),
        "stage": item.get("stage"),
        "crm_assigned_agent_id": item.get("assigned_agent_id"),
        "consent": item.get("consent_marketing"),
        "created_at": item.get("created_at"),
        "source": PROVIDER,
        "raw": item,
    }
    return {k: v for k, v in payload.items() if v not in (None, "", [])}


def _lead_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [i for i in data if isinstance(i, dict)]
    if not isinstance(data, dict):
        raise TypeError("payload must be a JSON object or list")
    if isinstance(data.get("data"), list):
        return [i for i in data["data"] if isinstance(i, dict)]
    if isinstance(data.get("leads"), list):
        return [i for i in data["leads"] if isinstance(i, dict)]
    if isinstance(data.get("lead"), dict):
        event = data.get("event")
        if event and (event not in LEAD_EVENTS):
            return []  # viewing.*, deal.*, lead.deleted … carry a lead stub, not a full record
        if data.get("origin") == "ai_agent":
            return []  # echo of our own write-back; re-ingesting it would loop score → webhook → score
        return [data["lead"]]
    if data.get("id") and (data.get("phone") or data.get("email")):
        return [data]
    return []


def normalize(data: Any) -> list[RawRecord]:
    """Webhook body or ``/v1/leads`` page -> raw records. Deleted leads and non-lead events are ignored."""
    out: list[RawRecord] = []
    for item in _lead_items(data):
        if item.get("deleted_at") or item.get("do_not_contact"):
            continue
        payload = lead_payload(item)
        if not payload.get("external_id"):
            continue
        out.append(RawRecord(external_id=str(payload["external_id"]), payload=payload, source_hint=PROVIDER))
    return out


async def fetch_leads_page(http: Http, cfg: dict[str, Any], *, cursor: str | None, updated_after: str | None, limit: int = PAGE_LIMIT) -> tuple[list[dict[str, Any]], str | None]:
    params: dict[str, Any] = {"limit": max(1, min(int(limit), 1000))}
    if cursor:
        params["cursor"] = cursor
    elif updated_after:
        params["updated_after"] = updated_after
    resp = await http("GET", f"{base_url(cfg)}/v1/leads?{urlencode(params)}", headers=headers(cfg))
    if resp.status_code >= 400:
        raise ValueError(f"Real-estate CRM returned HTTP {resp.status_code}")
    data = resp.json()
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise TypeError("Real-estate CRM returned an unexpected page shape")
    paging: dict[str, Any] = data["paging"] if isinstance(data.get("paging"), dict) else {}
    nxt = paging.get("next")
    return [i for i in data["data"] if isinstance(i, dict)], (str(nxt) if nxt else None)


async def fetch_changed_leads(http: Http, cfg: dict[str, Any], state: dict[str, Any], *, max_pages: int = MAX_PAGES) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Walk ``paging.next`` from the stored cursor; return the items and the new sync state.

    The watermark advances to the newest ``updated_at`` only once the walk finished
    (``next`` exhausted); a partial walk keeps the opaque cursor so the next tick resumes.
    """
    cursor = state.get("cursor")
    since = state.get("updated_after")
    items: list[dict[str, Any]] = []
    for _ in range(max_pages):
        page, nxt = await fetch_leads_page(http, cfg, cursor=cursor, updated_after=since)
        items.extend(page)
        cursor = nxt
        if not nxt:
            break
    newest = since if cursor else max((str(i.get("updated_at")) for i in items if i.get("updated_at")), default=since)
    new_state = {"updated_after": newest, "cursor": cursor, "last_pull_at": None}
    return items, new_state


def stage_from_crm(item: dict[str, Any]) -> str | None:
    stage = item.get("stage")
    return stage if isinstance(stage, str) and stage in PIPELINE_STAGES else None


# ------------------------------------------------------------------ platform -> CRM


def write_back_body(lead: dict[str, Any]) -> dict[str, Any]:
    """Only the fields ``LeadWriteBack`` accepts; the CRM rejects unknown keys."""
    body: dict[str, Any] = {}
    for key in WRITE_BACK_FIELDS:
        value = lead.get(key)
        if value in (None, "", []):
            continue
        if key == "score":
            value = max(0, min(100, round(float(value))))
        elif key == "band":
            value = str(value).lower()
            if value not in ("hot", "warm", "cold"):
                continue
        elif key == "stage":
            if value not in PIPELINE_STAGES:
                continue
        elif key == "purpose" and value not in ("buy", "rent", "invest"):
            continue
        elif key == "area_preference" and isinstance(value, list):
            value = [str(a) for a in value if a]
        body[key] = value
    reasons = lead.get("score_reasons")
    if isinstance(reasons, list) and reasons:
        body["summary"] = "; ".join(str(r) for r in reasons[:4])[:4000]
    return body


async def write_back(http: Http, cfg: dict[str, Any], crm_lead_id: str, body: dict[str, Any]) -> httpx.Response:
    url = f"{base_url(cfg)}/v1/leads/{quote(str(crm_lead_id), safe='')}"
    resp = await http("PATCH", url, headers=headers(cfg), body=body)
    if resp.status_code >= 400:
        raise ValueError(f"Real-estate CRM write-back returned HTTP {resp.status_code}")
    return resp


def upsert_body(lead: dict[str, Any]) -> dict[str, Any]:
    """Platform lead -> ``LeadCreate``. ``external_id`` is the platform lead id so re-pushes merge."""
    areas = lead.get("area_preference")
    body: dict[str, Any] = {
        "first_name": lead.get("first_name"),
        "last_name": lead.get("last_name"),
        "phone": lead.get("phone") or lead.get("phone_e164"),
        "email": lead.get("email"),
        "language": lead.get("preferred_language") or lead.get("language"),
        "source": "ai_agent",
        "external_id": lead.get("id"),
        "purpose": lead.get("purpose") if lead.get("purpose") in ("buy", "rent", "invest") else None,
        "property_type": lead.get("property_type"),
        "bedrooms": lead.get("bedrooms_min"),
        "areas": [str(a) for a in areas if a] if isinstance(areas, list) else ([str(areas)] if areas else None),
        "budget_min_aed": lead.get("budget_min_aed") or lead.get("budget_min"),
        "budget_max_aed": lead.get("budget_max_aed") or lead.get("budget_max"),
        "timeline": lead.get("timeline"),
        "payment_method": lead.get("payment") if lead.get("payment") in ("cash", "mortgage") else None,
        "notes": lead.get("initial_message"),
        "stage": lead.get("stage") if lead.get("stage") in PIPELINE_STAGES else "new",
    }
    return {k: v for k, v in body.items() if v not in (None, "", [])}


async def push_lead(http: Http, cfg: dict[str, Any], lead: dict[str, Any]) -> dict[str, Any]:
    """Leads the CRM already knows are only written back to; new ones are upserted then written back."""
    known = lead.get("crm_external_id")
    if known:
        ai_fields = write_back_body(lead)
        if not ai_fields:
            return {"ok": True, "crm_lead_id": str(known), "wrote_back": []}
        resp = await write_back(http, cfg, str(known), ai_fields)
        return {"ok": True, "http_status": resp.status_code, "crm_lead_id": str(known), "wrote_back": sorted(ai_fields)}
    body = upsert_body(lead)
    if not (body.get("phone") or body.get("email")):
        return {"ok": False, "error": "lead has neither phone nor e-mail"}
    resp = await http("POST", f"{base_url(cfg)}/v1/leads", headers=headers(cfg), body=body)
    if resp.status_code >= 400:
        return {"ok": False, "http_status": resp.status_code}
    data = resp.json() if resp.content else {}
    crm_lead = data.get("lead") if isinstance(data, dict) else None
    out: dict[str, Any] = {"ok": True, "http_status": resp.status_code}
    if isinstance(crm_lead, dict) and crm_lead.get("id"):
        out["crm_lead_id"] = str(crm_lead["id"])
        out["created"] = bool(data.get("created"))
    ai_fields = write_back_body(lead)
    if out.get("crm_lead_id") and ai_fields:
        try:
            await write_back(http, cfg, out["crm_lead_id"], ai_fields)
            out["wrote_back"] = sorted(ai_fields)
        except ValueError as exc:
            out["write_back_error"] = str(exc)
    return out


async def add_activity(http: Http, cfg: dict[str, Any], crm_lead_id: str, kind: str, summary: str, data: dict[str, Any] | None = None) -> bool:
    url = f"{base_url(cfg)}/v1/leads/{quote(str(crm_lead_id), safe='')}/activities"
    resp = await http("POST", url, headers=headers(cfg), body={"kind": kind[:32], "summary": summary[:400], "data": data or {}})
    return resp.status_code < 400
