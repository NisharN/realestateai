"""The turn engine shared by chat, voice and WhatsApp (architecture §8.1).

    facts  = extract(text, state)
    state  = profile.merge(state, facts)
    score  = scorer.score(state)
    move   = policy.decide(state, facts)
    tools  = run_for(move, state)
    reply  = responder.respond(...) guarded, else template
    repo.save_turn(...)

Every step is bounded by the turn deadline and every failure degrades to the
next cheaper option. ``handle_turn`` never raises for buyer-facing callers.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.config import get_settings
from app.database import get_lead_repository
from app.modules.agents import extractor, scorer
from app.modules.agents.responder import respond
from app.modules.ingestion import events
from app.modules.ingestion.pipeline.processor import suppress_contact
from app.modules.handoff import followups
from app.modules.handoff.service import create_handoff
from app.modules.leads.profile import lead_updates_from_state, merge
from app.modules.store import lock_for, table
from app.modules.tools import property_search
from app.modules.tools.area_profile import area_profile
from app.modules.tools.compare import compare
from app.modules.tools.viewing_slots import next_slots

from . import policy, templates
from .facts import ExtractedFacts
from .moves import Move
from .repository import ConversationRepo
from .state import ConversationState

logger = logging.getLogger(__name__)


class TurnResult(BaseModel):
    reply: str
    move: str
    stage: str
    score: int
    band: str
    score_reasons: list[str]
    turn: int
    profile: dict[str, Any]
    cards: list[dict[str, Any]] = Field(default_factory=list)
    area: dict[str, Any] | None = None
    compare: list[dict[str, Any]] = Field(default_factory=list)
    handoff_id: str | None = None
    ended: bool = False
    latency_ms: int = 0
    fallbacks: list[str] = Field(default_factory=list)
    idempotent_replay: bool = False
    language: str = "en"


class Deadline:
    def __init__(self, seconds: float) -> None:
        self.end = time.monotonic() + seconds

    def remaining(self, cap: float | None = None) -> float:
        left = max(0.0, self.end - time.monotonic())
        return min(left, cap) if cap is not None else left


async def handle_turn(
    lead_id: str,
    text: str,
    *,
    workspace_id: str,
    channel: str = "chat",
    idempotency_key: str | None = None,
    source: str | None = None,
) -> TurnResult:
    settings = get_settings()
    total_budget = settings.TURN_DEADLINE_VOICE_S if channel == "voice" else settings.TURN_DEADLINE_CHAT_S
    deadline = Deadline(total_budget)
    started = time.monotonic()
    repo = ConversationRepo(workspace_id)
    key = idempotency_key or f"{lead_id}:{uuid4().hex}"

    async with lock_for(f"turn:{workspace_id}:{lead_id}"):
        replay = await repo.find_message(lead_id, key)
        if replay:
            state = await repo.load(lead_id, channel=channel, source=source)
            return _result(state, replay["text"], replay["meta"].get("move", ""), replay["meta"].get("tool_results") or {}, 0, ["replay"], replay=True)

        state = await repo.load(lead_id, channel=channel, source=source)
        try:
            return await _run(state, text, repo, workspace_id, deadline, key, started)
        except Exception as exc:  # last resort: never surface an error to the buyer
            logger.exception("turn failed for lead %s: %s", lead_id, exc)
            state.misunderstandings += 1
            reply = templates.render("error_fallback", state.language, {})
            try:
                state.turn += 1
                await repo.save_turn(
                    state, text=text, reply=reply, move="error_fallback", facts={}, tool_results={},
                    idempotency_key=key, latency_ms=int((time.monotonic() - started) * 1000), fallbacks=["template:exception"],
                )
            except Exception:  # pragma: no cover
                logger.exception("could not persist fallback turn")
            return _result(state, reply, "error_fallback", {}, int((time.monotonic() - started) * 1000), ["template:exception"])


async def _run(
    state: ConversationState,
    text: str,
    repo: ConversationRepo,
    workspace_id: str,
    deadline: Deadline,
    key: str,
    started: float,
) -> TurnResult:
    settings = get_settings()
    state.turn += 1
    fallbacks: list[str] = []

    if state.stage in {"opted_out", "closed"}:
        reply = templates.render(Move.OPT_OUT, state.language, {})
        await repo.save_turn(state, text=text, reply=reply, move="opt_out", facts={}, tool_results={}, idempotency_key=key, latency_ms=0, fallbacks=["suppressed"])
        return _result(state, reply, "opt_out", {}, 0, ["suppressed"], ended=True)

    if state.stage == "handed_off":
        rules = extractor.extract_rules(text, state)
        if rules.intent != "stop":
            broker = await _handoff_broker_name(state, workspace_id)
            reply = templates.render("after_handoff", state.language, {"broker_name": broker})
            await repo.save_turn(state, text=text, reply=reply, move="after_handoff", facts=rules.model_dump(mode="json"), tool_results={}, idempotency_key=key, latency_ms=0, fallbacks=[])
            return _result(state, reply, "after_handoff", {}, 0, [], ended=True)

    # 1. extract ---------------------------------------------------------
    try:
        facts = await extractor.extract(text, state, deadline_s=deadline.remaining(settings.LLM_EXTRACT_TIMEOUT_S))
    except Exception as exc:
        logger.warning("extractor failed, rules only: %s", exc)
        facts = extractor.extract_rules(text, state)
        fallbacks.append("extract:rules_only")
    if facts.rules_only and facts.intent != "stop" and facts.intent != "request_human":
        fallbacks.append("extract:rules_only")

    # 2. merge + score ----------------------------------------------------
    merge(state, facts)
    if facts.intent == "unclear":
        state.misunderstandings += 1
    else:
        state.misunderstandings = 0
    state.score, state.score_reasons = scorer.score(state)
    state.band = scorer.band_for(state.score)  # type: ignore[assignment]

    # 3. decide -----------------------------------------------------------
    decision = policy.decide(state, facts)
    move = decision.move
    if decision.field:
        state.asked[decision.field] = state.asked.get(decision.field, 0) + 1
    if move == Move.CLARIFY_BUDGET:
        state.asked["budget_clarify"] = state.asked.get("budget_clarify", 0) + 1
    if move == Move.CLARIFY_AREA:
        state.asked["area_clarify"] = state.asked.get("area_clarify", 0) + 1

    # 4. tools ------------------------------------------------------------
    tool_results = await _run_tools(move, state, facts, workspace_id, deadline, fallbacks)

    # 5. stage transitions ------------------------------------------------
    _advance_stage(state, move, tool_results)

    # 6. respond ----------------------------------------------------------
    reply_facts = _reply_facts(move, state, facts, tool_results, decision.field)
    resp_fallbacks: list[str]
    if move == Move.SMALL_TALK_REDIRECT and not reply_facts.get("next_question") and state.shortlist:
        reply, resp_fallbacks = templates.render("ask_reaction", state.language, reply_facts), []
    else:
        reply, resp_fallbacks = await respond(
            move, state, reply_facts, deadline_s=deadline.remaining(settings.LLM_RESPOND_TIMEOUT_S), field=decision.field
        )
    fallbacks.extend(resp_fallbacks)
    state.last_move = move.value

    # 7. save -------------------------------------------------------------
    latency_ms = int((time.monotonic() - started) * 1000)
    await repo.save_turn(
        state, text=text, reply=reply, move=move.value, facts=facts.model_dump(mode="json"),
        tool_results=_jsonable(tool_results), idempotency_key=key, latency_ms=latency_ms, fallbacks=fallbacks,
    )
    await _mirror_lead(state, workspace_id)
    await _schedule_followups(state, move, workspace_id)
    return _result(state, reply, move.value, _jsonable(tool_results), latency_ms, fallbacks, ended=move in {Move.OPT_OUT, Move.HANDOFF, Move.HANDOFF_NOW})


async def _run_tools(
    move: Move, state: ConversationState, facts: ExtractedFacts, workspace_id: str, deadline: Deadline, fallbacks: list[str]
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    budget = deadline.remaining(2.5)

    async def guarded(name: str, coro):
        try:
            results[name] = await asyncio.wait_for(coro, timeout=max(0.2, budget))
        except Exception as exc:
            logger.warning("tool %s failed: %s", name, exc)
            fallbacks.append(f"tool:{name}")

    if move in {Move.SUGGEST, Move.HANDLE_OBJECTION}:
        relax = facts.objection if move == Move.HANDLE_OBJECTION else None
        query = property_search.query_from_state(state, relax=relax)
        await guarded("search", property_search.search(query, workspace_id))
        search = results.get("search")
        if search and search.cards:
            state.shortlist.extend(property_search.to_shown(search.cards, state.turn))
            state.shortlist = state.shortlist[-12:]

    elif move == Move.ANSWER_AREA:
        target = (facts.area_candidates or state.value("community_ids") or [None])[0] or " ".join(facts.slots.areas) or (state.value("area") or [""])[0]
        if target:
            await guarded("area", area_profile(target, workspace_id, state.language))

    elif move == Move.ANSWER_PROPERTY:
        current = state.current_shortlist()
        target = None
        for r in facts.reactions:
            if r.property_id:
                target = r.property_id
        if target is None and current:
            target = current[0].property_id
        if target:
            await guarded("compare", compare([target], workspace_id))

    elif move == Move.COMPARE:
        ids = [p.property_id for p in state.current_shortlist()][:3]
        if ids:
            await guarded("compare", compare(ids, workspace_id))

    elif move == Move.CONFIRM_HANDOFF:
        results["slots"] = next_slots()

    elif move in {Move.HANDOFF, Move.HANDOFF_NOW}:
        repo = ConversationRepo(workspace_id)
        transcript = await repo.transcript(state.lead_id)
        slot_text = None
        if move == Move.HANDOFF:
            slots = next_slots(count=1)
            slot_text = slots[0].label_en if state.language == "en" else slots[0].label_ar
        await guarded(
            "handoff",
            create_handoff(
                state,
                workspace_id=workspace_id,
                reason="request_human" if move == Move.HANDOFF_NOW else "qualified_confirmed",
                transcript=transcript,
                slot_text=slot_text,
                deadline_s=deadline.remaining(3.0),
            ),
        )
        if "handoff" in results:
            state.handoff_id = results["handoff"].get("id")
    return results


def _advance_stage(state: ConversationState, move: Move, tools: dict[str, Any]) -> None:
    if move == Move.OPT_OUT:
        state.stage = "opted_out"
    elif move in {Move.HANDOFF, Move.HANDOFF_NOW}:
        state.stage = "handed_off"
    elif move == Move.NURTURE:
        state.stage = "nurture"
    elif move == Move.CONFIRM_HANDOFF:
        state.stage = "confirming"
    elif move == Move.SUGGEST:
        found = bool(tools.get("search") and tools["search"].cards)
        state.stage = "suggesting" if found else "refining"
        if not found:
            state.asked["suggest_empty"] = state.asked.get("suggest_empty", 0) + 1
    elif move in {Move.HANDLE_OBJECTION, Move.COMPARE, Move.ANSWER_PROPERTY}:
        state.stage = "refining"
    elif move in {Move.ASK_NEXT_FIELD, Move.CLARIFY_AREA, Move.CLARIFY_BUDGET, Move.GREETING}:
        if state.stage in {"greeting", "discovering"}:
            state.stage = "discovering"


def _reply_facts(move: Move, state: ConversationState, facts: ExtractedFacts, tools: dict[str, Any], field: str | None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "brokerage": "our brokerage",
        "name_suffix": f" {state.value('name')}" if state.value("name") else "",
        "profile": state.profile_values(),
    }
    areas = state.value("area") or []
    if areas:
        out["area_name"] = ", ".join(areas)
    if facts.budget_question:
        out["budget_question"] = facts.budget_question
    next_field = field or state.next_field_to_ask()
    if next_field:
        q = templates.question_for_field(next_field, state.language)
        out["next_question"] = q
        out["next_question_lower"] = q[:1].lower() + q[1:] if state.language == "en" else q
    search = tools.get("search")
    if search is not None:
        out["cards"] = [c.model_dump() for c in search.cards]
        out["result_count"] = len(search.cards)
        out["titles"] = [c.title for c in search.cards]
        if search.cards and search.cards[0].area:
            out["area_name"] = search.cards[0].area
    if facts.objection:
        out["objection"] = facts.objection
        out["objection_topic"] = {"price": "your budget", "location": "location", "size": "space", "payment": "payment terms", "handover": "handover timing", "other": "what you mentioned"}.get(facts.objection, "your feedback")
    area = tools.get("area")
    if area is not None:
        out["area"] = area.model_dump()
        out["area_name"] = area.name_ar if state.language == "ar" else area.name_en
        out["area_summary"] = area.summary
        if area.median_price_psf:
            out["area_price_psf"] = f"{area.median_price_psf:,.0f}"
        if area.travel:
            approx = any(t.approx for t in area.travel)
            out["area_travel"] = [
                {"to": t.to_name_ar if state.language == "ar" else t.to_name_en, "minutes": t.minutes, "km": t.km, "approx": t.approx}
                for t in area.travel
            ]
            first = area.travel[0]
            out["area_travel_text"] = (
                (f"حوالي {first.minutes} دقيقة إلى {first.to_name_ar}" if approx else f"{first.minutes} دقيقة إلى {first.to_name_ar}")
                if state.language == "ar"
                else (f"about {first.minutes} minutes to {first.to_name_en} (approx.)" if approx else f"{first.minutes} minutes to {first.to_name_en}")
            )
    cmp = tools.get("compare")
    if cmp is not None and cmp.rows:
        out["compare"] = [r.model_dump() for r in cmp.rows]
        out["titles"] = [r.title for r in cmp.rows]
        out["compare_titles"] = " vs ".join(r.title for r in cmp.rows)
        first = cmp.rows[0]
        out.update(
            property_title=first.title, property_area=first.area, property_bedrooms=first.bedrooms,
            property_type=first.property_type, property_size=f"{first.size_sqft:,}" if first.size_sqft else None,
            property_price=f"{first.price:,.0f}" if first.price else None,
        )
    slots = tools.get("slots")
    if slots:
        labels = [s.label_ar if state.language == "ar" else s.label_en for s in slots]
        out["slots"] = labels
        out["slot_suggestion"] = (
            f"For example {labels[0]} or {labels[1]}." if state.language == "en" and len(labels) > 1 else (f"مثلاً {labels[0]} أو {labels[1]}." if len(labels) > 1 else "")
        )
    handoff = tools.get("handoff")
    if handoff:
        out["broker_name"] = handoff.get("broker_name") or ("a specialist" if state.language == "en" else "مختص")
        out["slot_text"] = handoff.get("slot_text") or ("shortly" if state.language == "en" else "قريباً")
    else:
        out["broker_name"] = "a specialist" if state.language == "en" else "مختص"
    return out


async def _handoff_broker_name(state: ConversationState, workspace_id: str) -> str:
    default = "our specialist" if state.language == "en" else "مختصنا"
    if not state.handoff_id:
        return default
    try:
        row = await table("handoffs", workspace_id).get(id=state.handoff_id)
    except Exception:
        return default
    return (row or {}).get("broker_name") or default


async def _schedule_followups(state: ConversationState, move: Move, workspace_id: str) -> None:
    try:
        if move == Move.OPT_OUT:
            await followups.cancel_followups(state.lead_id, workspace_id=workspace_id, reason="opt_out")
            lead = await get_lead_repository(workspace_id).get_by_id(state.lead_id)
            if lead:
                await suppress_contact(workspace_id, phone=lead.get("phone_e164") or lead.get("phone"), email=lead.get("email"), reason="opt_out")
        elif move in {Move.HANDOFF, Move.HANDOFF_NOW}:
            await followups.cancel_followups(state.lead_id, workspace_id=workspace_id, reason="handed_off")
        elif move == Move.NURTURE:
            await followups.schedule_followups(state.lead_id, state.band, workspace_id=workspace_id)
    except Exception as exc:
        logger.debug("followup scheduling skipped: %s", exc)


async def _mirror_lead(state: ConversationState, workspace_id: str) -> None:
    try:
        repo = get_lead_repository(workspace_id)
        lead = await repo.get_by_id(state.lead_id)
        if lead:
            updates = lead_updates_from_state(state)
            updates["intent_score"] = state.score
            await repo.update(state.lead_id, updates)
            changed = [k for k in ("score", "intent_score", "stage", "status", "band") if k in updates and lead.get(k) != updates[k]]
            if changed:
                await events.emit(state.lead_id, "lead.scored", {"changed_fields": changed, "score": state.score, "turn": state.turn}, workspace_id=workspace_id)
    except Exception as exc:
        logger.debug("lead mirror skipped: %s", exc)


def _jsonable(tools: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in tools.items():
        if isinstance(v, BaseModel):
            out[k] = v.model_dump(mode="json")
        elif isinstance(v, list):
            out[k] = [i.model_dump(mode="json") if isinstance(i, BaseModel) else i for i in v]
        else:
            out[k] = v
    return out


def _result(state: ConversationState, reply: str, move: str, tools: dict[str, Any], latency_ms: int, fallbacks: list[str], *, ended: bool = False, replay: bool = False) -> TurnResult:
    search = tools.get("search") or {}
    area = tools.get("area")
    cmp = tools.get("compare") or {}
    handoff = tools.get("handoff") or {}
    return TurnResult(
        reply=reply,
        move=move,
        stage=state.stage,
        score=state.score,
        band=state.band,
        score_reasons=list(state.score_reasons),
        turn=state.turn,
        profile=state.profile_values(),
        cards=list(search.get("cards") or []),
        area=area,
        compare=list(cmp.get("rows") or []),
        handoff_id=handoff.get("id") or state.handoff_id,
        ended=ended or state.stage in {"opted_out", "handed_off"},
        latency_ms=latency_ms,
        fallbacks=fallbacks,
        idempotent_replay=replay,
        language=state.language,
    )
