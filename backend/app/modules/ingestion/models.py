"""Ingestion data contracts (architecture §6.2, §6.3)."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

RecordStatus = Literal[
    "landed", "mapped", "cleaned", "validated", "merged", "enriched", "published", "review", "error"
]

SOURCES = ("pf", "bayut", "dubizzle", "web", "referral", "whatsapp", "crm", "csv", "webhook", "manual", "other")

# Canonical target fields a connector field map may point at.
CANONICAL_FIELDS: tuple[str, ...] = (
    "first_name", "last_name", "full_name", "phone", "email", "message", "budget", "budget_min", "budget_max",
    "area", "property_type", "bedrooms", "purpose", "timeline", "payment", "language", "source",
    "listing_ref", "external_id", "created_at", "consent",
)


def content_hash(payload: dict[str, Any], external_id: str | None = None) -> str:
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(f"{external_id or ''}|{body}".encode("utf-8")).hexdigest()


class RawRecord(BaseModel):
    external_id: str | None = None
    payload: dict[str, Any]
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_hint: str | None = None

    def hash(self) -> str:
        return content_hash(self.payload, self.external_id)


class CanonicalLead(BaseModel):
    """Draft produced by Map, refined by Clean, checked by Validate."""

    first_name: str | None = None
    last_name: str | None = None
    phone_e164: str | None = None
    phone_raw: str | None = None
    email: str | None = None
    message: str | None = None
    language: str = "en"
    purpose: str | None = None
    budget_min_aed: float | None = None
    budget_max_aed: float | None = None
    budget_period: str | None = None
    budget_raw: str | None = None
    community_ids: list[str] = Field(default_factory=list)
    area_raw: str | None = None
    property_type: str | None = None
    bedrooms: int | None = None
    timeline: str | None = None
    payment: str | None = None
    source: str = "other"
    listing_ref: str | None = None
    external_id: str | None = None
    enquiry_at: datetime | None = None
    consent: dict[str, Any] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

    def has_contact(self) -> bool:
        return bool(self.phone_e164 or self.email)


class ValidationResult(BaseModel):
    ok: bool
    reasons: list[str] = Field(default_factory=list)
    suggested_fix: dict[str, Any] = Field(default_factory=dict)


class MergeResult(BaseModel):
    lead_id: str
    created: bool
    matched_by: Literal["phone", "email", "name_recent", "none"]
    needs_review: bool = False
    suppressed: bool = False
    changed_fields: list[str] = Field(default_factory=list)


class PipelineOutcome(BaseModel):
    raw_record_id: str
    status: RecordStatus
    lead_id: str | None = None
    created: bool = False
    reasons: list[str] = Field(default_factory=list)
