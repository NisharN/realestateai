"""Extractor output schema (architecture §8.4). Shared by extractor and policy."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Intent = Literal[
    "provide_info", "ask_property", "ask_area", "compare", "request_viewing",
    "request_human", "objection", "smalltalk", "not_interested", "stop", "unclear",
    "agree", "disagree", "goodbye",
]
Objection = Literal["price", "location", "size", "payment", "handover", "other"]
Timeline = Literal["asap", "1_month", "3_months", "6_months", "12_months", "later", "unknown"]
Purpose = Literal["buy", "rent", "invest"]
Payment = Literal["cash", "mortgage_preapproved", "mortgage_not_started", "unknown"]


class Reaction(BaseModel):
    property_id: str | None = None
    property_index: int | None = None  # 1-based position in the last shortlist
    reaction: Literal["liked", "rejected", "neutral"]
    reason: str | None = None


class Slots(BaseModel):
    budget_text: str | None = None
    areas: list[str] = Field(default_factory=list)
    bedrooms: int | None = None
    property_type: str | None = None
    purpose: Purpose | None = None
    timeline: Timeline | None = None
    payment: Payment | None = None
    end_use: str | None = None
    must_haves: list[str] = Field(default_factory=list)
    name: str | None = None
    location_prefs: dict[str, str] = Field(default_factory=dict)  # e.g. {"work": "DIFC", "school": "..."}

    @field_validator("bedrooms")
    @classmethod
    def _bedrooms_range(cls, v: int | None) -> int | None:
        if v is None:
            return None
        return max(0, min(v, 10))


class ExtractedFacts(BaseModel):
    intent: Intent = "unclear"
    language: Literal["en", "ar"] = "en"
    slots: Slots = Field(default_factory=Slots)
    reactions: list[Reaction] = Field(default_factory=list)
    objection: Objection | None = None
    asks_why: bool = False
    why_field: str | None = None  # slot the buyer is asking about ("why do you need my budget?")
    wants_area_recommendation: bool = False  # "which areas give good yield?" with no area named
    confidence: float = 0.0
    # Filled by the rule extractor / merge step, never by the LLM directly:
    budget_ambiguous: bool = False
    budget_question: str | None = None
    area_candidates: list[str] = Field(default_factory=list)  # community ids resolved with confidence >= 0.8
    area_unresolved: bool = False  # buyer named a place we could not resolve
    focus_property_id: str | None = None  # card the buyer clicked; resolved against shown properties
    rules_only: bool = False
    text: str = ""


class LLMFacts(BaseModel):
    """Strict shape the LLM must return; converted into ExtractedFacts."""
    intent: Intent = "unclear"
    language: Literal["en", "ar"] = "en"
    slots: Slots = Field(default_factory=Slots)
    reactions: list[Reaction] = Field(default_factory=list)
    objection: Objection | None = None
    confidence: float = 0.0
