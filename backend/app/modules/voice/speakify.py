"""Turn written facts into speakable text before TTS (architecture §11).

"AED 1,850,000" → "one point eight five million dirhams", "2,300 sq ft" →
"two thousand three hundred square feet", "25 min" → "25 minutes". Purely
deterministic string rewriting; never changes the numbers themselves.
"""
from __future__ import annotations

import re

_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
         "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]

_AED_RE = re.compile(r"\bAED\s?([\d,]+(?:\.\d+)?)\s?(k|m|million|thousand)?\b", re.I)
_AED_AFTER_RE = re.compile(r"\b([\d,]+(?:\.\d+)?)\s?(k|m|million|thousand)?\s?(AED|dirhams?)\b", re.I)
_SQFT_RE = re.compile(r"\b([\d,]+)\s?(sq\.? ?ft|sqft|square feet)\b", re.I)
_PSF_RE = re.compile(r"\bper sq\.? ?ft\b", re.I)
_MIN_RE = re.compile(r"\b(\d+)\s?(min|mins)\b", re.I)
_KM_RE = re.compile(r"\b([\d.]+)\s?km\b", re.I)
_PCT_RE = re.compile(r"\b([\d.]+)\s?%")
_PLAIN_BIG_RE = re.compile(r"\b(\d{1,3}(?:,\d{3})+)\b")


def _to_number(raw: str, unit: str | None) -> float:
    value = float(raw.replace(",", ""))
    if unit:
        u = unit.lower()
        if u in ("k", "thousand"):
            value *= 1_000
        elif u in ("m", "million"):
            value *= 1_000_000
    return value


def _small_words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("" if n % 10 == 0 else f" {_ONES[n % 10]}")
    if n < 1000:
        rest = n % 100
        return f"{_ONES[n // 100]} hundred" + ("" if rest == 0 else f" {_small_words(rest)}")
    return str(n)


def number_words(value: float) -> str:
    """Spoken form that never loses digits.

    Round millions read as "one point eight five million"; anything else is
    spelled out in full ("one million two hundred thirty four thousand five
    hundred sixty seven").
    """
    n = int(round(value))
    if n >= 1_000_000 and n % 10_000 == 0:
        whole, rest = divmod(n, 1_000_000)
        spoken = _small_words(whole)
        if rest:
            frac = f"{rest // 10_000:02d}".rstrip("0")
            spoken += " point " + " ".join(_ONES[int(d)] for d in frac)
        return f"{spoken} million"
    if n < 1000:
        return _small_words(n)
    parts: list[str] = []
    millions, n = divmod(n, 1_000_000)
    if millions:
        parts.append(f"{_small_words(millions)} million")
    thousands, rest = divmod(n, 1000)
    if thousands:
        parts.append(f"{_small_words(thousands)} thousand")
    if rest:
        parts.append(_small_words(rest))
    return " ".join(parts)


def _aed(match: re.Match[str]) -> str:
    return f"{number_words(_to_number(match.group(1), match.group(2)))} dirhams"


def speakify(text: str, language: str = "en") -> str:
    if language == "ar":
        # Arabic TTS models read digits fine; only expand the currency token.
        text = re.sub(r"\bAED\b", "درهم", text)
        return text
    text = _AED_RE.sub(_aed, text)
    text = _AED_AFTER_RE.sub(_aed, text)
    text = _SQFT_RE.sub(lambda m: f"{number_words(_to_number(m.group(1), None))} square feet", text)
    text = _PSF_RE.sub("per square foot", text)
    text = _MIN_RE.sub(lambda m: f"{m.group(1)} minute{'s' if m.group(1) != '1' else ''}", text)
    text = _KM_RE.sub(lambda m: f"{m.group(1)} kilometres", text)
    text = _PCT_RE.sub(lambda m: f"{m.group(1)} percent", text)
    text = _PLAIN_BIG_RE.sub(lambda m: number_words(_to_number(m.group(1), None)), text)
    return re.sub(r"\s{2,}", " ", text).strip()
