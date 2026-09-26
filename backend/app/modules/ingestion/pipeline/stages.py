"""Pure stage functions: map → clean → validate (architecture §6.3).

Each function is deterministic and side-effect free so acceptance tests in
§6.6 can run without a database.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import phonenumbers

from app.modules.agents.extractor import detect_language
from app.modules.geo.communities import resolve_area
from app.modules.ingestion.field_maps import suggest_field_map
from app.modules.ingestion.models import CanonicalLead, ValidationResult
from app.services.budget_extraction import extract_budget

_SOURCE_ALIASES = {
    "pf": "pf", "propertyfinder": "pf", "property finder": "pf",
    "bayut": "bayut", "dubizzle": "dubizzle",
    "web": "web", "website": "web", "site": "web", "landing": "web", "form": "web",
    "referral": "referral", "referred": "referral",
    "whatsapp": "whatsapp", "wa": "whatsapp",
    "crm": "crm", "generic_crm": "crm", "realestate_crm": "crm", "ai_agent": "crm", "hubspot": "crm", "zoho": "crm", "salesforce": "crm", "bitrix": "crm", "bitrix24": "crm",
    "csv": "csv", "webhook": "webhook", "manual": "manual",
    "broker_api": "broker_api", "developer_api": "broker_api", "meta_lead_ads": "meta_lead_ads", "meta": "meta_lead_ads",
    "facebook": "meta_lead_ads", "instagram": "meta_lead_ads", "gmail": "gmail", "email": "gmail", "voice_notes": "whatsapp",
}
_TYPE_ALIASES = {
    "apartment": "apartment", "apt": "apartment", "flat": "apartment", "studio": "apartment", "penthouse": "penthouse",
    "villa": "villa", "house": "villa", "townhouse": "townhouse", "th": "townhouse", "duplex": "townhouse",
    "plot": "plot", "land": "plot", "office": "commercial", "commercial": "commercial", "retail": "commercial", "shop": "commercial",
}
_PURPOSE_ALIASES = {
    "buy": "buy", "purchase": "buy", "sale": "buy", "for sale": "buy", "buying": "buy",
    "rent": "rent", "rental": "rent", "lease": "rent", "renting": "rent", "for rent": "rent",
    "invest": "invest", "investment": "invest", "investor": "invest",
}
_TIMELINE_ALIASES = {
    "asap": "immediate", "immediately": "immediate", "now": "immediate", "urgent": "immediate", "this month": "immediate",
    "1-3 months": "1_3_months", "1 to 3 months": "1_3_months", "3 months": "1_3_months", "soon": "1_3_months",
    "3-6 months": "3_6_months", "6 months": "3_6_months", "later": "6_plus_months", "6+ months": "6_plus_months",
    "next year": "6_plus_months", "browsing": "browsing", "just looking": "browsing", "exploring": "browsing",
}
_PAYMENT_ALIASES = {
    "cash": "cash", "mortgage": "mortgage", "finance": "mortgage", "financing": "mortgage", "loan": "mortgage",
    "payment plan": "payment_plan", "installments": "payment_plan", "instalments": "payment_plan",
}
_BEDS_RE = re.compile(r"(\d+)")
_CONSENT_TRUE = {"yes", "true", "1", "y", "opted_in", "opt-in", "opt in", "granted"}


def _alias(value: Any, aliases: dict[str, str]) -> str | None:
    if value is None:
        return None
    key = str(value).strip().lower()
    if key in aliases:
        return aliases[key]
    for name, target in aliases.items():
        if name in key:
            return target
    return None


# ---------------------------------------------------------------- 1 Map


def map_record(payload: dict[str, Any], field_map: dict[str, str] | None) -> CanonicalLead:
    """Apply the approved field map; fall back to header suggestions when none exists."""
    if not field_map:
        field_map = {
            s["source_field"]: s["target_field"]
            for s in suggest_field_map(list(payload.keys()), {k: [str(v)] for k, v in payload.items()})
            if s["target_field"]
        }
    draft = CanonicalLead()
    mapped: dict[str, Any] = {}
    for source_field, value in payload.items():
        target = field_map.get(source_field)
        if not target or value in (None, ""):
            if value not in (None, ""):
                draft.extra[source_field] = value
            continue
        if target == "area" and "area" in mapped:
            mapped["area"] = f"{mapped['area']}, {value}"
        elif target == "message" and "message" in mapped:
            mapped["message"] = f"{mapped['message']}\n{value}"
        else:
            mapped[target] = value

    if mapped.get("full_name") and not (mapped.get("first_name") or mapped.get("last_name")):
        first, _, last = str(mapped["full_name"]).strip().partition(" ")
        mapped["first_name"], mapped["last_name"] = first, last or None
    draft.first_name = _str(mapped.get("first_name"))
    draft.last_name = _str(mapped.get("last_name"))
    draft.phone_raw = _str(mapped.get("phone"))
    draft.email = _str(mapped.get("email"))
    draft.message = _str(mapped.get("message"))
    draft.area_raw = _str(mapped.get("area"))
    draft.listing_ref = _str(mapped.get("listing_ref"))
    draft.external_id = _str(mapped.get("external_id"))
    budget_bits = [str(mapped[k]) for k in ("budget", "budget_min", "budget_max") if mapped.get(k) not in (None, "")]
    if mapped.get("budget_min") and mapped.get("budget_max"):
        draft.budget_raw = f"{mapped['budget_min']} to {mapped['budget_max']}"
    elif budget_bits:
        draft.budget_raw = budget_bits[0]
    draft.extra.update({k: mapped[k] for k in ("property_type", "bedrooms", "purpose", "timeline", "payment", "language", "source", "created_at", "consent") if k in mapped})
    return draft


def _str(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


# -------------------------------------------------------------- 2 Clean


def clean_phone(raw: str | None, region: str = "AE") -> str | None:
    if not raw:
        return None
    candidate = raw.strip()
    if candidate.startswith("00"):
        candidate = "+" + candidate[2:]
    try:
        parsed = phonenumbers.parse(candidate, region)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def clean_record(draft: CanonicalLead) -> CanonicalLead:
    d = draft.model_copy(deep=True)
    extra = d.extra
    d.phone_e164 = clean_phone(d.phone_raw)
    if d.phone_raw and not d.phone_e164:
        d.warnings.append("phone_invalid")
    if d.email:
        d.email = d.email.strip().lower()
        if "@" not in d.email:
            d.warnings.append("email_invalid")
            d.email = None
    if d.first_name and not d.last_name and " " in d.first_name:
        d.first_name, _, d.last_name = d.first_name.partition(" ")

    d.purpose = _alias(extra.pop("purpose", None), _PURPOSE_ALIASES)
    d.property_type = _alias(extra.pop("property_type", None), _TYPE_ALIASES)
    d.timeline = _alias(extra.pop("timeline", None), _TIMELINE_ALIASES)
    d.payment = _alias(extra.pop("payment", None), _PAYMENT_ALIASES)
    beds = extra.pop("bedrooms", None)
    if beds is not None:
        if str(beds).strip().lower().startswith("studio"):
            d.bedrooms = 0
        else:
            m = _BEDS_RE.search(str(beds))
            d.bedrooms = int(m.group(1)) if m else None
    lang = extra.pop("language", None)
    d.language = "ar" if str(lang or "").lower().startswith("ar") else ("en" if lang else detect_language(d.message or "", "en"))
    src = _alias(extra.pop("source", None), _SOURCE_ALIASES) or _alias(extra.get("__source_hint"), _SOURCE_ALIASES)
    d.source = src or d.source
    extra.pop("__source_hint", None)

    budget_text = d.budget_raw or (d.message if d.message and any(ch.isdigit() for ch in d.message) else None)
    if budget_text:
        b = extract_budget(budget_text)
        # CRM exports rarely carry a currency; AED is the default for a Dubai workspace.
        lo, hi = (b.amount_min_aed, b.amount_max_aed) if b.currency else (b.amount_min, b.amount_max)
        if hi is not None or lo is not None:
            d.budget_min_aed = lo
            d.budget_max_aed = hi
            if not b.currency:
                d.warnings.append("budget_currency_assumed_aed")
            d.budget_period = b.period or ("year" if d.purpose == "rent" else "total" if d.purpose in ("buy", "invest") else None)
            if not d.purpose and b.intent:
                d.purpose = b.intent
        elif d.budget_raw:
            d.warnings.append("budget_unparsed")

    area_text = " ".join(t for t in (d.area_raw, d.message) if t)
    if area_text:
        d.community_ids = [m.community.id for m in resolve_area(area_text)]
        if d.area_raw and not d.community_ids:
            d.warnings.append("area_unresolved")

    created = extra.pop("created_at", None)
    if created:
        d.enquiry_at = _parse_dt(str(created))
        if d.enquiry_at is None:
            d.warnings.append("created_at_unparsed")
    consent = extra.pop("consent", None)
    if consent is not None:
        d.consent = {"marketing": str(consent).strip().lower() in _CONSENT_TRUE, "source": d.source, "recorded_at": datetime.now(timezone.utc).isoformat()}
    return d


def _parse_dt(value: str) -> datetime | None:
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d/%m/%Y %H:%M", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            dt = datetime.strptime(value.strip().replace("Z", "+0000"), fmt)
        except ValueError:
            continue
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# ----------------------------------------------------------- 3 Validate

BUDGET_BOUNDS = {"buy": (100_000, 500_000_000), "invest": (100_000, 500_000_000), "rent": (10_000, 5_000_000)}


def validate_record(lead: CanonicalLead, suppression: set[str] | None = None) -> ValidationResult:
    reasons: list[str] = []
    fix: dict[str, Any] = {}
    if not lead.has_contact():
        reasons.append("missing_contact")
        if lead.phone_raw:
            fix["phone"] = lead.phone_raw
    if lead.phone_raw and not lead.phone_e164:
        reasons.append("phone_invalid")
        fix["phone"] = lead.phone_raw
    if lead.purpose in BUDGET_BOUNDS and lead.budget_max_aed is not None:
        lo, hi = BUDGET_BOUNDS[lead.purpose]
        if not (lo <= lead.budget_max_aed <= hi):
            reasons.append("budget_out_of_bounds")
            fix["budget"] = lead.budget_raw
    if suppression and ((lead.phone_e164 and lead.phone_e164 in suppression) or (lead.email and lead.email in suppression)):
        reasons.append("suppressed")
    return ValidationResult(ok=not reasons, reasons=reasons, suggested_fix=fix)
