"""Conversation engine: rules-first extraction, deterministic policy/scoring,
grounded replies, idempotent persisted turns, and LLM fault tolerance."""
from __future__ import annotations

import asyncio
from datetime import datetime, time, timezone

import pytest

from app.modules.agents import guard, scorer
from app.modules.agents.extractor import extract_rules
from app.modules.conversation.engine import handle_turn
from app.modules.conversation.moves import Move
from app.modules.conversation.policy import decide
from app.modules.conversation.repository import ConversationRepo
from app.modules.conversation.state import ConversationState
from app.modules.geo.communities import resolve_area
from app.modules.handoff.routing import BrokerProfile, route
from app.modules.leads import profile
from app.modules.llm import gateway as llm_gateway
from app.modules.llm.providers.base import Completion, ProviderError
from app.modules.store import reset_memory, table
from app.database import get_lead_repository

WS = "00000000-0000-0000-0000-000000000001"


@pytest.fixture(autouse=True)
def _clean():
    reset_memory()
    llm_gateway.reset_gateway()
    yield
    reset_memory()
    llm_gateway.reset_gateway()


def _state(**profile_values) -> ConversationState:
    state = ConversationState(lead_id="lead-1", channel="chat")
    for k, v in profile_values.items():
        state.set_slot(k, v, source="buyer")
    return state


async def _lead(name="Test Buyer", phone="+971500000001", source="crm") -> dict:
    repo = get_lead_repository(WS)
    return await repo.create({"name": name, "phone": phone, "source": source, "status": "new", "score": 0})


# --------------------------------------------------------------------- gazetteer
@pytest.mark.parametrize(
    "text,expected",
    [
        ("dubai hils", "dubai_hills"),
        ("JVC", "jvc"),
        ("marina", "dubai_marina"),
        ("داون تاون", "downtown_dubai"),
    ],
)
def test_resolve_area_aliases(text, expected):
    matches = resolve_area(text)
    assert matches and matches[0].community.id == expected


def test_resolve_area_unknown_returns_nothing():
    assert resolve_area("somewhere in the desert xyz") == []


# --------------------------------------------------------------------- extractor
def test_extractor_stop_is_authoritative():
    facts = extract_rules("STOP", _state())
    assert facts.intent == "stop"


def test_extractor_human_request():
    facts = extract_rules("can I speak to a real agent please", _state())
    assert facts.intent == "request_human"


def test_extractor_slots_from_one_message():
    facts = extract_rules("2 bed apartment in dubai marina, budget 2.5m to buy, cash, within 3 months", _state())
    assert facts.slots.bedrooms == 2
    assert facts.slots.property_type == "apartment"
    assert "dubai_marina" in facts.area_candidates
    assert facts.slots.purpose == "buy"
    assert facts.slots.payment == "cash"
    assert facts.slots.timeline == "3_months"


def test_extractor_detects_arabic():
    facts = extract_rules("أبحث عن شقة في مرسى دبي", _state())
    assert facts.language == "ar"
    assert "dubai_marina" in facts.area_candidates


# --------------------------------------------------------------------- merge
def test_budget_merge_clarifies_ambiguous_magnitude():
    state = _state(purpose="buy")
    facts = extract_rules("budget is 2.5", state)
    state = profile.merge(state, facts)
    assert state.value("budget") is None
    assert state.value("budget_pending") is not None

    facts2 = extract_rules("million", state)
    state = profile.merge(state, facts2)
    assert state.value("budget")["max_aed"] == 2_500_000


def test_budget_merge_assumes_aed():
    state = profile.merge(_state(), extract_rules("my budget is 1.8 million to buy", _state()))
    assert state.value("budget")["max_aed"] == 1_800_000
    assert state.value("budget")["currency"] == "AED"


def test_merge_never_downgrades_confirmed_slot():
    state = _state()
    state.set_slot("area", ["Dubai Marina"], source="buyer", confirmed=True)
    facts = extract_rules("what about downtown", state)
    merged = profile.merge(state, facts)
    assert merged.value("area")
    assert merged.profile["area"].source == "buyer"


# --------------------------------------------------------------------- scorer
def test_scorer_bands_and_reasons():
    cold, reasons = scorer.score(_state())
    assert cold < 40 and scorer.band_for(cold) == "cold"

    hot_state = _state(
        purpose="buy", budget={"max_aed": 2_500_000, "currency": "AED", "period": "total"}, area=["Dubai Marina"],
        property_type="apartment", timeline="3_months", payment="cash",
    )
    hot_state.source = "crm"
    hot_state.set_slot("bedrooms", 2, source="buyer")
    hot, reasons = scorer.score(hot_state)
    assert hot >= 60
    assert any("budget" in r.lower() for r in reasons)
    assert scorer.band_for(75) == "hot" and scorer.band_for(50) == "warm"


def test_scorer_is_deterministic():
    s = _state(purpose="buy", budget={"max_aed": 1_000_000, "currency": "AED"}, timeline="6_months")
    assert scorer.score(s) == scorer.score(s)


# --------------------------------------------------------------------- policy
def test_policy_stop_wins_over_everything():
    state = _state(purpose="buy")
    facts = extract_rules("stop messaging me", state)
    assert decide(state, facts).move == Move.OPT_OUT


def test_policy_human_request_hands_off_immediately():
    state = _state()
    facts = extract_rules("I want to talk to a human", state)
    assert decide(state, facts).move == Move.HANDOFF_NOW


def test_policy_asks_one_missing_field_and_never_repeats_past_limit():
    state = _state()
    state.turn = 2
    facts = extract_rules("hello", state)
    first = decide(state, facts)
    assert first.move == Move.ASK_NEXT_FIELD
    field = first.field
    state.asked[field] = 2
    second = decide(state, facts)
    assert second.field != field


def test_policy_suggests_when_required_known():
    state = _state(purpose="buy", budget={"max_aed": 2_000_000, "currency": "AED"}, area=["Dubai Marina"], property_type="apartment")
    state.turn = 1
    facts = extract_rules("ok", state)
    assert decide(state, facts).move == Move.SUGGEST


# --------------------------------------------------------------------- guard
def test_guard_rejects_ungrounded_numbers():
    facts = {"cards": [{"price": 2_500_000, "title": "Marina View"}]}
    assert guard.check("This one is AED 3,100,000.", facts, language="en", max_sentences=4) is None
    assert guard.check("Marina View is AED 2,500,000.", facts, language="en", max_sentences=4)


def test_guard_rejects_language_mismatch_and_banned_phrases():
    assert guard.check("Here you go.", {}, language="ar", max_sentences=4) is None
    assert guard.check("Guaranteed returns of 10%.", {}, language="en", max_sentences=4) is None


# --------------------------------------------------------------------- routing
def _broker(id_, **kw) -> BrokerProfile:
    return BrokerProfile(id=id_, name=id_, **kw)


def test_routing_prefers_language_area_and_least_loaded():
    brokers = [
        _broker("a", languages=["en"], community_ids=["dubai_marina"], active_leads=5),
        _broker("b", languages=["ar", "en"], community_ids=["dubai_marina"], active_leads=2),
        _broker("c", languages=["ar"], community_ids=[], active_leads=0),
    ]
    decision = route(brokers, language="ar", community_ids=["dubai_marina"])
    assert decision.broker and decision.broker.id == "b"


def test_routing_respects_capacity_shift_and_exclusions():
    now = datetime(2026, 1, 5, 20, 0, tzinfo=timezone.utc)  # 00:00 Dubai
    brokers = [
        _broker("full", active_leads=10, max_leads=10),
        _broker("off", shift_start=time(9, 0), shift_end=time(18, 0)),
        _broker("tried"),
        _broker("ok"),
    ]
    decision = route(brokers, language="en", community_ids=[], now=now, exclude_ids={"tried"})
    assert decision.broker and decision.broker.id == "ok"
    assert route(brokers[:1], language="en", community_ids=[], now=now).broker is None
    off_hours = route(brokers[:2], language="en", community_ids=[], now=now)
    assert off_hours.broker and off_hours.broker.id == "off"
    assert any("shift" in r for r in off_hours.reasons)


# --------------------------------------------------------------------- engine
@pytest.mark.asyncio
async def test_engine_full_flow_persists_and_hands_off():
    lead = await _lead()
    turns = [
        "hi, looking for a 2 bed apartment in dubai marina",
        "budget 2.5 million to buy",
        "within 3 months, paying cash",
        "yes please",
    ]
    results = [await handle_turn(lead["id"], t, workspace_id=WS, source="crm") for t in turns]
    assert all(r.reply for r in results)
    assert results[0].move == "ask_next_field"
    assert results[1].move == "suggest" and results[1].cards
    assert results[-1].move == "handoff" and results[-1].handoff_id

    repo = ConversationRepo(WS)
    state = await repo.load(lead["id"])
    assert state.stage == "handed_off" and state.turn == 4
    history = await repo.history(lead["id"])
    assert len(history) == 8
    handoff = await table("handoffs", WS).get(id=results[-1].handoff_id)
    assert handoff and handoff["brief"]["profile"]
    assert (await get_lead_repository(WS).get_by_id(lead["id"]))["score"] == results[-1].score

    viewings = await table("viewings", WS).select(lead_id=lead["id"])
    assert len(viewings) == 1
    v = viewings[0]
    assert v["status"] == "requested" and v["source"] == "buyer" and v["starts_at"]
    assert v["property_id"] in {c["property_id"] for c in results[1].cards}
    assert v["broker_id"] == handoff["broker_id"]


@pytest.mark.asyncio
async def test_engine_idempotent_replay():
    lead = await _lead(phone="+971500000002")
    a = await handle_turn(lead["id"], "hello", workspace_id=WS, idempotency_key="k1")
    b = await handle_turn(lead["id"], "hello", workspace_id=WS, idempotency_key="k1")
    assert b.idempotent_replay and b.reply == a.reply
    assert (await ConversationRepo(WS).load(lead["id"])).turn == 1


@pytest.mark.asyncio
async def test_engine_stop_opts_out_and_stays_quiet():
    lead = await _lead(phone="+971500000003")
    r = await handle_turn(lead["id"], "STOP", workspace_id=WS)
    assert r.move == "opt_out" and r.ended
    assert (await ConversationRepo(WS).load(lead["id"])).stage == "opted_out"


@pytest.mark.asyncio
async def test_engine_after_handoff_does_not_requalify():
    lead = await _lead(phone="+971500000004")
    await handle_turn(lead["id"], "get me a human now", workspace_id=WS)
    r = await handle_turn(lead["id"], "hello?", workspace_id=WS)
    assert r.move == "after_handoff"
    assert (await ConversationRepo(WS).load(lead["id"])).stage == "handed_off"


class _BrokenProvider:
    name = "broken"

    def configured(self) -> bool:
        return True

    async def complete(self, messages, *, tier, timeout_s, json_mode, max_tokens, temperature) -> Completion:
        raise ProviderError("boom")


class _SlowProvider(_BrokenProvider):
    name = "slow"

    async def complete(self, messages, *, tier, timeout_s, json_mode, max_tokens, temperature) -> Completion:
        await asyncio.sleep(timeout_s + 1)
        return Completion(text="late", provider="slow", model="m", latency_ms=0)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", [_BrokenProvider(), _SlowProvider()])
async def test_engine_replies_when_llm_fails_or_hangs(monkeypatch, provider):
    monkeypatch.setattr(llm_gateway, "_gateway", llm_gateway.LLMGateway(providers=[provider]))
    lead = await _lead(phone="+971500000005")
    started = asyncio.get_event_loop().time()
    r = await handle_turn(lead["id"], "2 bed apartment in JVC, 1.2m to buy", workspace_id=WS)
    assert r.reply and r.move in {"ask_next_field", "suggest"}
    assert "extract:rules_only" in r.fallbacks and "template:llm_unavailable" in r.fallbacks
    assert asyncio.get_event_loop().time() - started < 6.5


@pytest.mark.asyncio
async def test_engine_concurrent_turns_serialise_per_lead():
    lead = await _lead(phone="+971500000006")
    await asyncio.gather(*[handle_turn(lead["id"], f"message {i}", workspace_id=WS) for i in range(5)])
    assert (await ConversationRepo(WS).load(lead["id"])).turn == 5


@pytest.mark.asyncio
async def test_engine_area_answer_quotes_only_stored_travel_numbers():
    lead = await _lead(phone="+971500000004")
    r = await handle_turn(lead["id"], "how far is dubai marina from downtown?", workspace_id=WS)
    assert r.move == "answer_area" and r.area
    travel = r.area["travel"]
    assert travel and travel[0]["to_id"] == "downtown" and travel[0]["approx"] is True
    assert str(travel[0]["minutes"]) in r.reply and ("approx" in r.reply or "about" in r.reply)


@pytest.mark.asyncio
async def test_engine_turn_emits_lead_scored_for_writeback():
    lead = await _lead(phone="+971500000005")
    await handle_turn(lead["id"], "2 bed apartment in marina, budget 2.5m to buy", workspace_id=WS)
    evs = await table("lead_events", WS).select(lead_id=lead["id"], type="lead.scored")
    assert evs and "score" in evs[0]["payload"]["changed_fields"]


@pytest.mark.asyncio
async def test_engine_property_id_pins_card_actions_to_that_listing():
    lead = await _lead()
    await handle_turn(lead["id"], "2 bed apartment in dubai marina", workspace_id=WS)
    shown = await handle_turn(lead["id"], "budget 2.5 million to buy", workspace_id=WS)
    assert len(shown.cards) >= 2
    target = shown.cards[-1]["property_id"]

    r = await handle_turn(lead["id"], f"Tell me more about {shown.cards[-1]['title']}", workspace_id=WS, property_id=target)
    assert r.move == "answer_property"
    assert [c["property_id"] for c in r.compare] == [target]

    r = await handle_turn(lead["id"], f"I like {shown.cards[-1]['title']}", workspace_id=WS, property_id=target)
    state = await ConversationRepo(WS).load(lead["id"])
    liked = [p.property_id for p in state.shortlist if p.reaction == "liked"]
    assert liked == [target]

    r = await handle_turn(lead["id"], "I like this one", workspace_id=WS, property_id="not-a-shown-property")
    assert r.reply
    state = await ConversationRepo(WS).load(lead["id"])
    assert [p.property_id for p in state.shortlist if p.reaction == "liked"] == [target]
