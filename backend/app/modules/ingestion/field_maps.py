"""Field-map suggestion (fuzzy header + sample-value matching) and storage."""
from __future__ import annotations

import difflib
import re
from typing import Any

from app.modules.ingestion.models import CANONICAL_FIELDS
from app.modules.store import Row, now_iso, table

_SYNONYMS: dict[str, tuple[str, ...]] = {
    "first_name": ("first name", "firstname", "fname", "given name", "first"),
    "last_name": ("last name", "lastname", "lname", "surname", "family name", "last"),
    "full_name": ("name", "full name", "contact", "contact name", "client", "client name", "customer", "lead name"),
    "phone": ("phone", "mobile", "mobile number", "phone number", "tel", "telephone", "whatsapp", "contact number", "cell", "msisdn"),
    "email": ("email", "e-mail", "email address", "mail"),
    "message": ("message", "comments", "notes", "enquiry", "inquiry", "description", "remarks", "requirement", "requirements"),
    "budget": ("budget", "price", "price range", "max price", "budget aed", "amount"),
    "budget_min": ("budget min", "min budget", "min price", "price from"),
    "budget_max": ("budget max", "max budget", "max price", "price to"),
    "area": ("area", "location", "community", "preferred area", "areas", "district", "neighbourhood", "neighborhood", "region"),
    "property_type": ("property type", "type", "unit type", "category", "property"),
    "bedrooms": ("bedrooms", "beds", "br", "bed", "no of bedrooms", "rooms"),
    "purpose": ("purpose", "intent", "looking to", "buy or rent", "transaction type", "deal type"),
    "timeline": ("timeline", "timeframe", "move in", "when", "urgency", "move-in date"),
    "payment": ("payment", "payment method", "financing", "mortgage", "cash or mortgage"),
    "language": ("language", "preferred language", "lang"),
    "source": ("source", "lead source", "channel", "portal", "campaign", "utm source"),
    "listing_ref": ("listing", "listing ref", "listing id", "property ref", "reference", "ref", "property id", "unit"),
    "external_id": ("id", "lead id", "record id", "crm id", "external id"),
    "created_at": ("created", "created at", "date", "enquiry date", "timestamp", "received", "submitted at"),
    "consent": ("consent", "opt in", "opt-in", "marketing consent", "gdpr"),
}

_PHONE_RE = re.compile(r"^\+?[\d\s\-()]{7,}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.IGNORECASE)
_MONEY_RE = re.compile(r"(aed|dhs|\d[\d,\.]*\s*(k|m|million|thousand))", re.IGNORECASE)


def _norm(header: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", header.lower().replace("_", " ")).strip()


def _header_score(header: str) -> tuple[str | None, float]:
    h = _norm(header)
    best: tuple[str | None, float] = (None, 0.0)
    for target, names in _SYNONYMS.items():
        for name in (target.replace("_", " "), *names):
            if h == name:
                return target, 1.0
            ratio = difflib.SequenceMatcher(None, h, name).ratio()
            if h and (name in h or h in name):
                ratio = max(ratio, 0.85)
            if ratio > best[1]:
                best = (target, ratio)
    return best


def _value_hint(samples: list[str]) -> str | None:
    vals = [s for s in samples if s]
    if not vals:
        return None
    if all(_EMAIL_RE.match(v) for v in vals):
        return "email"
    if all(_PHONE_RE.match(v) and sum(c.isdigit() for c in v) >= 8 for v in vals):
        return "phone"
    if all(_MONEY_RE.search(v) for v in vals):
        return "budget"
    return None


def suggest_field_map(headers: list[str], samples: dict[str, list[str]] | None = None) -> list[dict[str, Any]]:
    """Return one suggestion per header: {source_field, target_field, confidence}."""
    samples = samples or {}
    out: list[dict[str, Any]] = []
    taken: set[str] = set()
    scored = []
    for header in headers:
        target, conf = _header_score(header)
        hint = _value_hint(samples.get(header, []))
        if hint and (target != hint):
            if conf < 0.9:
                target, conf = hint, max(conf, 0.8)
        elif hint and target == hint:
            conf = max(conf, 0.95)
        scored.append((header, target, conf))
    for header, target, conf in sorted(scored, key=lambda t: -t[2]):
        if target is None or conf < 0.6 or (target in taken and target not in ("area", "message")):
            out.append({"source_field": header, "target_field": None, "confidence": round(conf, 2)})
            continue
        taken.add(target)
        out.append({"source_field": header, "target_field": target, "confidence": round(conf, 2)})
    order = {h: i for i, h in enumerate(headers)}
    out.sort(key=lambda s: order[s["source_field"]])
    return out


async def approved_field_map(connector_id: str, workspace_id: str) -> dict[str, str]:
    rows = await table("field_maps", workspace_id).select(connector_id=connector_id, limit=500)
    return {r["source_field"]: r["target_field"] for r in rows if r.get("target_field") and r.get("approved_at")}


async def save_field_map(
    connector_id: str, workspace_id: str, mappings: list[dict[str, Any]], *, approved_by: str | None
) -> list[Row]:
    for m in mappings:
        target = m.get("target_field")
        if target is not None and target not in CANONICAL_FIELDS:
            raise ValueError(f"unknown target field: {target}")
        if not m.get("source_field"):
            raise ValueError("source_field is required")
    fm = table("field_maps", workspace_id)
    await fm.delete(connector_id=connector_id)
    saved: list[Row] = []
    for m in mappings:
        target = m.get("target_field")
        saved.append(
            await fm.insert(
                {
                    "connector_id": connector_id,
                    "source_field": m["source_field"],
                    "target_field": target,
                    "transform": m.get("transform"),
                    "approved_by": approved_by,
                    "approved_at": now_iso() if target else None,
                    "created_at": now_iso(),
                }
            )
        )
    return saved
