"""Co-work Connections: configured external systems, health tests, webhooks and actions.

A *connection* is one configured instance of a provider from ``providers.py``
(e.g. "Property Finder — Marina office"). It stores credentials (never
returned to clients), exposes an HMAC-signed inbound webhook, can be
health-tested, and offers ``execute_action`` — the primitive routines use to
pull listings, fetch leads, send messages, create calendar events, etc.

Without credentials every action reports ``simulated: true`` and explains what
is missing instead of pretending it talked to the provider.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
from collections.abc import Callable
from email.message import EmailMessage
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from app.config import get_settings
from app.modules.cowork import realestate_crm
from app.modules.cowork.providers import (
    PROVIDERS,
    ProviderSpec,
    get_provider,
    secret_keys,
)
from app.modules.ingestion.connectors.base import (
    SignatureError,
    land,
    verify_hmac_sha256,
)
from app.modules.ingestion.connectors.crm_pull import (
    pin_crm_url,
    safe_error,
    validate_crm_url,
)
from app.modules.ingestion.models import RawRecord
from app.modules.store import Row, new_id, now_iso, table

logger = logging.getLogger(__name__)

TABLE = "cowork_connections"
REDACTED = "••••••••"
HTTP_TIMEOUT_S = 8.0
MAX_ITEMS = 500

ConnStatus = Literal["active", "paused"]
TestStatus = Literal["ok", "failed", "skipped"]

ClientFactory = Callable[[], httpx.AsyncClient]
_client_factory: ClientFactory = lambda: httpx.AsyncClient(timeout=HTTP_TIMEOUT_S, follow_redirects=False)


def set_client_factory(factory: ClientFactory | None) -> None:
    """Tests inject a mocked ``httpx.AsyncClient``."""
    global _client_factory
    _client_factory = factory or (lambda: httpx.AsyncClient(timeout=HTTP_TIMEOUT_S, follow_redirects=False))


# --------------------------------------------------------------------------- models


class ConnectionIn(BaseModel):
    provider: str = Field(..., min_length=1, max_length=40)
    display_name: str | None = Field(None, max_length=120)
    config: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


class ConnectionPatch(BaseModel):
    display_name: str | None = Field(None, max_length=120)
    config: dict[str, str] | None = None
    enabled: bool | None = None
    rotate_webhook_secret: bool = False


def _validate_config(spec: ProviderSpec, config: dict[str, str]) -> dict[str, str]:
    allowed = {f.key for f in spec.fields} | {"listings_path", "leads_path"}
    unknown = set(config) - allowed
    if unknown:
        raise ValueError(f"unknown config keys for {spec.id}: {', '.join(sorted(unknown))}")
    cleaned = {k: str(v).strip() for k, v in config.items() if str(v).strip()}
    for key in ("base_url", "feed_url", "webhook_url"):
        if cleaned.get(key):
            cleaned[key] = validate_crm_url(cleaned[key])
    return cleaned


def missing_required(spec: ProviderSpec, config: dict[str, str]) -> list[str]:
    return [f.label for f in spec.fields if f.required and not config.get(f.key)]


def public_view(row: Row) -> Row:
    spec = get_provider(row["provider"])
    cfg = dict(row.get("config") or {})
    secret = secret_keys(spec) if spec else set()
    shown = {k: (REDACTED if k in secret else v) for k, v in cfg.items()}
    out = {k: v for k, v in row.items() if k not in ("config", "webhook_secret")}
    out["config"] = shown
    out["has_webhook_secret"] = bool(row.get("webhook_secret"))
    out["missing"] = missing_required(spec, cfg) if spec else []
    out["health"] = health_of(row, spec)
    out["provider_name"] = spec.name if spec else row["provider"]
    out["category"] = spec.category if spec else "data"
    out["capabilities"] = list(spec.capabilities) if spec else []
    out["inbound_webhook"] = bool(spec and spec.inbound_webhook)
    out["certification"] = spec.certification if spec else None
    return out


def health_of(row: Row, spec: ProviderSpec | None) -> str:
    if row.get("status") == "paused":
        return "paused"
    if spec and missing_required(spec, row.get("config") or {}):
        return "not_configured"
    if row.get("last_error"):
        return "error"
    if row.get("last_test_status") == "failed":
        return "degraded"
    if row.get("last_test_status") == "ok":
        return "connected"
    return "untested"


# --------------------------------------------------------------------------- CRUD


def catalog() -> list[dict[str, Any]]:
    return [p.to_public() for p in PROVIDERS]


async def list_connections(workspace_id: str) -> list[Row]:
    rows = await table(TABLE, workspace_id).select(order="created_at", desc=True, limit=200)
    return [public_view(r) for r in rows]


async def get_connection(workspace_id: str, connection_id: str) -> Row | None:
    return await table(TABLE, workspace_id).get(id=connection_id)


async def create_connection(workspace_id: str, body: ConnectionIn, *, actor: str | None) -> Row:
    spec = get_provider(body.provider)
    if not spec:
        raise ValueError(f"unknown provider {body.provider!r}")
    config = _validate_config(spec, body.config)
    row = await table(TABLE, workspace_id).insert(
        {
            "id": new_id(),
            "provider": spec.id,
            "display_name": body.display_name or spec.name,
            "config": config,
            "webhook_secret": secrets.token_hex(24) if spec.inbound_webhook else None,
            "status": "active" if body.enabled else "paused",
            "last_test_at": None,
            "last_test_status": None,
            "last_test_detail": None,
            "last_error": None,
            "last_activity_at": None,
            "received_total": 0,
            "created_by": actor,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
    )
    return public_view(row)


async def patch_connection(workspace_id: str, connection_id: str, body: ConnectionPatch) -> Row | None:
    t = table(TABLE, workspace_id)
    row = await t.get(id=connection_id)
    if not row:
        return None
    spec = get_provider(row["provider"])
    updates: Row = {"updated_at": now_iso()}
    if body.display_name is not None:
        updates["display_name"] = body.display_name
    if body.config is not None and spec:
        merged = dict(row.get("config") or {})
        incoming = _validate_config(spec, body.config)
        for k in body.config:  # empty string clears a value; redacted marker keeps it
            if body.config[k] == REDACTED:
                continue
            if k in incoming:
                merged[k] = incoming[k]
            else:
                merged.pop(k, None)
        updates["config"] = merged
        updates["last_error"] = None
    if body.enabled is not None:
        updates["status"] = "active" if body.enabled else "paused"
    if body.rotate_webhook_secret and spec and spec.inbound_webhook:
        updates["webhook_secret"] = secrets.token_hex(24)
    rows = await t.update(updates, id=connection_id)
    return public_view(rows[0]) if rows else None


async def delete_connection(workspace_id: str, connection_id: str) -> bool:
    return (await table(TABLE, workspace_id).delete(id=connection_id)) > 0


async def reveal_webhook(workspace_id: str, connection_id: str) -> dict[str, Any] | None:
    """Return the inbound URL + secret once so an external system can be configured."""
    row = await get_connection(workspace_id, connection_id)
    if not row or not row.get("webhook_secret"):
        return None
    return {
        "url": webhook_url(workspace_id, connection_id),
        "secret": row["webhook_secret"],
        "signature_header": "X-Signature-256",
        "algorithm": "HMAC-SHA256 hex of the raw body, optionally prefixed with 'sha256='",
    }


def webhook_url(workspace_id: str, connection_id: str) -> str:
    base = (get_settings().PUBLIC_API_URL or "").rstrip("/")
    return f"{base}/api/v1/cowork/webhooks/{connection_id}?workspace_id={workspace_id}"


# --------------------------------------------------------------------------- health tests


async def _record_test(workspace_id: str, connection_id: str, status: TestStatus, detail: str, *, error: str | None = None) -> None:
    await table(TABLE, workspace_id).update(
        {
            "last_test_at": now_iso(),
            "last_test_status": status,
            "last_test_detail": detail[:500],
            "last_error": error[:500] if error else None,
            "updated_at": now_iso(),
        },
        id=connection_id,
    )


def _auth_headers(spec: ProviderSpec, cfg: dict[str, str]) -> dict[str, str]:
    token = cfg.get("access_token") or cfg.get("api_key")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _ping_request(spec: ProviderSpec, cfg: dict[str, str]) -> tuple[str, str, dict[str, Any] | None]:
    """(method, url, json_body) for the cheapest authenticated call each provider offers."""
    base = (cfg.get("base_url") or "").rstrip("/")
    if spec.id == "hubspot":
        return "GET", "https://api.hubapi.com/crm/v3/objects/contacts?limit=1", None
    if spec.id in ("whatsapp", "voice_notes"):
        return "GET", f"https://graph.facebook.com/v20.0/{cfg.get('phone_number_id')}", None
    if spec.id == "meta_lead_ads":
        return "GET", f"https://graph.facebook.com/v20.0/{cfg.get('page_id')}?fields=id,name", None
    if spec.id == "broker_api":
        return "GET", f"{base}{cfg.get('leads_path') or '/leads'}?limit=1", None
    if spec.id == "gmail":
        return "GET", "https://gmail.googleapis.com/gmail/v1/users/me/profile", None
    if spec.id == "google_calendar":
        return "GET", f"https://www.googleapis.com/calendar/v3/calendars/{cfg.get('calendar_id') or 'primary'}", None
    if spec.id == "google_sheets":
        return "GET", f"https://sheets.googleapis.com/v4/spreadsheets/{cfg.get('spreadsheet_id')}?fields=spreadsheetId", None
    if spec.id == "slack":
        return "POST", cfg.get("webhook_url") or "", {"text": "Co-work connection test — this Slack webhook is wired up."}
    if spec.id == "bitrix24":
        return "GET", f"{(cfg.get('webhook_url') or '').rstrip('/')}/profile.json", None
    if spec.id == "zoho_crm":
        return "GET", f"{base or 'https://www.zohoapis.com'}/crm/v2/settings/modules", None
    if spec.id == "propertybase":
        return "GET", f"{base}/services/data/", None
    if spec.id == realestate_crm.PROVIDER:
        return "GET", f"{base}/v1/me", None
    if spec.id == "property_finder":
        return "GET", f"{base or 'https://api.propertyfinder.ae'}{cfg.get('listings_path') or '/v1/listings'}?limit=1", None
    return "GET", base, None


async def _http(method: str, url: str, *, headers: dict[str, str], body: dict[str, Any] | None = None) -> httpx.Response:
    pinned = pin_crm_url(url)
    async with _client_factory() as client:
        return await client.request(
            method,
            pinned.url,
            headers={**headers, **pinned.headers},
            json=body,
            extensions=pinned.extensions or None,
        )


async def test_connection(workspace_id: str, connection_id: str) -> dict[str, Any]:
    row = await get_connection(workspace_id, connection_id)
    if not row:
        raise LookupError("connection not found")
    spec = get_provider(row["provider"])
    if not spec:
        raise LookupError("unknown provider")
    cfg = dict(row.get("config") or {})
    missing = missing_required(spec, cfg)
    if missing:
        detail = f"Not configured: {', '.join(missing)} missing"
        await _record_test(workspace_id, connection_id, "failed", detail, error=detail)
        return {"status": "failed", "detail": detail, "missing": missing}

    if spec.test_method == "llm_ping":
        from app.modules.llm.gateway import get_gateway

        gw = get_gateway()
        ok = bool(gw.available)
        detail = "LLM provider configured" if ok else "No LLM provider key set — routines fall back to deterministic rules"
        await _record_test(workspace_id, connection_id, "ok" if ok else "failed", detail, error=None if ok else detail)
        return {"status": "ok" if ok else "failed", "detail": detail}

    if spec.test_method == "jev_ping":
        from app.modules.llm import jev

        ok, detail = await jev.ping(api_key=cfg.get("api_key"), base_url=cfg.get("base_url") or None)
        await _record_test(workspace_id, connection_id, "ok" if ok else "failed", detail, error=None if ok else detail)
        return {"status": "ok" if ok else "failed", "detail": detail}

    if spec.test_method == "voice_ping":
        from app.services.voice_service import VoiceService

        lang = (cfg.get("voice_language") or "en").strip().lower()[:2]
        tts_ok = VoiceService().tts_available(lang)
        method, url, body = _ping_request(spec, cfg)
        try:
            resp = await _http(method, url, headers=_auth_headers(spec, cfg), body=body)
            wa_ok = resp.status_code < 400
            wa_detail = f"WhatsApp audio endpoint reachable (HTTP {resp.status_code})" if wa_ok else f"WhatsApp rejected the phone number / token (HTTP {resp.status_code})"
        except Exception as exc:  # noqa: BLE001
            wa_ok, wa_detail = False, safe_error(exc)
        ok = tts_ok and wa_ok
        detail = f"{'TTS voice ready' if tts_ok else f'No TTS voice for “{lang}” — set PIPER_MODEL_PATH'} · {wa_detail}"
        await _record_test(workspace_id, connection_id, "ok" if ok else "failed", detail, error=None if ok else detail)
        return {"status": "ok" if ok else "failed", "detail": detail, "tts": tts_ok, "delivery": wa_ok}

    if spec.test_method == "webhook":
        detail = "Inbound webhook ready — send a signed test from the Webhook panel"
        await _record_test(workspace_id, connection_id, "ok", detail)
        return {"status": "ok", "detail": detail, "webhook_url": webhook_url(workspace_id, connection_id)}

    if spec.test_method == "feed_fetch":
        url = cfg.get("feed_url") or ""
        try:
            resp = await _http("GET", url, headers={})
            ok = resp.status_code < 400
            ctype = resp.headers.get("content-type", "")
            detail = f"Feed responded {resp.status_code} ({ctype or 'no content-type'})" if ok else f"Feed returned HTTP {resp.status_code}"
            if ok and "xml" not in ctype and not resp.text.lstrip().startswith("<"):
                ok, detail = False, f"Feed responded {resp.status_code} but is not XML"
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, safe_error(exc)
        await _record_test(workspace_id, connection_id, "ok" if ok else "failed", detail, error=None if ok else detail)
        return {"status": "ok" if ok else "failed", "detail": detail}

    # http_ping
    method, url, body = _ping_request(spec, cfg)
    if not url:
        detail = "No endpoint configured"
        await _record_test(workspace_id, connection_id, "failed", detail, error=detail)
        return {"status": "failed", "detail": detail}
    try:
        resp = await _http(method, url, headers=_auth_headers(spec, cfg), body=body)
        if resp.status_code in (401, 403):
            ok, detail = False, f"{spec.name} rejected the credentials (HTTP {resp.status_code})"
        elif resp.status_code >= 400:
            ok, detail = False, f"{spec.name} returned HTTP {resp.status_code}"
        else:
            ok, detail = True, f"{spec.name} reachable (HTTP {resp.status_code})"
    except Exception as exc:  # noqa: BLE001
        ok, detail = False, safe_error(exc)
    await _record_test(workspace_id, connection_id, "ok" if ok else "failed", detail, error=None if ok else detail)
    return {"status": "ok" if ok else "failed", "detail": detail}


# --------------------------------------------------------------------------- inbound webhooks


SAMPLE_LEADS: dict[str, dict[str, Any]] = {
    "property_finder": {
        "event": "lead.created",
        "lead": {"id": "pf-test-1", "name": "Test Buyer", "phone": "+971501234567", "email": "buyer@example.com", "message": "Interested in 2BR in Dubai Marina", "listing_reference": "PF-12345"},
    },
    "bayut": {"lead_id": "bayut-test-1", "name": "Test Buyer", "mobile": "+971501234567", "email": "buyer@example.com", "message": "Is this villa still available?", "listing_reference": "BY-777"},
    "dubizzle": {"lead_id": "dz-test-1", "name": "Test Buyer", "mobile": "+971501234567", "email": "buyer@example.com", "message": "Viewing this weekend?", "listing_reference": "DZ-42"},
    "realestate_crm": {"event": "lead.updated", "lead": {"id": "crm-test-1", "first_name": "Test", "last_name": "Buyer", "phone": "+971501234567", "stage": "qualified", "budget_max_aed": 2500000}},
    "whatsapp": {"entry": [{"changes": [{"value": {"messages": [{"from": "971501234567", "text": {"body": "Hi, looking for a villa"}}]}}]}]},
    "meta_lead_ads": {"object": "page", "entry": [{"id": "1234567890", "changes": [{"field": "leadgen", "value": {"leadgen_id": "meta-test-1", "form_id": "form-1", "page_id": "1234567890", "created_time": 1700000000}}]}]},
    "portal_webhook": {"external_id": "web-test-1", "name": "Test Buyer", "phone": "+971501234567", "email": "buyer@example.com", "message": "Website form test", "source": "website"},
}


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def normalize_inbound(provider: str, data: Any) -> list[RawRecord]:
    """Map a provider payload into raw lead records the ingestion pipeline understands."""
    if provider == realestate_crm.PROVIDER:
        return realestate_crm.normalize(data)
    items: list[dict[str, Any]]
    if isinstance(data, list):
        items = [i for i in data if isinstance(i, dict)]
    elif isinstance(data, dict):
        if isinstance(data.get("records"), list):
            items = [i for i in data["records"] if isinstance(i, dict)]
        elif isinstance(data.get("leads"), list):
            items = [i for i in data["leads"] if isinstance(i, dict)]
        elif isinstance(data.get("lead"), dict):
            items = [{**data["lead"], "event": data.get("event")}]
        elif provider == "meta_lead_ads" and isinstance(data.get("entry"), list):
            items = []
            for entry in data["entry"]:
                for change in (entry or {}).get("changes", []) or []:
                    value = (change or {}).get("value") or {}
                    if value.get("leadgen_id"):
                        items.append({"external_id": str(value["leadgen_id"]), "leadgen_id": str(value["leadgen_id"]), "form_id": value.get("form_id"), "page_id": value.get("page_id") or (entry or {}).get("id"), "created_time": value.get("created_time"), "pending_fetch": True})
        elif provider == "whatsapp" and isinstance(data.get("entry"), list):
            items = []
            for entry in data["entry"]:
                for change in (entry or {}).get("changes", []) or []:
                    for msg in ((change or {}).get("value") or {}).get("messages", []) or []:
                        items.append({"phone": msg.get("from"), "message": ((msg.get("text") or {}).get("body")), "external_id": msg.get("id")})
        else:
            items = [data]
    else:
        raise TypeError("payload must be a JSON object or list")

    records: list[RawRecord] = []
    for item in items[:MAX_ITEMS]:
        payload = {
            "external_id": item.get("id") or item.get("lead_id") or item.get("external_id"),
            "name": item.get("name") or " ".join(x for x in (item.get("first_name"), item.get("last_name")) if x) or None,
            "first_name": item.get("first_name"),
            "last_name": item.get("last_name"),
            "phone": item.get("phone") or item.get("mobile") or item.get("phone_number"),
            "email": item.get("email"),
            "message": item.get("message") or item.get("enquiry") or item.get("notes"),
            "listing_reference": item.get("listing_reference") or item.get("reference") or item.get("property_reference"),
            "stage": item.get("stage"),
            "budget_max_aed": item.get("budget_max_aed") or item.get("budget"),
            "area": item.get("area") or item.get("area_preference") or item.get("community") or item.get("location"),
            "purpose": item.get("purpose") or item.get("intent"),
            "timeline": item.get("timeline"),
            "property_type": item.get("property_type") or item.get("type"),
            "bedrooms": item.get("bedrooms") or item.get("beds"),
            "source": provider,
            "raw": item,
        }
        if item.get("pending_fetch"):
            payload.update({"pending_fetch": True, "leadgen_id": item.get("leadgen_id"), "form_id": item.get("form_id"), "page_id": item.get("page_id")})
        payload = {k: v for k, v in payload.items() if v not in (None, "")}
        ext = payload.get("external_id")
        records.append(RawRecord(external_id=str(ext) if ext else None, payload=payload, source_hint=provider))
    return records


async def handle_inbound(
    workspace_id: str,
    connection_id: str,
    headers: dict[str, str],
    body: bytes,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Verify signature, normalize and land. ``dry_run`` validates without persisting."""
    row = await get_connection(workspace_id, connection_id)
    if not row:
        raise LookupError("connection not found")
    spec = get_provider(row["provider"])
    if not spec or not spec.inbound_webhook:
        raise LookupError("connection has no inbound webhook")
    if row.get("status") != "active":
        raise PermissionError(f"connection is {row.get('status')}")
    cfg = dict(row.get("config") or {})
    secrets = [s for s in (row.get("webhook_secret"), cfg.get("app_secret") if spec.id == "meta_lead_ads" else None) if s]
    if not secrets:
        raise PermissionError("webhook has no signing secret")
    lowered = {k.lower(): v for k, v in headers.items()}
    provided = lowered.get("x-signature-256") or lowered.get("x-hub-signature-256") or lowered.get("x-signature")
    if not any(verify_hmac_sha256(s, body, provided) for s in secrets):
        if not dry_run:
            await table(TABLE, workspace_id).update({"last_error": "invalid webhook signature", "updated_at": now_iso()}, id=connection_id)
        raise SignatureError("invalid signature")
    try:
        data = json.loads(body.decode("utf-8") or "null")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("invalid json") from exc
    records = normalize_inbound(spec.id, data)
    if dry_run:
        return {"status": "ok", "dry_run": True, "records": [r.payload for r in records], "count": len(records)}
    if spec.id == "meta_lead_ads":
        records = await _meta_resolve(spec, cfg, records)
    result = await land(records, connector_id=None, workspace_id=workspace_id)
    await table(TABLE, workspace_id).update(
        {
            "last_activity_at": now_iso(),
            "received_total": int(row.get("received_total") or 0) + len(result.landed),
            "last_error": None,
            "updated_at": now_iso(),
        },
        id=connection_id,
    )
    return {"status": "ok", "landed": len(result.landed), "duplicates": result.duplicates, "raw_ids": result.ids}


async def test_webhook(workspace_id: str, connection_id: str) -> dict[str, Any]:
    """Sign a provider-shaped sample with the stored secret and run it through the inbound path."""
    row = await get_connection(workspace_id, connection_id)
    if not row:
        raise LookupError("connection not found")
    sample = SAMPLE_LEADS.get(row["provider"]) or SAMPLE_LEADS["portal_webhook"]
    body = json.dumps(sample).encode("utf-8")
    secret = row.get("webhook_secret") or ""
    try:
        out = await handle_inbound(workspace_id, connection_id, {"X-Signature-256": sign(secret, body)}, body, dry_run=True)
        detail = f"Signature verified, {out['count']} record(s) parsed"
        status: TestStatus = "ok"
    except (SignatureError, ValueError, PermissionError, LookupError) as exc:
        out = {"status": "failed", "error": str(exc)}
        detail = f"Webhook test failed: {exc}"
        status = "failed"
    await table(TABLE, workspace_id).update(
        {"last_test_at": now_iso(), "last_test_status": status, "last_test_detail": detail, "updated_at": now_iso()},
        id=connection_id,
    )
    return {**out, "detail": detail, "url": webhook_url(workspace_id, connection_id), "sample": sample}


# --------------------------------------------------------------------------- actions (used by routines)

ActionName = Literal[
    "pull_listings",
    "pull_leads",
    "push_lead",
    "send_message",
    "send_email",
    "create_event",
    "notify",
]


def _simulated(reason: str, **extra: Any) -> dict[str, Any]:
    return {"simulated": True, "reason": reason, **extra}


def _dig(obj: Any, path: str | None) -> Any:
    if not path:
        return obj
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def normalize_listing(provider: str, item: dict[str, Any]) -> dict[str, Any] | None:
    ref = item.get("reference") or item.get("id") or item.get("listing_reference") or item.get("external_id")
    if not ref:
        return None
    price = item.get("price") or item.get("price_aed") or _dig(item, "price.value")
    try:
        price_f = float(price) if price not in (None, "") else None
    except (TypeError, ValueError):
        price_f = None
    ptype = str(item.get("property_type") or item.get("type") or "apartment").lower()
    offering = str(item.get("offering_type") or item.get("listing_type") or item.get("purpose") or "sale").lower()
    listing_type = "rent" if "rent" in offering else "sale"
    return {
        "source": provider,
        "source_id": str(ref),
        "source_url": item.get("url") or item.get("source_url"),
        "title": item.get("title") or f"{ptype.title()} in {item.get('community') or item.get('area') or 'Dubai'}",
        "description": item.get("description"),
        "property_type": ptype if ptype in ("apartment", "villa", "townhouse", "penthouse") else "apartment",
        "listing_type": listing_type,
        "area": item.get("community") or item.get("area") or item.get("location"),
        "price": price_f,
        "bedrooms": item.get("bedrooms") or item.get("beds"),
        "bathrooms": item.get("bathrooms") or item.get("baths"),
        "size_sqft": item.get("size_sqft") or item.get("size"),
        "images": item.get("images") or item.get("photos") or ([item["image"]] if item.get("image") else []),
        "permit_number": item.get("permit_number") or item.get("rera_permit") or item.get("trakheesi"),
        "is_active": item.get("is_active", True),
        "updated_at": now_iso(),
    }


async def _upsert_listings(workspace_id: str, provider: str, items: list[dict[str, Any]]) -> dict[str, int]:
    from app.database import get_property_repository

    repo = get_property_repository(workspace_id)
    created = updated = skipped = 0
    for item in items[:MAX_ITEMS]:
        listing = normalize_listing(provider, item)
        if not listing:
            skipped += 1
            continue
        existing = await repo.get_by_source_ref(provider, source_id=listing["source_id"])
        if existing:
            await repo.update(existing["id"], {k: v for k, v in listing.items() if k not in ("source", "source_id")})
            updated += 1
        else:
            await repo.create({**listing, "created_at": now_iso()})
            created += 1
    return {"created": created, "updated": updated, "skipped": skipped}


async def execute_action(workspace_id: str, connection_row: Row, action: str, params: dict[str, Any]) -> dict[str, Any]:
    """Run one connector action. Never raises for provider failures; returns a result dict."""
    spec = get_provider(connection_row["provider"])
    if not spec:
        return {"ok": False, "error": "unknown provider"}
    if connection_row.get("status") != "active":
        return {"ok": False, "error": f"connection is {connection_row.get('status')}"}
    if action not in spec.capabilities and not (action == "push_lead" and "push_leads" in spec.capabilities):
        return {"ok": False, "error": f"{spec.name} cannot {action}"}
    cfg = dict(connection_row.get("config") or {})
    missing = missing_required(spec, cfg)
    if missing:
        return {"ok": True, **_simulated(f"{spec.name} not configured ({', '.join(missing)} missing)", action=action)}
    try:
        if action == "pull_listings":
            return await _pull_listings(workspace_id, spec, cfg, params)
        if action == "pull_leads":
            return await _pull_leads(workspace_id, spec, cfg, params, row=connection_row)
        if action == "push_lead":
            return await _push_lead(spec, cfg, params)
        if action == "send_message":
            return await _send_message(spec, cfg, params)
        if action == "send_email":
            return await _send_email(spec, cfg, params)
        if action == "create_event":
            return await _create_event(spec, cfg, params)
        if action == "notify":
            return await _notify(spec, cfg, params)
        if action == "send_voice_note":
            return await _send_voice_note(spec, cfg, params)
    except Exception as exc:  # noqa: BLE001
        logger.warning("connector action %s on %s failed: %s", action, spec.id, safe_error(exc))
        return {"ok": False, "error": safe_error(exc)}
    return {"ok": False, "error": f"unsupported action {action}"}


async def _get_json(spec: ProviderSpec, cfg: dict[str, str], url: str) -> Any:
    resp = await _http("GET", url, headers=_auth_headers(spec, cfg))
    if resp.status_code >= 400:
        raise ValueError(f"{spec.name} returned HTTP {resp.status_code}")
    return resp.json()


def _items(data: Any, path: str | None) -> list[dict[str, Any]]:
    found = _dig(data, path) if path else None
    if found is None:
        if isinstance(data, list):
            found = data
        elif isinstance(data, dict):
            for key in ("data", "items", "results", "listings", "leads", "result"):
                if isinstance(data.get(key), list):
                    found = data[key]
                    break
    return [i for i in (found or []) if isinstance(i, dict)]


async def _pull_listings(workspace_id: str, spec: ProviderSpec, cfg: dict[str, str], params: dict[str, Any]) -> dict[str, Any]:
    base = (cfg.get("base_url") or ("https://api.propertyfinder.ae" if spec.id == "property_finder" else "")).rstrip("/")
    path = cfg.get("listings_path") or params.get("path") or "/v1/listings"
    data = await _get_json(spec, cfg, f"{base}{path}")
    items = _items(data, cfg.get("items_path"))
    counts = await _upsert_listings(workspace_id, spec.id, items)
    return {"ok": True, "fetched": len(items), **counts}


async def _land_and_process(workspace_id: str, records: list[RawRecord], *, fetched: int, **extra: Any) -> dict[str, Any]:
    from app.modules.ingestion.pipeline.processor import process_many

    result = await land(records, connector_id=None, workspace_id=workspace_id)
    processed = await process_many(result.ids, workspace_id=workspace_id) if result.ids else []
    published = [p for p in processed if p.status == "published"]
    return {
        "ok": True,
        "fetched": fetched,
        "landed": len(result.landed),
        "duplicates": result.duplicates,
        "processed": len(processed),
        "published": len(published),
        "review": sum(1 for p in processed if p.status == "review"),
        "lead_ids": [p.lead_id for p in published if p.lead_id],
        **extra,
    }


async def _pull_leads(workspace_id: str, spec: ProviderSpec, cfg: dict[str, str], params: dict[str, Any], *, row: Row | None = None) -> dict[str, Any]:
    if spec.id == realestate_crm.PROVIDER:
        return await _pull_realestate_crm_leads(workspace_id, cfg, params, row=row)
    if spec.id == "gmail":
        return await _pull_gmail_leads(workspace_id, spec, cfg, params)
    if spec.id == "meta_lead_ads":
        return await _pull_meta_leads(workspace_id, spec, cfg, params)
    if spec.id == "bitrix24":
        url = f"{(cfg.get('webhook_url') or '').rstrip('/')}/crm.lead.list.json"
    elif spec.id == "hubspot":
        url = "https://api.hubapi.com/crm/v3/objects/contacts?limit=100&properties=firstname,lastname,phone,email"
    else:
        base = (cfg.get("base_url") or "").rstrip("/")
        default_path = "/leads" if spec.id == "broker_api" else "/v1/leads"
        url = f"{base}{cfg.get('leads_path') or params.get('path') or default_path}" if spec.id != "generic_crm" else base
    data = await _get_json(spec, cfg, url)
    items = _items(data, cfg.get("items_path"))
    return await _land_and_process(workspace_id, normalize_inbound(spec.id, items), fetched=len(items))


async def _pull_realestate_crm_leads(workspace_id: str, cfg: dict[str, str], params: dict[str, Any], *, row: Row | None) -> dict[str, Any]:
    """Changed-since pull from the standalone CRM; cursor/watermark live in ``sync_state`` on the connection.

    The CRM is authoritative for pipeline stage, so after the pipeline has merged the
    records the platform lead's stage is aligned to the CRM's where they differ.
    """
    state = dict((row or {}).get("sync_state") or {})
    if params.get("full"):
        state = {}
    items, new_state = await realestate_crm.fetch_changed_leads(_http, cfg, state)
    result = await _land_and_process(workspace_id, realestate_crm.normalize(items), fetched=len(items))
    stages = {str(i["id"]): s for i in items if i.get("id") and (s := realestate_crm.stage_from_crm(i))}
    result["stage_synced"] = await _sync_crm_stages(workspace_id, result.get("lead_ids") or [], stages)
    if row is not None:
        await table(TABLE, workspace_id).update({"sync_state": {**new_state, "last_pull_at": now_iso()}, "updated_at": now_iso()}, id=row["id"])
    return {**result, "cursor": new_state.get("cursor"), "updated_after": new_state.get("updated_after")}


async def _sync_crm_stages(workspace_id: str, lead_ids: list[str], crm_stages: dict[str, str]) -> int:
    from app.database import get_lead_repository

    if not lead_ids or not crm_stages:
        return 0
    repo = get_lead_repository(workspace_id)
    changed = 0
    for lead_id in lead_ids:
        lead = await repo.get_by_id(lead_id)
        if not lead or lead.get("opted_out_at"):
            continue
        target = crm_stages.get(str(lead.get("crm_external_id") or ""))
        if target and target != lead.get("stage"):
            await repo.update(lead_id, {"stage": target, "status": target, "updated_at": now_iso()})
            changed += 1
    return changed


GRAPH = "https://graph.facebook.com/v20.0"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
GMAIL_MAX_MESSAGES = 50


async def _pull_gmail_leads(workspace_id: str, spec: ProviderSpec, cfg: dict[str, str], params: dict[str, Any]) -> dict[str, Any]:
    """List matching messages, extract a structured lead from each and push through the pipeline."""
    from urllib.parse import quote

    from app.modules.cowork.lead_extraction import (
        extract_lead,
        gmail_message_text,
        source_from_sender,
        to_raw_payload,
    )

    query = params.get("query") or cfg.get("label") or "from:(bayut.com OR dubizzle.com OR propertyfinder.ae) newer_than:1d"
    limit = min(int(params.get("limit") or GMAIL_MAX_MESSAGES), GMAIL_MAX_MESSAGES)
    listing = await _get_json(spec, cfg, f"{GMAIL}/messages?q={quote(query)}&maxResults={limit}")
    ids = [m.get("id") for m in (listing.get("messages") or []) if isinstance(m, dict) and m.get("id")]
    records: list[RawRecord] = []
    low_confidence = 0
    for mid in ids:
        msg = await _get_json(spec, cfg, f"{GMAIL}/messages/{mid}?format=full")
        subject, sender, body = gmail_message_text(msg)
        lead = await extract_lead(subject, body, sender)
        if not (lead.phone or lead.email):
            low_confidence += 1
            continue
        payload = to_raw_payload(lead, external_id=f"gmail:{mid}", source=source_from_sender(sender), extra={"email_subject": subject[:200], "email_from": sender[:200]})
        records.append(RawRecord(external_id=f"gmail:{mid}", payload=payload, source_hint=payload["source"]))
    return await _land_and_process(workspace_id, records, fetched=len(ids), skipped_no_contact=low_confidence, query=query)


async def _meta_fetch_lead(spec: ProviderSpec, cfg: dict[str, str], leadgen_id: str) -> dict[str, Any] | None:
    try:
        return await _get_json(spec, cfg, f"{GRAPH}/{leadgen_id}?fields=id,created_time,field_data,form_id,ad_id,adset_id,campaign_id")
    except Exception as exc:  # noqa: BLE001
        logger.warning("meta leadgen fetch failed: %s", safe_error(exc))
        return None


async def _meta_resolve(spec: ProviderSpec, cfg: dict[str, str], records: list[RawRecord]) -> list[RawRecord]:
    """Webhooks only carry ``leadgen_id``; fetch the form answers before landing. Unresolvable leads still land (for retry/review)."""
    from app.modules.cowork.lead_extraction import meta_lead_payload

    out: list[RawRecord] = []
    for rec in records:
        p = rec.payload
        if not p.get("pending_fetch") or not cfg.get("access_token"):
            out.append(rec)
            continue
        lead = await _meta_fetch_lead(spec, cfg, str(p["leadgen_id"]))
        if lead:
            out.append(RawRecord(external_id=rec.external_id, payload=meta_lead_payload(lead, form_id=p.get("form_id"), page_id=p.get("page_id")), source_hint="meta_lead_ads"))
        else:
            out.append(rec)
    return out


async def _pull_meta_leads(workspace_id: str, spec: ProviderSpec, cfg: dict[str, str], params: dict[str, Any]) -> dict[str, Any]:
    """Scheduled catch-up: every form on the page → its recent leads (covers missed webhooks)."""
    from app.modules.cowork.lead_extraction import meta_lead_payload

    page = cfg.get("page_id")
    forms = await _get_json(spec, cfg, f"{GRAPH}/{page}/leadgen_forms?fields=id,name,status&limit=50")
    records: list[RawRecord] = []
    fetched = 0
    for form in _items(forms, "data"):
        if form.get("status") not in (None, "ACTIVE"):
            continue
        leads = await _get_json(spec, cfg, f"{GRAPH}/{form['id']}/leads?fields=id,created_time,field_data,ad_id,adset_id,campaign_id&limit=100")
        for lead in _items(leads, "data"):
            fetched += 1
            payload = meta_lead_payload(lead, form_id=str(form["id"]), page_id=page)
            records.append(RawRecord(external_id=str(lead.get("id")) if lead.get("id") else None, payload=payload, source_hint="meta_lead_ads"))
    return await _land_and_process(workspace_id, records, fetched=fetched)


async def _send_voice_note(spec: ProviderSpec, cfg: dict[str, str], params: dict[str, Any]) -> dict[str, Any]:
    """TTS → upload media → WhatsApp audio message. Fails loudly; never degrades to a text send."""
    from app.services.voice_service import VoiceService

    text = str(params.get("text") or "").strip()
    to = str(params.get("to") or "").strip().lstrip("+")
    lang = (params.get("language") or cfg.get("voice_language") or "en").strip().lower()[:2]
    if not text or not to:
        return {"ok": False, "error": "voice note needs text and a recipient"}
    audio = await VoiceService().text_to_speech(text[:800], lang)
    if not audio:
        return {"ok": False, "error": f"TTS unavailable for '{lang}' — voice note not sent"}
    headers = _auth_headers(spec, cfg)
    pn = cfg.get("phone_number_id")
    pinned = pin_crm_url(f"{GRAPH}/{pn}/media")
    async with _client_factory() as client:
        up = await client.post(pinned.url, headers={**headers, **pinned.headers}, data={"messaging_product": "whatsapp", "type": "audio/ogg"}, files={"file": ("note.ogg", audio, "audio/ogg")}, extensions=pinned.extensions or None)
    if up.status_code >= 400:
        return {"ok": False, "error": f"media upload failed (HTTP {up.status_code})"}
    media_id = (up.json() or {}).get("id")
    if not media_id:
        return {"ok": False, "error": "media upload returned no id"}
    resp = await _http("POST", f"{GRAPH}/{pn}/messages", headers=headers, body={"messaging_product": "whatsapp", "to": to, "type": "audio", "audio": {"id": media_id}})
    if resp.status_code >= 400:
        return {"ok": False, "error": f"WhatsApp audio send failed (HTTP {resp.status_code})"}
    msgs = (resp.json() or {}).get("messages") or []
    return {"ok": True, "media_id": media_id, "message_id": msgs[0].get("id") if msgs else None, "seconds": round(len(audio) / 32000, 1), "language": lang}


async def _push_lead(spec: ProviderSpec, cfg: dict[str, str], params: dict[str, Any]) -> dict[str, Any]:
    lead = params.get("lead") or {}
    if spec.id == realestate_crm.PROVIDER:
        return await realestate_crm.push_lead(_http, cfg, lead)
    if spec.id == "bitrix24":
        url = f"{(cfg.get('webhook_url') or '').rstrip('/')}/crm.lead.add.json"
        body = {"fields": {"TITLE": lead.get("name") or "Lead", "PHONE": [{"VALUE": lead.get("phone")}], "EMAIL": [{"VALUE": lead.get("email")}]}}
    elif spec.id == "hubspot":
        url = "https://api.hubapi.com/crm/v3/objects/contacts"
        body = {"properties": {"firstname": lead.get("first_name"), "lastname": lead.get("last_name"), "phone": lead.get("phone"), "email": lead.get("email")}}
    else:
        url = f"{(cfg.get('base_url') or '').rstrip('/')}{cfg.get('leads_path') or '/v1/leads'}"
        body = lead
    resp = await _http("POST", url, headers=_auth_headers(spec, cfg), body=body)
    return {"ok": resp.status_code < 400, "http_status": resp.status_code}


async def _send_message(spec: ProviderSpec, cfg: dict[str, str], params: dict[str, Any]) -> dict[str, Any]:
    from app.services.whatsapp import get_whatsapp_service

    to, body = str(params.get("to") or ""), str(params.get("body") or "")
    if not to or not body:
        return {"ok": False, "error": "to and body are required"}
    msg = await get_whatsapp_service().send_text(to, body, lead_id=params.get("lead_id"))
    return {"ok": True, "message_id": msg.id, "mode": get_whatsapp_service().mode}


async def _send_email(spec: ProviderSpec, cfg: dict[str, str], params: dict[str, Any]) -> dict[str, Any]:
    to, subject, body = str(params.get("to") or ""), str(params.get("subject") or ""), str(params.get("body") or "")
    if not to or not body:
        return {"ok": False, "error": "to and body are required"}
    msg = EmailMessage()
    msg["To"], msg["From"], msg["Subject"] = to, cfg.get("mailbox", ""), subject or "(no subject)"
    msg.set_content(body)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    resp = await _http("POST", "https://gmail.googleapis.com/gmail/v1/users/me/messages/send", headers=_auth_headers(spec, cfg), body={"raw": raw})
    return {"ok": resp.status_code < 400, "http_status": resp.status_code}


async def _create_event(spec: ProviderSpec, cfg: dict[str, str], params: dict[str, Any]) -> dict[str, Any]:
    start, end = params.get("start"), params.get("end")
    if not start or not end:
        return {"ok": False, "error": "start and end are required"}
    body = {
        "summary": params.get("summary") or "Property viewing",
        "description": params.get("description"),
        "location": params.get("location"),
        "start": {"dateTime": start},
        "end": {"dateTime": end},
        "attendees": [{"email": e} for e in params.get("attendees", []) if e],
    }
    cal = cfg.get("calendar_id") or "primary"
    resp = await _http("POST", f"https://www.googleapis.com/calendar/v3/calendars/{cal}/events", headers=_auth_headers(spec, cfg), body=body)
    return {"ok": resp.status_code < 400, "http_status": resp.status_code}


async def _notify(spec: ProviderSpec, cfg: dict[str, str], params: dict[str, Any]) -> dict[str, Any]:
    text = str(params.get("text") or params.get("body") or "")
    if not text:
        return {"ok": False, "error": "text is required"}
    if spec.id == "slack":
        resp = await _http("POST", cfg.get("webhook_url") or "", headers={}, body={"text": text[:4000]})
        return {"ok": resp.status_code < 400, "http_status": resp.status_code}
    if spec.id == "whatsapp":
        return await _send_message(spec, cfg, {"to": params.get("to"), "body": text})
    return {"ok": False, "error": f"{spec.name} cannot notify"}


def counts_by_health(rows: list[Row]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        out[r["health"]] = out.get(r["health"], 0) + 1
    return out
