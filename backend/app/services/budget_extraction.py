"""Structured budget + currency extraction.

Why this exists (PILOT.md, feature #2): the single most damaging failure mode
in this product is confidently misreading a budget. In Dubai a lead types
"1.2" and means AED 1.2M; another types "80" and means AED 80k *per year* in
rent; an overseas investor types "500k" and means USD. Getting this wrong
produces a beautifully-worded WhatsApp message quoting the wrong price band,
which destroys trust on the first touch.

The rule enforced here: never guess a currency or a period. Extract what is
*explicitly* stated, and when the input is ambiguous, return
``needs_clarification`` with a specific question instead of picking a value.
Downstream code must not paper over that by defaulting.

Pure functions, no I/O, no LLM. This is deliberately deterministic so it can
be tested exhaustively and so its behaviour never drifts with a model update.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# Rough AED per unit. Only used to normalise for comparison/scoring, never to
# silently rewrite what the lead said.
FX_TO_AED = {
    "AED": 1.0,
    "USD": 3.6725,   # AED is pegged to USD
    "GBP": 4.65,
    "EUR": 3.98,
    "INR": 0.044,
}

CURRENCY_PATTERNS = [
    (r"\b(aed|dhs?|dirhams?)\b", "AED"),
    (r"د\.إ|درهم", "AED"),
    (r"\b(usd|dollars?)\b|\$", "USD"),
    (r"\b(gbp|pounds?|sterling)\b|£", "GBP"),
    (r"\b(eur|euros?)\b|€", "EUR"),
    (r"\b(inr|rupees?)\b|₹", "INR"),
]

# "per year", "a year", "annually", "p.a.", "yearly", "/yr"
PER_YEAR = re.compile(
    r"(per\s*(year|annum)|a\s*year|annual(ly)?|yearly|p\.?a\.?\b|/\s*(yr|year))",
    re.I,
)
# "per month", "a month", "monthly", "/mo"
PER_MONTH = re.compile(r"(per\s*month|a\s*month|monthly|/\s*(mo|month))", re.I)

RENT_HINT = re.compile(r"\b(rent|rental|renting|lease|leasing|tenant)\b", re.I)
# invest\w* so "investor" and "investment" count, not just "invest".
BUY_HINT = re.compile(
    r"\b(buy|buying|purchase|purchasing|own|owner|mortgage|invest\w*|off-?plan|freehold)\b",
    re.I,
)

# 1.2m / 850k / 1,200,000 / 2 million / 75 lakh
NUMBER = re.compile(
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
    r"(?P<suffix>m\b|mn\b|million\b|k\b|thousand\b|cr\b|crore\b|lakh\b|lac\b)?",
    re.I,
)

SUFFIX_MULTIPLIER = {
    "m": 1_000_000, "mn": 1_000_000, "million": 1_000_000,
    "k": 1_000, "thousand": 1_000,
    "cr": 10_000_000, "crore": 10_000_000,
    "lakh": 100_000, "lac": 100_000,
}

# Numbers followed by these are describing the property, not the money:
# "2 bed", "3 br", "1200 sqft", "floor 15", "2 bathrooms".
NON_MONEY_UNIT = re.compile(
    r"^\s*(bed|beds|bedroom|bedrooms|bhk|br\b|bath|baths|bathroom|bathrooms|"
    r"sq\.?\s?ft|sqft|sqm|sq\.?\s?m|square|floor|storey|story|year|years|"
    r"month|months|bed-?room|"
    r"غرف|غرفة|غرفه|حمام|حمامات|قدم|متر|طابق|سنة|سنوات|شهر|أشهر|اشهر)",
    re.I,
)
# Numbers preceded by these are labels, not money: "floor 20", "tower 3", "no. 4".
NON_MONEY_PREFIX = re.compile(
    r"(floor|level|tower|building|unit|apt|apartment|villa|no\.?|#|طابق|برج|رقم)\s*$",
    re.I,
)


@dataclass
class BudgetExtraction:
    """Result of parsing a budget out of free text.

    ``needs_clarification`` is the important field: when True, the caller must
    ask ``clarifying_question`` before quoting any price. It is never
    acceptable to fall back to a default currency or period.
    """

    raw_text: str
    amount_min: Optional[float] = None
    amount_max: Optional[float] = None
    currency: Optional[str] = None
    period: Optional[str] = None          # "total" (sale) | "year" | "month"
    intent: Optional[str] = None          # "buy" | "rent"
    needs_clarification: bool = False
    clarifying_question: Optional[str] = None
    assumptions: list[str] = field(default_factory=list)

    @property
    def amount_min_aed(self) -> Optional[float]:
        return self._to_aed(self.amount_min)

    @property
    def amount_max_aed(self) -> Optional[float]:
        return self._to_aed(self.amount_max)

    def _to_aed(self, value: Optional[float]) -> Optional[float]:
        if value is None or not self.currency:
            return None
        rate = FX_TO_AED.get(self.currency)
        return round(value * rate, 2) if rate else None

    def to_lead_fields(self) -> dict:
        """Map onto the lead record. Only writes what we actually know."""
        out: dict = {}
        if not self.needs_clarification:
            if self.amount_min_aed is not None:
                out["budget_min"] = self.amount_min_aed
            if self.amount_max_aed is not None:
                out["budget_max"] = self.amount_max_aed
        if self.currency:
            out["budget_currency"] = self.currency
        if self.period:
            out["budget_period"] = self.period
        if self.intent:
            out["deal_intent"] = self.intent
        return out


def _parse_amounts(text: str) -> list[float]:
    """Pull candidate money amounts, skipping property descriptors.

    "2 bed apartment, budget AED 1.8M" must yield [1_800_000], not
    [2, 1_800_000] — otherwise the bedroom count becomes the budget floor.
    """
    scaled: list[float] = []
    bare: list[float] = []

    for match in NUMBER.finditer(text):
        suffix = (match.group("suffix") or "").lower().rstrip(".")
        trailing = text[match.end():]
        if not suffix and NON_MONEY_UNIT.match(trailing):
            continue  # "2 bed", "1200 sqft" — describing the property
        if not suffix and NON_MONEY_PREFIX.search(text[: match.start()]):
            continue  # "floor 20", "tower 3"

        raw = match.group("num").replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue

        if suffix:
            scaled.append(value * SUFFIX_MULTIPLIER.get(suffix, 1))
        elif "," in match.group("num") or value >= 1000:
            scaled.append(value)   # "1,200,000" or "850000" reads as money
        else:
            # A bare small number ("1.2", "800") is inherently ambiguous — it
            # is almost never a literal AED 1.2. Kept only if nothing clearer
            # appears, and flagged for clarification by the caller.
            bare.append(value)

    return scaled or bare


def _detect_currency(text: str) -> Optional[str]:
    for pattern, code in CURRENCY_PATTERNS:
        if re.search(pattern, text, re.I):
            return code
    return None


def _detect_intent(text: str) -> Optional[str]:
    if RENT_HINT.search(text):
        return "rent"
    if BUY_HINT.search(text):
        return "buy"
    return None


def _detect_period(text: str, intent: Optional[str]) -> Optional[str]:
    if PER_YEAR.search(text):
        return "year"
    if PER_MONTH.search(text):
        return "month"
    if intent == "buy":
        # A purchase price is a total by definition — this is a safe inference,
        # not a guess about what the lead meant.
        return "total"
    return None


def extract_budget(text: str) -> BudgetExtraction:
    """Extract an explicit budget, or ask for one. Never invents a value."""
    result = BudgetExtraction(raw_text=text or "")
    if not text or not text.strip():
        return result

    amounts = _parse_amounts(text)
    if not amounts:
        return result

    amounts = sorted(amounts)
    result.amount_min = amounts[0]
    result.amount_max = amounts[-1] if len(amounts) > 1 else amounts[0]

    result.intent = _detect_intent(text)
    result.currency = _detect_currency(text)
    result.period = _detect_period(text, result.intent)

    questions: list[str] = []

    # Ambiguity 1: bare number with no magnitude suffix, e.g. "my budget is 1.2"
    has_suffix = bool(re.search(r"\d\s*(m|mn|million|k|thousand|cr|crore|lakh|lac)\b", text, re.I))
    has_grouping = bool(re.search(r"\d{1,3}(,\d{3})+", text))
    if result.amount_max is not None and result.amount_max < 1000 and not has_suffix and not has_grouping:
        questions.append(
            f"just to confirm, is that {result.amount_max:g} million or {result.amount_max:g} thousand?"
        )

    # Ambiguity 2: no currency stated at all.
    if result.currency is None:
        questions.append("is that in AED or another currency?")

    # Ambiguity 3: no period, and we can't safely infer one.
    if result.period is None:
        questions.append("is that the total purchase price, or per year for rent?")

    if questions:
        result.needs_clarification = True
        result.clarifying_question = _compose_question(questions)
    else:
        result.assumptions.append(
            f"Explicitly stated: {result.currency}, {result.period}"
        )

    return result


def _compose_question(questions: list[str]) -> str:
    """Fold the ambiguities into one natural question, not an interrogation."""
    if len(questions) == 1:
        body = questions[0]
    elif len(questions) == 2:
        body = f"{questions[0]} And {questions[1]}"
    else:
        body = f"{questions[0]} Also, {questions[1]} And {questions[-1]}"
    return "Happy to pull the right options for you — " + body


def describe_budget(extraction: BudgetExtraction) -> str:
    """Human-readable budget for message templates. Safe when unknown."""
    if extraction.needs_clarification or extraction.amount_min is None:
        return "your budget"
    currency = extraction.currency or "AED"
    if extraction.amount_min == extraction.amount_max:
        amount = f"{currency} {extraction.amount_min:,.0f}"
    else:
        amount = f"{currency} {extraction.amount_min:,.0f}-{extraction.amount_max:,.0f}"
    if extraction.period == "year":
        return f"{amount} per year"
    if extraction.period == "month":
        return f"{amount} per month"
    return amount
