"""Operational metrics, alert thresholds and deep health."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import get_lead_repository
from app.main import app
from app.modules.conversation.engine import handle_turn
from app.modules.llm import gateway as llm_gateway
from app.modules.ops import metrics
from app.modules.ops.health import deep_health
from app.modules.store import reset_memory, table

client = TestClient(app, raise_server_exceptions=False)
WS = get_settings().WORKSPACE_ID


@pytest.fixture(autouse=True)
def _clean():
    reset_memory()
    llm_gateway.reset_gateway()
    yield
    reset_memory()
    llm_gateway.reset_gateway()


def test_summarize_turns_percentiles_and_fallback_classes():
    rows = [
        {"meta": {"latency_ms": 100, "fallbacks": ["extract:rules_only"], "move": "suggest"}},
        {"meta": {"latency_ms": 300, "fallbacks": ["template:llm_unavailable"], "move": "suggest"}},
        {"meta": {"latency_ms": 900, "fallbacks": ["template:guard_rejected", "tool:search"], "move": "ask_next_field"}},
        {"meta": {"latency_ms": 200, "fallbacks": ["replay"], "move": "suggest"}},
    ]
    s = metrics.summarize_turns(rows)
    assert s["turns"] == 4
    assert s["latency_ms"] == {"p50": 200, "p95": 900, "max": 900}
    assert s["fallback_turns"] == 2 and s["fallback_rate"] == 0.5
    assert s["guard_failures"] == 1 and s["tool_failures"] == 1 and s["llm_fallbacks"] == 1
    assert s["moves"] == {"suggest": 3, "ask_next_field": 1}
    assert metrics.summarize_turns([])["latency_ms"] == {"p50": None, "p95": None, "max": None}


@pytest.mark.asyncio
async def test_collect_reads_real_turns_and_raises_alerts():
    lead = await get_lead_repository(WS).create({"name": "Ops", "phone": "+971500009999", "source": "crm", "status": "new"})
    await handle_turn(lead["id"], "2 bed apartment in dubai marina", workspace_id=WS)
    await handle_turn(lead["id"], "budget 2 million to buy", workspace_id=WS)

    now = datetime.now(timezone.utc)
    stale = (now - timedelta(minutes=20)).isoformat()
    await table("connectors", WS).insert({"id": "c-bad", "type": "generic_crm", "display_name": "Bad CRM", "status": "active", "consecutive_failures": 3})
    for i in range(21):
        await table("review_queue", WS).insert({"id": f"rq-{i}", "raw_id": f"raw-{i}", "reason": "missing_phone", "resolved_at": None})
    await table("lead_events", WS).insert({"id": "ev-old", "lead_id": lead["id"], "type": "lead.scored", "payload": {}, "created_at": stale})

    report = await metrics.collect(WS, now=now)
    assert report["window"]["turns"] == 2
    assert report["window"]["latency_ms"]["p95"] is not None
    assert report["llm_configured"] is False
    assert report["consumers"]["crm_writeback"]["pending"] >= 1
    assert report["consumers"]["crm_writeback"]["lag_s"] >= 1200
    assert report["review_open"] == 21
    codes = sorted(a["code"] for a in report["alerts"])
    assert codes == ["connector_failing", "consumer_lag", "review_queue"]


@pytest.mark.asyncio
async def test_fallback_alert_only_when_llm_configured(monkeypatch):
    for i in range(10):
        await table("messages", WS).insert({"lead_id": "l", "role": "assistant", "text": "x", "meta": {"latency_ms": 50, "fallbacks": ["template:llm_unavailable"], "move": "suggest"}})
    report = await metrics.collect(WS)
    assert report["window"]["fallback_rate"] == 1.0
    assert not [a for a in report["alerts"] if a["code"] == "fallback_rate"]

    class Gateway:
        available = True

    monkeypatch.setattr(metrics, "get_gateway", lambda: Gateway())
    report = await metrics.collect(WS)
    assert [a["code"] for a in report["alerts"]] == ["fallback_rate"]


def test_ops_endpoint_requires_admin_and_returns_thresholds():
    r = client.get("/api/v1/admin/ops")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["thresholds"] == {"fallback_rate": 0.05, "consumer_lag_s": 300, "connector_failures": 3, "review_queue": 20}
    assert body["alerts"] == [] and body["window"]["turns"] == 0


def test_health_deep_reports_each_dependency(monkeypatch):
    from app.modules.ops import health

    async def redis_down():
        raise ConnectionError("refused")

    monkeypatch.setattr(health, "_redis", redis_down)
    report = asyncio.get_event_loop().run_until_complete(deep_health(WS))
    by_name = {c["name"]: c for c in report["checks"]}
    assert by_name["database"]["status"] == "ok" and by_name["database"]["mode"] == "memory"
    assert by_name["redis"]["status"] == "down" and by_name["redis"]["error"] == "ConnectionError"
    assert by_name["llm"]["status"] == "fallback" and by_name["llm"]["providers"]
    assert report["status"] == "unhealthy"

    r = client.get("/health/deep")
    assert r.status_code == 503 and r.json()["status"] == "unhealthy"

    async def redis_slow():
        await asyncio.sleep(5)
        return {}

    monkeypatch.setattr(health, "_redis", redis_slow)
    monkeypatch.setattr(health, "PROBE_TIMEOUT_S", 0.05)
    report = asyncio.get_event_loop().run_until_complete(deep_health(WS))
    assert report["status"] == "degraded"
    assert {c["name"]: c["status"] for c in report["checks"]}["redis"] == "degraded"
