"""TypeSafe AI "Jev" System One client for lead scoring and qualification.

Jev is not a text model: a request carries a `state` (the lead as JSON) plus typed
questions (choice / score / noul) and returns one calibrated answer per question.
Endpoint, body and answer shapes follow TypeSafe's System One API reference
(POST https://api.typesafe.ai/v1/systemone, Bearer auth).
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.config import get_settings

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.typesafe.ai"
DEFAULT_MODEL = "jev-latest"
TIMEOUT_S = 6.0

Band = Literal["hot", "warm", "cold"]

# Ordered levels for the "readiness" score. Index -> 0..100 via SCORE_POINTS.
READINESS_LEVELS: tuple[str, ...] = (
    "browsing with no budget, timeline or area; not ready to transact",
    "early interest: one of budget, area or timeline known, no urgency",
    "engaged: budget and area known, timeline within a year, asking questions",
    "serious: realistic budget, area and type known, timeline under six months",
    "ready to transact: cash or pre-approved, timeline under three months, asked for viewing or price",
)
SCORE_POINTS: tuple[int, ...] = (10, 30, 55, 75, 92)

QUESTIONS: dict[str, dict[str, Any]] = {
    "band": {
        "type": "choice",
        "instructions": "How should a UAE property broker prioritise this lead right now?",
        "criteria": {
            "hot": "contact within the hour: clear intent, realistic budget, short timeline or viewing/price request",
            "warm": "follow up this week: genuine interest but budget, timeline or financing still open",
            "cold": "nurture only: vague, unrealistic budget, far-off timeline, or no engagement",
        },
    },
    "readiness": {
        "type": "score",
        "instructions": "How close is this lead to a property transaction?",
        "criteria": list(READINESS_LEVELS),
    },
    "intent": {
        "type": "choice",
        "instructions": "What does the lead actually want to do?",
        "criteria": {
            "buy": "buy a home to live in",
            "invest": "buy for rental yield or capital growth",
            "rent": "rent a home",
            "unclear": "cannot tell from the conversation",
        },
    },
    "finance_ready": {
        "type": "noul",
        "instructions": "Does the lead have financing in place (cash, or mortgage pre-approval)?",
    },
    "viewing_intent": {
        "type": "noul",
        "instructions": "Has the lead asked for a viewing, a call with an agent, or specific price details?",
    },
    "needs_human": {
        "type": "noul",
        "instructions": "Should a human broker take over this conversation now?",
    },
}


class JevUnavailable(Exception):
    """Raised when Jev is not configured, unreachable, or returned an unusable reply."""


class _ChoiceAnswer(BaseModel):
    type: Literal["choice"]
    choice: str
    confidence: float = Field(ge=0.0, le=1.0)
    probabilities: dict[str, float] = Field(default_factory=dict)


class _ScoreAnswer(BaseModel):
    type: Literal["score"]
    score: float
    confidence: float = Field(ge=0.0, le=1.0)
    probabilities: dict[str, float] = Field(default_factory=dict)


class _NoulAnswer(BaseModel):
    type: Literal["noul"]
    noul: float = Field(ge=0.0, le=1.0)


class _Reply(BaseModel):
    model: str = ""
    answers: dict[str, _ChoiceAnswer | _ScoreAnswer | _NoulAnswer]
    usage: dict[str, int] = Field(default_factory=dict)


class JevQualification(BaseModel):
    band: Band
    band_confidence: float
    score: int = Field(ge=0, le=100)
    intent: Literal["buy", "invest", "rent", "unclear"]
    finance_ready: float
    viewing_intent: float
    needs_human: float
    model: str
    latency_ms: int
    reasons: list[str]

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump()


ClientFactory = Callable[[], httpx.AsyncClient]
_client_factory: ClientFactory = lambda: httpx.AsyncClient(timeout=TIMEOUT_S)


def set_client_factory(factory: ClientFactory | None) -> None:
    global _client_factory
    _client_factory = factory or (lambda: httpx.AsyncClient(timeout=TIMEOUT_S))


def configured(api_key: str | None = None) -> bool:
    return bool(api_key or get_settings().TYPESAFE_API_KEY)


def _score_from_levels(ans: _ScoreAnswer) -> int:
    """Expected score over the level distribution; falls back to the point estimate."""
    if ans.probabilities:
        total = sum(ans.probabilities.values())
        if total > 0:
            expected = 0.0
            for key, p in ans.probabilities.items():
                try:
                    idx = round(float(key))
                except ValueError:
                    continue
                idx = max(0, min(idx, len(SCORE_POINTS) - 1))
                expected += SCORE_POINTS[idx] * (p / total)
            return int(round(expected))
    idx = max(0, min(int(round(ans.score)), len(SCORE_POINTS) - 1))
    return SCORE_POINTS[idx]


def _reasons(q: dict[str, Any], band: _ChoiceAnswer, ready: _ScoreAnswer, intent: _ChoiceAnswer) -> list[str]:
    out = [f"Jev: {band.choice} ({band.confidence:.0%} confidence)"]
    level = max(0, min(int(round(ready.score)), len(READINESS_LEVELS) - 1))
    out.append(f"Readiness: {READINESS_LEVELS[level]}")
    if intent.choice != "unclear":
        out.append(f"Intent: {intent.choice} ({intent.confidence:.0%})")
    if q["finance_ready"].noul >= 0.6:
        out.append("Financing likely in place")
    if q["viewing_intent"].noul >= 0.6:
        out.append("Asked for a viewing, call or price")
    return out[:5]


async def qualify(state: dict[str, Any], *, api_key: str | None = None, model: str | None = None, base_url: str | None = None) -> JevQualification:
    """Ask Jev to band, score and characterise a lead described by `state` (JSON-able)."""
    settings = get_settings()
    key = api_key or settings.TYPESAFE_API_KEY
    if not key:
        raise JevUnavailable("TYPESAFE_API_KEY not set")
    url = f"{(base_url or settings.TYPESAFE_BASE_URL or DEFAULT_BASE_URL).rstrip('/')}/v1/systemone"
    body = {"model": model or settings.JEV_MODEL or DEFAULT_MODEL, "state": state, "questions": QUESTIONS}
    started = time.monotonic()
    try:
        async with _client_factory() as client:
            resp = await client.post(url, json=body, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    except httpx.HTTPError as exc:
        raise JevUnavailable(f"Jev request failed: {type(exc).__name__}") from exc
    if resp.status_code in (401, 403):
        raise JevUnavailable("Jev rejected the API key")
    if resp.status_code >= 400:
        raise JevUnavailable(f"Jev returned HTTP {resp.status_code}")
    try:
        reply = _Reply.model_validate(resp.json())
    except (ValueError, ValidationError) as exc:
        raise JevUnavailable("Jev reply was not in the expected shape") from exc
    a = reply.answers
    try:
        band, ready, intent = a["band"], a["readiness"], a["intent"]
        finance, viewing, human = a["finance_ready"], a["viewing_intent"], a["needs_human"]
    except KeyError as exc:
        raise JevUnavailable(f"Jev reply missing answer {exc}") from exc
    if not (isinstance(band, _ChoiceAnswer) and isinstance(ready, _ScoreAnswer) and isinstance(intent, _ChoiceAnswer)
            and isinstance(finance, _NoulAnswer) and isinstance(viewing, _NoulAnswer) and isinstance(human, _NoulAnswer)):
        raise JevUnavailable("Jev answered with unexpected question types")
    if band.choice not in ("hot", "warm", "cold") or intent.choice not in ("buy", "invest", "rent", "unclear"):
        raise JevUnavailable("Jev chose an option outside the schema")
    return JevQualification(
        band=band.choice,  # type: ignore[arg-type]
        band_confidence=band.confidence,
        score=_score_from_levels(ready),
        intent=intent.choice,  # type: ignore[arg-type]
        finance_ready=finance.noul,
        viewing_intent=viewing.noul,
        needs_human=human.noul,
        model=reply.model or body["model"],
        latency_ms=int((time.monotonic() - started) * 1000),
        reasons=_reasons(a, band, ready, intent),
    )


async def ping(*, api_key: str | None = None, base_url: str | None = None) -> tuple[bool, str]:
    """Cheap connectivity/credential check against GET /v1/models."""
    settings = get_settings()
    key = api_key or settings.TYPESAFE_API_KEY
    if not key:
        return False, "TYPESAFE_API_KEY not set"
    url = f"{(base_url or settings.TYPESAFE_BASE_URL or DEFAULT_BASE_URL).rstrip('/')}/v1/models"
    try:
        async with _client_factory() as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {key}"})
    except httpx.HTTPError as exc:
        return False, f"Jev unreachable: {type(exc).__name__}"
    if resp.status_code in (401, 403):
        return False, "Jev rejected the API key"
    if resp.status_code >= 400:
        return False, f"Jev returned HTTP {resp.status_code}"
    return True, f"Jev reachable ({settings.JEV_MODEL or DEFAULT_MODEL})"
