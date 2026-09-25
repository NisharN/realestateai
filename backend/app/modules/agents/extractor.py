"""Extractor agent: rules always run; the LLM adds intent/slots when available.

STOP and human-request detection are rules-first and cannot be overridden by
the LLM. Money never comes from the LLM: any ``budget_text`` goes through
``services.budget_extraction.extract_budget``.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.modules.conversation.facts import ExtractedFacts, LLMFacts, Reaction, Slots
from app.modules.conversation.state import ConversationState
from app.modules.geo.communities import resolve_area
from app.modules.leads.profile import normalise_money_text
from app.modules.llm import LLMUnavailable, get_gateway
from app.services.budget_extraction import extract_budget

logger = logging.getLogger(__name__)

# --- rule patterns (EN + AR) ---------------------------------------------
STOP_RE = re.compile(
    r"^\s*(stop|unsubscribe|opt\s*out|do not (contact|message|call) me|don'?t (contact|message|call) me|"
    r"remove me|leave me alone|توقف|لا تراسلني|الغاء الاشتراك|لا تتصل بي)\b",
    re.I,
)
HUMAN_RE = re.compile(
    r"\b(speak|talk|chat)\s+(to|with)\s+(an?\s+)?(human|person|agent|broker|someone|real person)|"
    r"\b(real|human)\s+(agent|person|broker)\b|\b(get|give|connect|put)\s+me\s+(to\s+|with\s+)?(a\s+|an\s+)?(human|person|agent|broker)\b|\bcall me\b|\bcan (someone|an agent|a broker) call\b|"
    r"\bnot a bot\b|\bare you a bot\b.*\bhuman\b|أريد (التحدث|الكلام) مع (شخص|موظف|وسيط)|اتصل بي|شخص حقيقي|موظف حقيقي",
    re.I,
)
VIEWING_RE = re.compile(
    r"\b(viewing|view it|visit|see it in person|book (a )?(visit|viewing|tour)|arrange (a )?(visit|viewing)|"
    r"schedule (a )?(visit|viewing|call)|site visit|show me the (place|unit|property) in person)\b|"
    r"معاينة|زيارة|اشوف العقار|أشاهد العقار",
    re.I,
)
NOT_INTERESTED_RE = re.compile(
    r"\b(not interested|no longer interested|already (bought|rented|found)|changed my mind|no thanks|not looking anymore|"
    r"maybe (next|later) year|just browsing)\b|غير مهتم|لست مهتم|اشتريت بالفعل|لاحقاً ربما",
    re.I,
)
AGREE_RE = re.compile(
    r"^\s*(yes|yeah|yep|sure|ok(ay)?|please do|sounds good|go ahead|that works|perfect|great|fine|absolutely|of course|"
    r"نعم|أجل|تمام|أكيد|موافق|ماشي|طيب|اوك|ايوه)\b[\s!.,]*",
    re.I,
)
DISAGREE_RE = re.compile(r"^\s*(no|nope|not now|not yet|later|لا|ليس الآن|لاحقاً)\b", re.I)
ASK_AREA_RE = re.compile(
    r"\b(what('s| is) (it|the area|the community|life|living) like|how is (the|that) (area|community)|"
    r"(schools?|metro|beach|traffic|commute|nearby|near by|amenities|hospital|mall|supermarket|gym) (in|near|around|at)|"
    r"is (it|the area) (safe|quiet|family|good)|how far (is|from)|travel time|distance to)\b|"
    r"كيف المنطقة|ما رأيك بالمنطقة|قريب من|كم تبعد|المدارس|المترو",
    re.I,
)
ASK_PROPERTY_RE = re.compile(
    r"\b(tell me more about|more (details|info|information) (on|about)|what('s| is) the (service charge|floor|view|handover|payment plan)|"
    r"is it (furnished|vacant|rented|ready)|does it have|how (big|large|many floors)|which floor|when is (the )?handover|"
    r"the (first|second|third|1st|2nd|3rd) one\b.*\?)|تفاصيل|أخبرني أكثر عن|هل هو مفروش|أي طابق",
    re.I,
)
COMPARE_RE = re.compile(
    r"\b(compare|comparison|versus|vs\.?|difference between|which (one )?is better|side by side)\b|قارن|مقارنة|الفرق بين|أيهما أفضل",
    re.I,
)
OBJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("price", re.compile(r"\b(too (expensive|pricey|much|high)|over (my )?budget|can'?t afford|cheaper|lower price|expensive)\b|غالي|فوق الميزانية|أرخص", re.I)),
    ("location", re.compile(r"\b(too far|wrong (area|location)|not that area|different (area|community|location)|don'?t like the (area|location))\b|بعيد جداً|منطقة أخرى|لا أحب المنطقة", re.I)),
    ("size", re.compile(r"\b(too small|too big|bigger|larger|more space|smaller|not enough (space|rooms|bedrooms))\b|صغير جداً|أكبر|مساحة أكبر", re.I)),
    ("payment", re.compile(r"\b(payment plan|installments?|mortgage (rate|issue|problem)|down ?payment|can'?t pay upfront)\b|خطة دفع|أقساط|الدفعة الأولى", re.I)),
    ("handover", re.compile(r"\b(handover|completion|off[- ]?plan|ready (now|to move)|delivery date|too late|not ready)\b|التسليم|جاهز|قيد الإنشاء", re.I)),
]

BEDROOM_RE = re.compile(
    r"\b(\d{1,2})\s*(-|\s)?\s*(bed(room)?s?|br|bhk)\b|\b(studio)\b|"
    r"\b(one|two|three|four|five|six)\s*(-|\s)?\s*(bed(room)?s?|br)\b|"
    r"(\d{1,2})\s*غرف|غرفتين|غرفه واحده|غرفة واحدة|ثلاث غرف|أربع غرف|استوديو",
    re.I,
)
WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
AR_BED = {"غرفتين": 2, "غرفه واحده": 1, "غرفة واحدة": 1, "ثلاث غرف": 3, "أربع غرف": 4}

TYPE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("townhouse", re.compile(r"\b(town ?houses?)\b|تاون ?هاوس", re.I)),
    ("penthouse", re.compile(r"\b(penthouses?)\b|بنتهاوس", re.I)),
    ("villa", re.compile(r"\b(villas?)\b|فيلا|فلل", re.I)),
    ("apartment", re.compile(r"\b(apartments?|flats?|apt|condo|studio)\b|شقة|شقه|شقق|استوديو", re.I)),
    ("land", re.compile(r"\b(plot|land)\b|أرض|قطعة", re.I)),
]
PURPOSE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("rent", re.compile(r"\b(rent(ing|al)?|lease|to let|tenant|per (year|annum|month)|yearly|monthly)\b|إيجار|استئجار|أستأجر|سنوياً|شهرياً", re.I)),
    ("invest", re.compile(r"\b(invest(ment|ing|or)?|roi|rental yield|yield|golden visa|off[- ]?plan for investment)\b|استثمار|عائد|فيزا ذهبية", re.I)),
    ("buy", re.compile(r"\b(buy(ing)?|purchase|own(ing)?|mortgage|cash buyer|first home|move in|live in)\b|شراء|أشتري|تملك|أسكن", re.I)),
]
TIMELINE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("asap", re.compile(r"\b(asap|immediately|right away|urgent(ly)?|this (week|month)|as soon as possible|now)\b|فوراً|بأسرع وقت|هذا الشهر|حالاً", re.I)),
    ("1_month", re.compile(r"\b(within (a|one|1) month|next month|in (a|one|1) month|4 weeks|few weeks)\b|خلال شهر|الشهر القادم", re.I)),
    ("3_months", re.compile(r"\b((within |in |next )?(2|3|two|three) months|this quarter|by (summer|winter|ramadan|eid)|couple of months)\b|خلال (شهرين|ثلاثة أشهر|3 أشهر)", re.I)),
    ("6_months", re.compile(r"\b((within |in |next )?(4|5|6|four|five|six) months|half a year|(in )?6 months)\b|خلال (ستة|6) أشهر|نصف سنة", re.I)),
    ("12_months", re.compile(r"\b((within |in |next )?(7|8|9|10|11|12) months|within (a|one|1|this) year|end of (the )?year|by next year)\b|خلال سنة|نهاية السنة", re.I)),
    ("later", re.compile(r"\b(next year|in (2|two|3|three) years|no rush|not (in a )?hurry|just (looking|browsing|exploring|researching)|someday|eventually|long term)\b|السنة القادمة|لا يوجد عجلة|مجرد أتصفح|بعد سنتين", re.I)),
]
PAYMENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("mortgage_preapproved", re.compile(r"\b(pre[- ]?approv(ed|al)|approved (for a )?mortgage|bank approved|got (the )?mortgage)\b|موافقة مبدئية|تمويل معتمد", re.I)),
    ("mortgage_not_started", re.compile(r"\b(mortgage|finance|financing|loan|bank)\b|تمويل|قرض|رهن", re.I)),
    ("cash", re.compile(r"\b(cash|no mortgage|outright|full payment|pay in full)\b|كاش|نقد|نقداً|بدون تمويل", re.I)),
]
LIKE_RE = re.compile(r"\b(i like|love|nice|looks good|interested in|the (first|second|third|1st|2nd|3rd) (one|option)|number ([123])|option ([123]))\b|أعجبني|يعجبني|جميل|الأول|الثاني|الثالث", re.I)
REJECT_RE = re.compile(r"\b(don'?t like|not (for me|these|those|this)|none of (these|those|them)|no(ne)? (of )?(these|those)|show me (other|different|more)|something else|next)\b|لا يعجبني|لا تناسبني|شيء آخر|غيرها", re.I)
ORDINAL = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "الأول": 1, "الثاني": 2, "الثالث": 3}
ARABIC_RE = re.compile(r"[\u0600-\u06FF]")
BUDGET_FOLLOWUP_RE = re.compile(r"\b(million|mil|m|thousand|k|total|purchase|per (year|annum|month)|yearly|annual|to buy|to rent|buy|rent)\b|مليون|ألف|سنوي|شراء|إيجار|اجار", re.I)


def detect_language(text: str, default: str = "en") -> str:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return default
    arabic = sum(1 for c in letters if ARABIC_RE.match(c))
    return "ar" if arabic / len(letters) >= 0.4 else "en"


def _first(patterns: list[tuple[str, re.Pattern[str]]], text: str) -> str | None:
    for label, pattern in patterns:
        if pattern.search(text):
            return label
    return None


def _bedrooms(text: str) -> int | None:
    m = BEDROOM_RE.search(text)
    if not m:
        return None
    if m.group(1):
        return int(m.group(1))
    if m.group(5):
        return 0
    if m.group(6):
        return WORD_NUM[m.group(6).lower()]
    if m.group(9):
        return int(m.group(9))
    for ar, n in AR_BED.items():
        if ar in m.group(0):
            return n
    if "استوديو" in m.group(0):
        return 0
    return None


def _reactions(text: str, state: ConversationState) -> list[Reaction]:
    current = state.current_shortlist()
    if not current:
        return []
    reactions: list[Reaction] = []
    like = LIKE_RE.search(text)
    reject = REJECT_RE.search(text)
    index: int | None = None
    if like:
        for key, n in ORDINAL.items():
            if re.search(rf"\b{key}\b", text, re.I) or key in text:
                index = n
                break
        for g in (like.group(4), like.group(5)):
            if g and g.isdigit():
                index = int(g)
    if like and not reject:
        if index and index <= len(current):
            reactions.append(Reaction(property_id=current[index - 1].property_id, property_index=index, reaction="liked"))
        elif len(current) == 1:
            reactions.append(Reaction(property_id=current[0].property_id, property_index=1, reaction="liked"))
    elif reject and not like:
        for i, shown in enumerate(current, start=1):
            reactions.append(Reaction(property_id=shown.property_id, property_index=i, reaction="rejected"))
    return reactions


def extract_rules(text: str, state: ConversationState) -> ExtractedFacts:
    """Deterministic extraction. Always runs; never raises."""
    text = text or ""
    lang = detect_language(text, state.language)
    slots = Slots()
    facts = ExtractedFacts(language=lang, slots=slots, rules_only=True, text=text)  # type: ignore[arg-type]

    if STOP_RE.search(text):
        facts.intent = "stop"
        facts.confidence = 1.0
        return facts
    if HUMAN_RE.search(text):
        facts.intent = "request_human"
        facts.confidence = 1.0
        return facts

    # slots -------------------------------------------------------------
    slots.purpose = _first(PURPOSE_PATTERNS, text)  # type: ignore[assignment]
    slots.property_type = _first(TYPE_PATTERNS, text)
    slots.bedrooms = _bedrooms(text)
    slots.timeline = _first(TIMELINE_PATTERNS, text)  # type: ignore[assignment]
    slots.payment = _first(PAYMENT_PATTERNS, text)  # type: ignore[assignment]

    budget = extract_budget(normalise_money_text(text))
    if budget.amount_max is not None or (state.has("budget_pending") and BUDGET_FOLLOWUP_RE.search(text)):
        slots.budget_text = text

    matches = resolve_area(text)
    strong = [m for m in matches if m.confidence >= 0.8]
    slots.areas = [m.community.name_en for m in strong]
    facts.area_candidates = [m.community.id for m in strong]
    if not strong and re.search(r"\b(in|at|near|around)\s+[A-Z][a-zA-Z]+|في\s+\S+", text):
        # a proper-noun place we don't know
        known_words = {"dubai", "uae", "aed", "the", "a", "an"}
        tail = re.search(r"\b(in|at|near|around)\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)", text)
        if tail and tail.group(2).lower() not in known_words and not slots.timeline:
            facts.area_unresolved = True

    facts.reactions = _reactions(text, state)

    # intent ------------------------------------------------------------
    objection = _first(OBJECTION_PATTERNS, text)
    if NOT_INTERESTED_RE.search(text):
        facts.intent = "not_interested"
    elif VIEWING_RE.search(text):
        facts.intent = "request_viewing"
    elif COMPARE_RE.search(text) and len(state.shortlist) >= 2:
        facts.intent = "compare"
    elif ASK_AREA_RE.search(text):
        facts.intent = "ask_area"
    elif ASK_PROPERTY_RE.search(text) and state.shortlist:
        facts.intent = "ask_property"
    elif objection and state.shortlist:
        facts.intent = "objection"
        facts.objection = objection  # type: ignore[assignment]
    elif any(
        v not in (None, [], "") for v in (slots.purpose, slots.property_type, slots.bedrooms, slots.timeline, slots.payment, slots.budget_text, slots.areas)
    ) or facts.reactions:
        facts.intent = "provide_info"
    elif AGREE_RE.match(text):
        facts.intent = "agree"
    elif DISAGREE_RE.match(text):
        facts.intent = "disagree"
    elif len(text.split()) <= 4 and re.search(r"\b(hi|hello|hey|salam|مرحبا|السلام|هلا|اهلا)\b", text, re.I):
        facts.intent = "smalltalk"
    else:
        facts.intent = "unclear"
    facts.confidence = 0.7 if facts.intent != "unclear" else 0.2
    return facts


EXTRACT_SYSTEM = (
    "You extract structured facts from one message of a Dubai property buyer. "
    "Return ONLY a JSON object with keys: intent, language, slots, reactions, objection, confidence. "
    "intent ∈ provide_info|ask_property|ask_area|compare|request_viewing|request_human|objection|smalltalk|not_interested|stop|unclear|agree|disagree. "
    "language ∈ en|ar. slots keys: budget_text (verbatim money phrase or null), areas (list of place names as written), bedrooms (int or null), "
    "property_type (apartment|villa|townhouse|penthouse|land|null), purpose (buy|rent|invest|null), timeline (asap|1_month|3_months|6_months|12_months|later|null), "
    "payment (cash|mortgage_preapproved|mortgage_not_started|null), end_use, must_haves (list), name, location_prefs (object like {\"work\":\"DIFC\"}). "
    "reactions: list of {property_index (1-based from the shown list), reaction liked|rejected|neutral, reason}. "
    "objection ∈ price|location|size|payment|handover|other|null. Do not compute amounts; copy the money phrase verbatim. Never invent facts."
)


def _merge(rules: ExtractedFacts, llm: LLMFacts, state: ConversationState) -> ExtractedFacts:
    merged = rules.model_copy(deep=True)
    merged.rules_only = False
    # Rules own STOP / human. Otherwise prefer the LLM's intent when rules were unsure.
    if rules.intent in {"unclear", "smalltalk", "provide_info", "agree", "disagree"} and llm.intent not in {"stop", "request_human"}:
        if llm.intent != "unclear":
            merged.intent = llm.intent
    if llm.objection and not merged.objection:
        merged.objection = llm.objection
    s, ls = merged.slots, llm.slots
    if s.purpose is None and ls.purpose is not None:
        s.purpose = ls.purpose
    if s.property_type is None and ls.property_type:
        s.property_type = ls.property_type
    if s.bedrooms is None and ls.bedrooms is not None:
        s.bedrooms = ls.bedrooms
    if s.timeline is None and ls.timeline is not None:
        s.timeline = ls.timeline
    if s.payment is None and ls.payment is not None:
        s.payment = ls.payment
    if s.end_use is None and ls.end_use is not None:
        s.end_use = ls.end_use
    if not s.name and ls.name:
        s.name = ls.name
    if not s.must_haves and ls.must_haves:
        s.must_haves = ls.must_haves
    if ls.location_prefs:
        s.location_prefs = {**ls.location_prefs, **s.location_prefs}
    if not s.budget_text and ls.budget_text:
        s.budget_text = ls.budget_text
    if ls.areas and not merged.area_candidates:
        for name in ls.areas:
            for m in resolve_area(name):
                if m.confidence >= 0.8 and m.community.id not in merged.area_candidates:
                    merged.area_candidates.append(m.community.id)
                    s.areas.append(m.community.name_en)
        if not merged.area_candidates:
            merged.area_unresolved = True
    if not merged.reactions and llm.reactions:
        current = state.current_shortlist()
        for r in llm.reactions:
            if r.property_index and 1 <= r.property_index <= len(current):
                merged.reactions.append(
                    Reaction(property_id=current[r.property_index - 1].property_id, property_index=r.property_index, reaction=r.reaction, reason=r.reason)
                )
    merged.confidence = max(rules.confidence, llm.confidence)
    return merged


async def extract(text: str, state: ConversationState, deadline_s: float | None = None) -> ExtractedFacts:
    """Rules first (authoritative for STOP/human), then LLM enrichment if available."""
    rules = extract_rules(text, state)
    if rules.intent in {"stop", "request_human"}:
        return rules
    gateway = get_gateway()
    if not gateway.available:
        return rules
    shown = [
        {"index": i + 1, "title": p.title, "area": p.area, "price": p.price}
        for i, p in enumerate(state.current_shortlist())
    ]
    messages = [
        {"role": "system", "content": EXTRACT_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Known profile: {state.profile_values()}\nStage: {state.stage}\nShown properties: {shown}\n"
                f"Buyer message: <<<{text}>>>"
            ),
        },
    ]
    try:
        llm = await gateway.complete_json(messages, LLMFacts, deadline_s=deadline_s, purpose="extract")
    except LLMUnavailable as exc:
        logger.info("extractor: llm unavailable (%s); rules only", exc)
        return rules
    return _merge(rules, llm, state)


def slots_to_dict(facts: ExtractedFacts) -> dict[str, Any]:
    return facts.model_dump(mode="json")
