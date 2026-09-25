"""TypeSafe AI Jev scoring: request shape, blending with rules, and fallbacks."""
from __future__ import annotations

import json

import httpx
import pytest

from app.config import get_settings
from app.modules.agents import scorer
from app.modules.conversation.state import ConversationState
from app.modules.cowork import connections, routines
from app.modules.cowork.connections import ConnectionIn
from app.modules.cowork.routines import RoutineIn, Schedule, Step
from app.modules.llm import jev
from app.modules.store import reset_memory

WS = get_settings().WORKSPACE_ID


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    reset_memory()
    settings = get_settings()
    monkeypatch.setattr(settings, "TYPESAFE_API_KEY", "")
    monkeypatch.setattr(settings, "LEAD_SCORING_PROVIDER", "auto")
    monkeypatch.setattr(settings, "JEV_MIN_CONFIDENCE", 0.55)
    jev.set_client_factory(None)
    yield
    jev.set_client_factory(None)
    reset_memory()


def _answers(band="hot", conf=0.9, level=4, intent="buy", finance=0.8, viewing=0.7, human=0.6):
    probs = {str(i): 0.0 for i in range(5)}
    probs[str(level)] = 1.0
    return {
        "model": "jev-1.13.0",
        "answers": {
            "band": {"type": "choice", "choice": band, "confidence": conf, "probabilities": {band: conf}},
            "readiness": {"type": "score", "score": float(level), "confidence": 0.9, "probabilities": probs},
            "intent": {"type": "choice", "choice": intent, "confidence": 0.95, "probabilities": {intent: 0.95}},
            "finance_ready": {"type": "noul", "noul": finance},
            "viewing_intent": {"type": "noul", "noul": viewing},
            "needs_human": {"type": "noul", "noul": human},
        },
        "usage": {"input_tokens": 300, "output_tokens": 40},
    }


def _mock(handler):
    jev.set_client_factory(lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def _state(**slots) -> ConversationState:
    st = ConversationState(lead_id="l1", source="propertyfinder")
    for k, v in slots.items():
        st.set_slot(k, v)
    return st


# ------------------------------------------------------------------ client


@pytest.mark.asyncio
async def test_request_shape_and_parsed_answers(monkeypatch):
    monkeypatch.setattr(get_settings(), "TYPESAFE_API_KEY", "sk-test")
    seen = {}

    def handler(req: httpx.Request):
        seen["url"] = str(req.url)
        seen["auth"] = req.headers.get("authorization")
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json=_answers())

    _mock(handler)
    q = await jev.qualify({"purpose": "buy", "budget_aed": {"max_aed": 2_000_000}})
    assert seen["url"] == "https://api.typesafe.ai/v1/systemone"
    assert seen["auth"] == "Bearer sk-test"
    body = seen["body"]
    assert body["model"] == "jev-latest"
    assert body["state"]["purpose"] == "buy"
    assert body["questions"]["band"]["type"] == "choice" and set(body["questions"]["band"]["criteria"]) == {"hot", "warm", "cold"}
    assert body["questions"]["readiness"]["type"] == "score" and 2 <= len(body["questions"]["readiness"]["criteria"]) <= 10
    assert body["questions"]["finance_ready"]["type"] == "noul" and "criteria" not in body["questions"]["finance_ready"]
    assert q.band == "hot" and q.score == 92 and q.intent == "buy" and q.model == "jev-1.13.0"
    assert q.reasons[0].startswith("Jev: hot")


@pytest.mark.asyncio
async def test_expected_score_over_distribution(monkeypatch):
    monkeypatch.setattr(get_settings(), "TYPESAFE_API_KEY", "k")
    a = _answers()
    a["answers"]["readiness"]["probabilities"] = {"2": 0.5, "3": 0.5}
    a["answers"]["readiness"]["score"] = 2.5
    _mock(lambda r: httpx.Response(200, json=a))
    q = await jev.qualify({})
    assert q.score == 65  # mean of 55 and 75


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resp",
    [
        httpx.Response(401, json={"error": "bad key"}),
        httpx.Response(500, text="boom"),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"model": "jev", "answers": {"band": {"type": "choice", "choice": "hot", "confidence": 1.0}}}),
        httpx.Response(200, json=_answers(band="lukewarm")),
    ],
)
async def test_bad_replies_raise_unavailable(monkeypatch, resp):
    monkeypatch.setattr(get_settings(), "TYPESAFE_API_KEY", "k")
    _mock(lambda r: resp)
    with pytest.raises(jev.JevUnavailable):
        await jev.qualify({})


@pytest.mark.asyncio
async def test_timeout_raises_unavailable(monkeypatch):
    monkeypatch.setattr(get_settings(), "TYPESAFE_API_KEY", "k")

    def handler(_):
        raise httpx.ReadTimeout("slow")

    _mock(handler)
    with pytest.raises(jev.JevUnavailable):
        await jev.qualify({})


@pytest.mark.asyncio
async def test_not_configured_raises():
    with pytest.raises(jev.JevUnavailable):
        await jev.qualify({})


# ------------------------------------------------------------------ scorer blend


@pytest.mark.asyncio
async def test_rules_only_when_no_key():
    st = _state(purpose="buy", budget={"max_aed": 2_000_000}, timeline="1_month")
    q = await scorer.qualify(st)
    base, _ = scorer.score(st)
    assert q.provider == "rules" and q.score == base and q.jev is None


@pytest.mark.asyncio
async def test_jev_upgrades_band_when_confident(monkeypatch):
    monkeypatch.setattr(get_settings(), "TYPESAFE_API_KEY", "k")
    _mock(lambda r: httpx.Response(200, json=_answers(band="hot", conf=0.92, level=4)))
    st = _state(purpose="buy", budget={"max_aed": 2_000_000}, timeline="6_months", area=["Dubai Marina"], property_type="apartment")
    base, _ = scorer.score(st)
    assert scorer.band_for(base) == "warm"
    q = await scorer.qualify(st)
    assert q.provider == "jev" and q.band == "hot" and 70 <= q.score <= 100
    assert q.jev["model"] == "jev-1.13.0"


@pytest.mark.asyncio
async def test_jev_cannot_make_empty_lead_hot(monkeypatch):
    monkeypatch.setattr(get_settings(), "TYPESAFE_API_KEY", "k")
    _mock(lambda r: httpx.Response(200, json=_answers(band="hot", conf=0.99, level=4)))
    q = await scorer.qualify(_state(purpose="buy"))
    assert q.band == "warm" and q.score <= 69


@pytest.mark.asyncio
async def test_jev_low_confidence_keeps_rules_band(monkeypatch):
    monkeypatch.setattr(get_settings(), "TYPESAFE_API_KEY", "k")
    _mock(lambda r: httpx.Response(200, json=_answers(band="cold", conf=0.4)))
    st = _state(purpose="buy", budget={"max_aed": 2_000_000}, timeline="1_month", payment="cash")
    q = await scorer.qualify(st)
    base, _ = scorer.score(st)
    assert q.provider == "rules" and q.band == scorer.band_for(base) and q.jev is not None


@pytest.mark.asyncio
async def test_jev_can_only_downgrade_one_band(monkeypatch):
    monkeypatch.setattr(get_settings(), "TYPESAFE_API_KEY", "k")
    _mock(lambda r: httpx.Response(200, json=_answers(band="cold", conf=0.95, level=0)))
    st = _state(purpose="buy", budget={"max_aed": 2_000_000}, timeline="asap", payment="cash", area=["Dubai Marina"], property_type="apartment")
    base, _ = scorer.score(st)
    assert scorer.band_for(base) == "hot"
    q = await scorer.qualify(st)
    assert q.band == "warm"


@pytest.mark.asyncio
async def test_jev_failure_falls_back_and_records(monkeypatch):
    monkeypatch.setattr(get_settings(), "TYPESAFE_API_KEY", "k")
    _mock(lambda r: httpx.Response(503))
    fallbacks: list[str] = []
    st = _state(purpose="buy", budget={"max_aed": 2_000_000})
    q = await scorer.qualify(st, fallbacks=fallbacks)
    assert q.provider == "rules" and fallbacks == ["score:rules_only"]
    assert any("Jev unavailable" in r for r in q.reasons)


@pytest.mark.asyncio
async def test_provider_rules_disables_jev(monkeypatch):
    monkeypatch.setattr(get_settings(), "TYPESAFE_API_KEY", "k")
    monkeypatch.setattr(get_settings(), "LEAD_SCORING_PROVIDER", "rules")
    calls = []
    _mock(lambda r: calls.append(1) or httpx.Response(200, json=_answers()))
    q = await scorer.qualify(_state(purpose="buy"))
    assert q.provider == "rules" and not calls


# ------------------------------------------------------------------ co-work provider + routine


@pytest.mark.asyncio
async def test_typesafe_connection_test_pings_models(monkeypatch):
    def handler(req: httpx.Request):
        assert str(req.url) == "https://api.typesafe.ai/v1/models"
        assert req.headers["authorization"] == "Bearer conn-key"
        return httpx.Response(200, json={"data": [{"id": "jev-latest"}]})

    _mock(handler)
    row = await connections.create_connection(WS, ConnectionIn(provider="typesafe_jev", display_name="Jev", config={"api_key": "conn-key"}), actor="t")
    res = await connections.test_connection(WS, row["id"])
    assert res["status"] == "ok"
    listed = [c for c in await connections.list_connections(WS) if c["id"] == row["id"]][0]
    assert listed["health"] == "connected"
    assert "conn-key" not in json.dumps(listed)


@pytest.mark.asyncio
async def test_typesafe_connection_test_rejected_key():
    _mock(lambda r: httpx.Response(401))
    row = await connections.create_connection(WS, ConnectionIn(provider="typesafe_jev", display_name="Jev", config={"api_key": "bad"}), actor="t")
    res = await connections.test_connection(WS, row["id"])
    assert res["status"] == "failed" and "rejected" in res["detail"]


async def _seed_lead():
    from app.database import get_lead_repository

    repo = get_lead_repository(WS)
    return await repo.create({"first_name": "Sara", "phone": "+971500000001", "purpose": "buy", "budget_max_aed": 1_500_000, "timeline": "3_months", "stage": "new", "score": 45, "band": "warm", "status": "new"})


@pytest.mark.asyncio
async def test_routine_qualify_uses_connection_key():
    await _seed_lead()
    seen = {}

    def handler(req: httpx.Request):
        seen["auth"] = req.headers.get("authorization")
        seen["model"] = json.loads(req.content)["model"]
        return httpx.Response(200, json=_answers(band="hot", conf=0.9))

    _mock(handler)
    row = await connections.create_connection(WS, ConnectionIn(provider="typesafe_jev", display_name="Jev", config={"api_key": "conn-key", "model": "jev-1.13.0"}), actor="t")
    routine = await routines.create_routine(
        WS,
        RoutineIn(name="q", schedule=Schedule(kind="interval", seconds=3600), steps=[Step(type="leads.select", params={"limit": 10}), Step(type="llm.qualify", connection_id=row["id"])]),
        actor="t",
    )
    run = await routines.run_routine(WS, routine["id"], trigger="manual")
    step = run["steps"][1]
    assert step["status"] == "success", step
    assert step["summary"]["jev"] >= 1 and step["summary"]["rules"] == 0 and step["summary"]["provider"] == "typesafe_jev"
    assert seen["auth"] == "Bearer conn-key" and seen["model"] == "jev-1.13.0"


@pytest.mark.asyncio
async def test_routine_qualify_without_jev_is_simulated_with_reason():
    await _seed_lead()
    routine = await routines.create_routine(
        WS,
        RoutineIn(name="q", schedule=Schedule(kind="interval", seconds=3600), steps=[Step(type="leads.select", params={"limit": 10}), Step(type="llm.qualify")]),
        actor="t",
    )
    run = await routines.run_routine(WS, routine["id"], trigger="manual")
    step = run["steps"][1]
    assert step["status"] == "simulated"
    assert "Jev not configured" in step["summary"]["reason"]


@pytest.mark.asyncio
async def test_routine_rejects_non_scoring_connection_for_qualify():
    row = await connections.create_connection(WS, ConnectionIn(provider="slack", display_name="Slack", config={}), actor="t")
    with pytest.raises(ValueError):
        await routines.create_routine(
            WS,
            RoutineIn(name="q", schedule=Schedule(kind="interval", seconds=3600), steps=[Step(type="llm.qualify", connection_id=row["id"])]),
            actor="t",
        )
