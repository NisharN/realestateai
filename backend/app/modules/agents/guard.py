"""Guard — pure code check of an LLM reply against FACTS (architecture §8.7).

Returns the reply if safe, else ``None`` so the caller renders the template.
"""
from __future__ import annotations

import re
from typing import Any

from app.modules.agents.extractor import detect_language

BANNED_PHRASES = (
    "guaranteed", "guarantee", "approved for a mortgage", "you are approved", "best price",
    "lowest price", "risk-free", "no risk", "legal advice", "i promise",
    "مضمون", "ضمان", "أفضل سعر", "أقل سعر", "بدون مخاطر",
)

_NUMBER_RE = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s*(m|mn|million|k|thousand|مليون|ألف|الف)?(?![\w])", re.I)
_MULT = {"m": 1e6, "mn": 1e6, "million": 1e6, "مليون": 1e6, "k": 1e3, "thousand": 1e3, "ألف": 1e3, "الف": 1e3}


def _numbers_in(text: str) -> list[float]:
    out: list[float] = []
    for m in _NUMBER_RE.finditer(text):
        raw = m.group(1).replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        suffix = (m.group(2) or "").lower()
        out.append(value * _MULT.get(suffix, 1))
    return out


def _flatten_numbers(obj: Any, acc: set[float]) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        acc.add(float(obj))
    elif isinstance(obj, str):
        for n in _numbers_in(obj):
            acc.add(n)
    elif isinstance(obj, dict):
        for v in obj.values():
            _flatten_numbers(v, acc)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _flatten_numbers(v, acc)


def _close(a: float, allowed: set[float]) -> bool:
    for b in allowed:
        if b == 0:
            if a == 0:
                return True
            continue
        if abs(a - b) / max(abs(b), 1) <= 0.02:
            return True
    return False


SMALL_SAFE_NUMBERS = {float(n) for n in range(0, 25)}  # counts like "3 options", bedrooms, hours


def check(reply: str | None, facts: dict[str, Any], *, language: str, max_sentences: int) -> str | None:
    if not reply or not reply.strip():
        return None
    text = reply.strip()
    lowered = text.lower()
    if any(p in lowered for p in BANNED_PHRASES):
        return None

    allowed: set[float] = set(SMALL_SAFE_NUMBERS)
    _flatten_numbers(facts, allowed)
    for n in _numbers_in(text):
        if not _close(n, allowed):
            return None

    if "titles" in facts:
        mentioned_titles = [t for t in facts.get("titles", []) if t]
        # property mentions are validated by title presence only when the reply
        # looks like it names a listing ("Tower", "Residence", "Villa ...")
        if re.search(r"\b(tower|residence|residences|villas?|heights|gate|bay|creek|park)\b", lowered) and mentioned_titles:
            if not any(t.lower().split(" - ")[0] in lowered for t in mentioned_titles):
                return None

    if detect_language(text, language) != language:
        return None

    sentences = [s for s in re.split(r"(?<=[.!?؟])\s+", text) if s.strip()]
    if len(sentences) > max_sentences:
        text = " ".join(sentences[:max_sentences])
    if text.count("?") + text.count("؟") > 1:
        return None
    return text
