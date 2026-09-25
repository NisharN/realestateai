"""Structured lead extraction from unstructured inbound channels.

Two sources feed this:

* **Gmail** — portal notification e-mails (Bayut, Dubizzle, Property Finder,
  website forms, developer referral mails). Deterministic regex extraction
  runs first; when an LLM provider is configured a typed JSON extraction
  refines missing fields. The result is a normal raw lead payload so it goes
  through the same clean → validate → merge → score pipeline as any CRM pull.
* **Meta Lead Ads** — instant-form ``field_data`` arrays fetched from the
  Graph API after a leadgen webhook, mapped by well-known field names.
"""
from __future__ import annotations

import base64
import html
import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from app.modules.llm.gateway import LLMUnavailable, get_gateway

logger = logging.getLogger(__name__)

PORTAL_SENDERS: dict[str, str] = {
    "bayut.com": "bayut",
    "dubizzle.com": "dubizzle",
    "propertyfinder.ae": "property_finder",
    "propertyfinder.com": "property_finder",
    "houza.com": "houza",
}

_PHONE = re.compile(r"(?:\+?971|0)?[\s\-.]?(?:5\d|4)[\s\-.]?\d{3}[\s\-.]?\d{4}\b|\+\d{7,15}")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_REFERENCE = re.compile(r"(?:ref(?:erence)?(?:\s*(?:no|number|#))?|listing(?:\s*id)?|property\s*id)\s*[:#\-]?\s*([A-Z0-9][A-Z0-9\-_/]{3,})", re.IGNORECASE)
_BUDGET = re.compile(r"(?:budget|up to|max(?:imum)?)\s*(?:is|of|around|about|approx\.?|roughly|:|-)?\s*(?:aed)?\s*([\d.,]+)\s*(m|mn|million|k)?", re.IGNORECASE)
_NAME_LINE = re.compile(r"(?:^|\n)\s*(?:name|client|buyer|lead|from)\s*[:\-]\s*([A-Za-z\u0600-\u06FF][A-Za-z\u0600-\u06FF' .\-]{1,60})", re.IGNORECASE)
_MESSAGE_LINE = re.compile(r"(?:^|\n)\s*(?:message|enquiry|inquiry|comments?|notes?)\s*[:\-]\s*(.+?)(?:\n\s*\n|\Z)", re.IGNORECASE | re.DOTALL)
_BEDROOMS = re.compile(r"\b(\d|studio)\s*(?:br|bed|bedroom)s?\b", re.IGNORECASE)
_TAGS = re.compile(r"<[^>]+>")

AREA_CANONICAL: dict[str, str] = {
    "jvc": "Jumeirah Village Circle",
    "jumeirah village circle": "Jumeirah Village Circle",
    "dubai hills": "Dubai Hills Estate",
    "jbr": "JBR",
    "jlt": "JLT",
    "mbr city": "MBR City",
    "downtown": "Downtown Dubai",
}

AREAS = (
    "palm jumeirah", "dubai marina", "downtown", "business bay", "jvc", "jumeirah village circle", "dubai hills",
    "arabian ranches", "damac hills", "jbr", "dubai creek harbour", "mbr city", "meydan", "al barsha", "mirdif",
    "jlt", "dubai south", "emaar beachfront", "bluewaters", "dubai islands", "tilal al ghaf", "the springs",
    "the meadows", "emirates hills", "jumeirah", "al furjan", "motor city", "sports city", "silicon oasis",
    "yas island", "saadiyat", "al reem", "sharjah", "ajman",
)


class ExtractedLead(BaseModel):
    """Typed shape used for both regex and LLM extraction."""

    name: str | None = None
    phone: str | None = None
    email: str | None = None
    message: str | None = None
    listing_reference: str | None = None
    area: str | None = None
    property_type: str | None = None
    bedrooms: str | None = None
    budget_max_aed: int | None = None
    purpose: str | None = Field(default=None, description="buy | rent | invest")
    source: str | None = None
    confidence: float = 0.5


def strip_html(raw: str) -> str:
    text = _TAGS.sub("\n", raw or "")
    text = html.unescape(text)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", text)).strip()


def _to_aed(amount: str, unit: str | None) -> int | None:
    try:
        n = float(amount.replace(",", ""))
    except ValueError:
        return None
    u = (unit or "").lower()
    if u in ("m", "mn", "million"):
        n *= 1_000_000
    elif u == "k":
        n *= 1_000
    n = int(n)
    return n if 50_000 <= n <= 500_000_000 else None


def normalize_phone(raw: str | None) -> str | None:
    """UAE-first E.164: ``050 123 4567`` → ``+971501234567``; international numbers keep their prefix."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    digits = digits.removeprefix("00")
    if digits.startswith("971"):
        return f"+{digits}"
    if digits.startswith("0") and len(digits) in (9, 10):
        return f"+971{digits[1:]}"
    if len(digits) == 9 and digits[0] in "45":
        return f"+971{digits}"
    return f"+{digits}" if 7 <= len(digits) <= 15 else None


def canonical_area(area: str | None) -> str | None:
    if not area:
        return None
    return AREA_CANONICAL.get(area.lower(), area.title())


def source_from_sender(sender: str | None) -> str:
    s = (sender or "").lower()
    for domain, src in PORTAL_SENDERS.items():
        if domain in s:
            return src
    return "email"


def extract_lead_rules(subject: str, body: str, sender: str | None = None) -> ExtractedLead:
    text = strip_html(body)
    blob = f"{subject}\n{text}"
    low = blob.lower()
    phone = _PHONE.search(text)
    emails = [e for e in _EMAIL.findall(blob) if not any(d in e.lower() for d in PORTAL_SENDERS) and "noreply" not in e.lower() and "no-reply" not in e.lower()]
    name = _NAME_LINE.search(blob)
    ref = _REFERENCE.search(blob)
    budget = _BUDGET.search(blob)
    msg = _MESSAGE_LINE.search(blob)
    beds = _BEDROOMS.search(blob)
    area = next((a for a in AREAS if a in low), None)
    ptype = next((t for t in ("villa", "townhouse", "penthouse", "apartment", "flat", "studio", "plot", "office") if re.search(rf"\b{t}s?\b", low)), None)
    purpose = "rent" if re.search(r"\b(rent|rental|lease|yearly|annual)\b", low) else "invest" if re.search(r"\b(invest|roi|yield|off-plan|payment plan)\b", low) else "buy" if re.search(r"\b(buy|purchase|sale|for sale)\b", low) else None
    filled = sum(1 for v in (phone, name, ref, area, emails) if v)
    return ExtractedLead(
        name=(name.group(1).strip() if name else None),
        phone=normalize_phone(phone.group(0)) if phone else None,
        email=(emails[0] if emails else None),
        message=(msg.group(1).strip()[:600] if msg else (text[:400] or None)),
        listing_reference=(ref.group(1) if ref else None),
        area=canonical_area(area),
        property_type="apartment" if ptype == "flat" else ptype,
        bedrooms=(beds.group(1).lower() if beds else None),
        budget_max_aed=(_to_aed(budget.group(1), budget.group(2)) if budget else None),
        purpose=purpose,
        source=source_from_sender(sender),
        confidence=min(0.95, 0.35 + 0.12 * filled),
    )


async def extract_lead(subject: str, body: str, sender: str | None = None, *, use_llm: bool = True) -> ExtractedLead:
    """Regex first; typed LLM extraction fills gaps when a provider is configured. Never raises."""
    base = extract_lead_rules(subject, body, sender)
    gw = get_gateway()
    if not use_llm or not gw.available or (base.phone and base.name and base.area):
        return base
    text = strip_html(body)[:4000]
    try:
        llm = await gw.complete_json(
            [
                {"role": "system", "content": "Extract the property enquiry from this e-mail into JSON. Fields: name, phone (E.164 if possible), email, message, listing_reference, area (Dubai/UAE community), property_type, bedrooms, budget_max_aed (integer AED), purpose (buy|rent|invest). Use null when unknown. Never invent contact details."},
                {"role": "user", "content": f"Subject: {subject}\nFrom: {sender or ''}\n\n{text}"},
            ],
            ExtractedLead,
            purpose="lead.extract",
        )
    except LLMUnavailable:
        return base
    base_data = base.model_dump()
    llm_data = llm.model_dump()
    merged = {k: (llm_data[k] if v in (None, "") and llm_data.get(k) not in (None, "") else v) for k, v in base_data.items() if k not in ("confidence", "source")}
    merged["phone"] = normalize_phone(merged.get("phone")) or base.phone
    merged["area"] = canonical_area(merged.get("area"))
    return ExtractedLead(**merged, source=base.source, confidence=max(base.confidence, 0.8))


def to_raw_payload(lead: ExtractedLead, *, external_id: str | None, source: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "external_id": external_id,
        "name": lead.name,
        "phone": lead.phone,
        "email": lead.email,
        "message": lead.message,
        "listing_reference": lead.listing_reference,
        "area_preference": lead.area,
        "property_type": lead.property_type,
        "bedrooms": lead.bedrooms,
        "budget_max_aed": lead.budget_max_aed,
        "purpose": lead.purpose,
        "source": lead.source if lead.source and lead.source != "email" else source,
        "extraction_confidence": lead.confidence,
        **(extra or {}),
    }
    return {k: v for k, v in payload.items() if v not in (None, "")}


# --------------------------------------------------------------------------- Gmail


def gmail_message_text(msg: dict[str, Any]) -> tuple[str, str, str]:
    """(subject, sender, body) from a Gmail ``users.messages.get?format=full`` payload."""
    payload = msg.get("payload") or {}
    headers = {(h.get("name") or "").lower(): h.get("value") or "" for h in payload.get("headers") or []}
    parts: list[str] = []

    def walk(p: dict[str, Any]) -> None:
        data = ((p.get("body") or {}).get("data")) or ""
        mime = p.get("mimeType") or ""
        if data and mime.startswith("text/"):
            try:
                parts.append(base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace"))
            except ValueError:
                pass
        for child in p.get("parts") or []:
            walk(child)

    walk(payload)
    body = "\n".join(parts) or msg.get("snippet") or ""
    return headers.get("subject", ""), headers.get("from", ""), body


# --------------------------------------------------------------------------- Meta Lead Ads

_META_FIELDS = {
    "full_name": "name", "name": "name", "first_name": "first_name", "last_name": "last_name",
    "phone_number": "phone", "phone": "phone", "mobile": "phone", "whatsapp": "phone",
    "email": "email", "budget": "budget", "budget_aed": "budget", "area": "area", "community": "area", "location": "area",
    "property_type": "property_type", "bedrooms": "bedrooms", "purpose": "purpose", "message": "message", "comments": "message",
    "timeline": "timeline", "when_are_you_looking_to_buy": "timeline",
}
_META_FUZZY: tuple[tuple[str, str], ...] = (
    ("phone", "phone"), ("mobile", "phone"), ("whatsapp", "phone"), ("email", "email"), ("full_name", "name"), ("name", "name"),
    ("budget", "budget"), ("area", "area"), ("community", "area"), ("location", "area"), ("bedroom", "bedrooms"),
    ("property_type", "property_type"), ("type_of_property", "property_type"), ("message", "message"), ("comment", "message"),
    ("timeline", "timeline"), ("when", "timeline"), ("purpose", "purpose"), ("buy_or_rent", "purpose"),
)


def meta_lead_payload(lead: dict[str, Any], *, form_id: str | None = None, page_id: str | None = None) -> dict[str, Any]:
    """Map a Graph API leadgen object (``field_data`` list) to a raw lead payload."""
    fields: dict[str, Any] = {}
    for f in lead.get("field_data") or []:
        key = str(f.get("name") or "").lower().strip()
        vals = f.get("values") or []
        if not vals:
            continue
        mapped = _META_FIELDS.get(key)
        if mapped is None:
            mapped = next((target for token, target in _META_FUZZY if token in key), None)
        if mapped:
            fields[mapped] = vals[0]
        else:
            fields.setdefault("answers", {})[key] = vals[0]
    budget = fields.pop("budget", None)
    if budget is not None:
        m = re.search(r"([\d.,]+)\s*(m|mn|million|k)?", str(budget), re.IGNORECASE)
        fields["budget_max_aed"] = _to_aed(m.group(1), m.group(2)) if m else None
    first, last = fields.pop("first_name", None), fields.pop("last_name", None)
    full = fields.pop("name", None)
    if full and not (first or last):
        first, _, last = str(full).strip().partition(" ")
    if "phone" in fields:
        fields["phone"] = normalize_phone(str(fields["phone"])) or fields["phone"]
    payload = {
        "external_id": lead.get("id"),
        "first_name": first or None,
        "last_name": last or None,
        **fields,
        "area_preference": fields.pop("area", None),
        "source": "meta_lead_ads",
        "campaign": {"form_id": form_id or lead.get("form_id"), "page_id": page_id, "ad_id": lead.get("ad_id"), "adset_id": lead.get("adset_id"), "campaign_id": lead.get("campaign_id"), "created_time": lead.get("created_time")},
        "raw": lead,
    }
    payload.pop("area", None)
    return {k: v for k, v in payload.items() if v not in (None, "", {})}
