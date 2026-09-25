"""Deep dependency health: bounded probes of the datastore, Redis, and LLM breakers.

Every probe is time-boxed so ``/health/deep`` itself can never hang a load
balancer check; a slow dependency reports ``degraded`` rather than blocking.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

import redis.asyncio as aioredis

from app.config import get_settings
from app.database import DatabaseClient, _use_mock_store
from app.modules.llm.gateway import get_gateway

PROBE_TIMEOUT_S = 2.0


async def _timed(name: str, probe: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
    started = time.monotonic()
    try:
        detail = await asyncio.wait_for(probe(), timeout=PROBE_TIMEOUT_S)
        status = detail.pop("status", "ok")
    except asyncio.TimeoutError:
        status, detail = "degraded", {"error": f"timeout after {PROBE_TIMEOUT_S}s"}
    except Exception as exc:
        status, detail = "down", {"error": type(exc).__name__}
    return {"name": name, "status": status, "latency_ms": int((time.monotonic() - started) * 1000), **detail}


async def _database(workspace_id: str) -> dict[str, Any]:
    if _use_mock_store():
        return {"status": "ok", "mode": "memory"}
    if DatabaseClient.get_client() is None:
        return {"status": "down", "mode": "supabase", "error": "client_init_failed"}
    # The Supabase SDK is synchronous; run it off the event loop so the probe
    # timeout can fire and other requests keep being served while it stalls.
    await asyncio.to_thread(_sync_workspace_probe, workspace_id)
    return {"status": "ok", "mode": "supabase"}


def _sync_workspace_probe(workspace_id: str) -> None:
    client = DatabaseClient.get_client()
    if client is None:
        raise RuntimeError("client_init_failed")
    client.table("workspaces").select("id").eq("id", workspace_id).limit(1).execute()


async def _redis() -> dict[str, Any]:
    url = get_settings().REDIS_URL
    if not url:
        return {"status": "disabled"}
    client = aioredis.from_url(url, socket_connect_timeout=PROBE_TIMEOUT_S, socket_timeout=PROBE_TIMEOUT_S)
    try:
        await client.ping()
    finally:
        await client.aclose()
    return {"status": "ok"}


async def _llm() -> dict[str, Any]:
    gateway = get_gateway()
    providers = [
        {"name": p.name, "configured": p.configured(), "breaker_open": not gateway.breakers[p.name].allow()}
        for p in gateway.providers
    ]
    configured = [p for p in providers if p["configured"]]
    if not configured:
        return {"status": "fallback", "providers": providers}
    return {"status": "ok" if gateway.available else "degraded", "providers": providers}


async def deep_health(workspace_id: str) -> dict[str, Any]:
    checks = await asyncio.gather(
        _timed("database", lambda: _database(workspace_id)),
        _timed("redis", _redis),
        _timed("llm", _llm),
    )
    statuses = {c["status"] for c in checks}
    if "down" in statuses:
        overall = "unhealthy"
    elif "degraded" in statuses:
        overall = "degraded"
    else:
        overall = "healthy"
    return {"status": overall, "checks": checks}
