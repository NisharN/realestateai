"""Co-work job registry: every scheduled background job, runnable on demand.

The Celery beat schedule in ``app.worker`` is the *timer*; this module is the
*catalogue*. Each job is described once here (id, label, default interval,
category) together with the async runner the worker uses, so the Co-work page
can list them, toggle them, run them now, and show a shared run history
regardless of whether the trigger was beat, a person, or an automation.

Per-workspace overrides (enabled / interval) live in ``cowork_job_settings``;
every execution is recorded in ``cowork_job_runs``.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from app.modules.store import Row, chunked, new_id, now_iso, table

logger = logging.getLogger(__name__)

Runner = Callable[[str], Awaitable[dict[str, Any]]]
Trigger = Literal["schedule", "manual", "automation"]
Category = Literal["intake", "engagement", "sync", "compliance", "housekeeping"]


@dataclass(frozen=True)
class JobSpec:
    id: str
    label: str
    description: str
    category: Category
    default_interval_s: int
    runner: Runner
    default_enabled: bool = True


async def _poll_connectors(workspace_id: str) -> dict[str, Any]:
    from app.modules.ingestion.connectors.crm_pull import (
        due_pull_connectors,
        poll_connector,
    )
    from app.modules.ingestion.pipeline.processor import process_many

    landed = processed = 0
    connectors = await due_pull_connectors(workspace_id)
    for connector in connectors:
        result = await poll_connector(connector["id"], workspace_id=workspace_id)
        ids = result.get("raw_ids", [])
        landed += len(ids)
        for batch in chunked(ids, PROCESS_BATCH):
            processed += len(await process_many(batch, workspace_id=workspace_id))
    return {"connectors": len(connectors), "landed": landed, "processed": processed}


async def _retry_errors(workspace_id: str) -> dict[str, Any]:
    from app.modules.ingestion.pipeline.processor import process_stranded, retry_errors

    retried = await retry_errors(workspace_id)
    stranded = await process_stranded(workspace_id)
    return {"retried": len(retried), "stranded": len(stranded)}


async def _followups(workspace_id: str) -> dict[str, Any]:
    from app.modules.handoff.followups import send_due

    return {"sent": len(await send_due(workspace_id))}


async def _reassign(workspace_id: str) -> dict[str, Any]:
    from app.modules.handoff.service import reassign_stale

    return {"reassigned": len(await reassign_stale(workspace_id))}


async def _writeback(workspace_id: str) -> dict[str, Any]:
    from app.modules.ingestion.writeback import run_writeback

    return {"events": await run_writeback(workspace_id)}


async def _automations(workspace_id: str) -> dict[str, Any]:
    from app.modules.cowork.automations import run_automations

    return await run_automations(workspace_id)


async def _routines(workspace_id: str) -> dict[str, Any]:
    from app.modules.cowork.routines import run_due

    return await run_due(workspace_id)


async def _retention(workspace_id: str) -> dict[str, Any]:
    from app.modules.privacy.service import retention_purge

    return dict(await retention_purge(workspace_id))


JOBS: tuple[JobSpec, ...] = (
    JobSpec("poll_pull_connectors", "Poll CRM connectors", "Pull new/changed records from every due CRM connector and run them through the pipeline.", "intake", 60, _poll_connectors),
    JobSpec("retry_ingestion_errors", "Retry failed records", "Re-run raw records that errored in the pipeline and recover stranded ones.", "intake", 120, _retry_errors),
    JobSpec("run_automations", "Run task automations", "Evaluate enabled automation rules against new lead events.", "engagement", 60, _automations),
    JobSpec("send_due_followups", "Send due follow-ups", "Deliver scheduled follow-up messages inside the contact window, re-checking consent.", "engagement", 300, _followups),
    JobSpec("reassign_stale_handoffs", "Reassign stale handoffs", "Route handoffs no broker accepted in time to the next available broker.", "engagement", 60, _reassign),
    JobSpec("crm_writeback", "CRM write-back", "Push score/stage/assignment changes back to the originating CRM (idempotent outbox).", "sync", 60, _writeback),
    JobSpec("retention_purge", "PDPL retention purge", "Erase or anonymise lead data past its retention period.", "compliance", 86_400, _retention),
    JobSpec("run_routines", "Run due routines", "Execute every enabled routine whose schedule is due (connector, data and LLM steps).", "engagement", 60, _routines),
)
JOB_INDEX: dict[str, JobSpec] = {j.id: j for j in JOBS}

SETTINGS_TABLE = "cowork_job_settings"
RUNS_TABLE = "cowork_job_runs"
LEASES_TABLE = "cowork_job_leases"
PROCESS_BATCH = 500
LEASE_S = 600


def get_spec(job_id: str) -> JobSpec:
    try:
        return JOB_INDEX[job_id]
    except KeyError:
        raise KeyError(f"unknown job {job_id!r}") from None


async def _settings(workspace_id: str) -> dict[str, Row]:
    rows = await table(SETTINGS_TABLE, workspace_id).select(limit=len(JOBS) + 10)
    return {r["job_id"]: r for r in rows}


def _effective(spec: JobSpec, row: Row | None) -> dict[str, Any]:
    enabled = spec.default_enabled if not row or row.get("enabled") is None else bool(row["enabled"])
    interval = int((row or {}).get("interval_s") or spec.default_interval_s)
    return {
        "id": spec.id,
        "label": spec.label,
        "description": spec.description,
        "category": spec.category,
        "enabled": enabled,
        "interval_s": interval,
        "default_interval_s": spec.default_interval_s,
    }


async def list_jobs(workspace_id: str) -> list[dict[str, Any]]:
    settings = await _settings(workspace_id)
    runs_t = table(RUNS_TABLE, workspace_id)
    out: list[dict[str, Any]] = []
    for spec in JOBS:
        job = _effective(spec, settings.get(spec.id))
        last = await runs_t.select(job_id=spec.id, order="started_at", desc=True, limit=1)
        job["last_run"] = last[0] if last else None
        job["next_run_at"] = _next_run(job, last[0] if last else None)
        out.append(job)
    return out


def _next_run(job: dict[str, Any], last: Row | None) -> str | None:
    if not job["enabled"]:
        return None
    if not last or not last.get("started_at"):
        return now_iso()
    started = datetime.fromisoformat(last["started_at"])
    return (started + timedelta(seconds=job["interval_s"])).isoformat()


async def update_job(workspace_id: str, job_id: str, *, enabled: bool | None = None, interval_s: int | None = None) -> dict[str, Any]:
    spec = get_spec(job_id)
    t = table(SETTINGS_TABLE, workspace_id)
    row = await t.get(job_id=job_id) or {"id": new_id(), "job_id": job_id, "enabled": spec.default_enabled, "interval_s": spec.default_interval_s}
    if enabled is not None:
        row["enabled"] = enabled
    if interval_s is not None:
        row["interval_s"] = max(30, min(int(interval_s), 7 * 86_400))
    row["updated_at"] = now_iso()
    saved = await t.upsert(row, on_conflict="workspace_id,job_id")
    return _effective(spec, saved)


async def is_enabled(workspace_id: str, job_id: str) -> bool:
    row = await table(SETTINGS_TABLE, workspace_id).get(job_id=job_id)
    return _effective(get_spec(job_id), row)["enabled"]


async def is_due(workspace_id: str, job_id: str, now: datetime | None = None) -> bool:
    """Beat ticks faster than most jobs; honour the per-workspace interval."""
    spec = get_spec(job_id)
    row = await table(SETTINGS_TABLE, workspace_id).get(job_id=job_id)
    job = _effective(spec, row)
    if not job["enabled"]:
        return False
    last = await table(RUNS_TABLE, workspace_id).select(job_id=job_id, order="started_at", desc=True, limit=1)
    if not last:
        return True
    now = now or datetime.now(timezone.utc)
    return datetime.fromisoformat(last[0]["started_at"]) + timedelta(seconds=job["interval_s"]) <= now


async def acquire_lease(workspace_id: str, job_id: str, holder: str, *, now: datetime | None = None) -> bool:
    """Atomic per-workspace/job execution lease.

    One row per (workspace, job); a conditional UPDATE on ``lease_until <= now``
    is a single-row compare-and-set in Postgres, and the unique index makes the
    first INSERT the only winner when no row exists yet. Anyone who does not
    get a row back must not run the job.
    """
    leases = table(LEASES_TABLE, workspace_id)
    now = now or datetime.now(timezone.utc)
    until = (now + timedelta(seconds=LEASE_S)).isoformat()
    updates = {"holder": holder, "lease_until": until, "updated_at": now.isoformat()}
    if await leases.update(updates, job_id=job_id, lease_until__lte=now.isoformat()):
        return True
    if await leases.get(job_id=job_id):
        return False
    try:
        await leases.insert({"id": new_id(), "job_id": job_id, **updates})
    except Exception as exc:  # unique violation: someone else inserted first
        logger.info("lease for %s/%s taken concurrently: %s", workspace_id, job_id, exc)
        return False
    return True


async def release_lease(workspace_id: str, job_id: str, holder: str) -> None:
    await table(LEASES_TABLE, workspace_id).update({"lease_until": now_iso(), "updated_at": now_iso()}, job_id=job_id, holder=holder)


async def run_job(workspace_id: str, job_id: str, *, trigger: Trigger = "manual", actor: str | None = None) -> Row:
    """Execute a job once and record the outcome. Never raises for job failures.

    Returns an unpersisted ``skipped`` row when another worker holds the lease.
    """
    spec = get_spec(job_id)
    holder = new_id()
    if not await acquire_lease(workspace_id, job_id, holder):
        return {"id": None, "job_id": job_id, "trigger": trigger, "actor": actor, "status": "skipped", "error": "already running", "summary": {}}
    try:
        if trigger == "schedule" and not await is_due(workspace_id, job_id):
            return {"id": None, "job_id": job_id, "trigger": trigger, "actor": actor, "status": "skipped", "error": "not due", "summary": {}}
        return await _run_locked(spec, workspace_id, job_id, trigger=trigger, actor=actor)
    finally:
        await release_lease(workspace_id, job_id, holder)


async def _run_locked(spec: JobSpec, workspace_id: str, job_id: str, *, trigger: Trigger, actor: str | None) -> Row:
    runs = table(RUNS_TABLE, workspace_id)
    started = time.monotonic()
    row: Row = {
        "id": new_id(),
        "job_id": job_id,
        "trigger": trigger,
        "actor": actor,
        "status": "running",
        "started_at": now_iso(),
        "finished_at": None,
        "duration_ms": None,
        "summary": {},
        "error": None,
    }
    await runs.insert(row)
    try:
        summary = await spec.runner(workspace_id)
        row.update(status="success", summary=summary)
    except Exception as exc:
        logger.exception("cowork job %s failed", job_id)
        row.update(status="failed", error=str(exc)[:500])
    row["finished_at"] = now_iso()
    row["duration_ms"] = int((time.monotonic() - started) * 1000)
    updated = await runs.update(
        {k: row[k] for k in ("status", "summary", "error", "finished_at", "duration_ms")},
        id=row["id"],
    )
    return updated[0] if updated else row


async def run_if_due(workspace_id: str, job_id: str) -> Row | None:
    if not await is_due(workspace_id, job_id):
        return None
    return await run_job(workspace_id, job_id, trigger="schedule")


async def list_runs(workspace_id: str, *, job_id: str | None = None, status: str | None = None, limit: int = 50) -> list[Row]:
    filters: dict[str, Any] = {}
    if job_id:
        filters["job_id"] = job_id
    if status:
        filters["status"] = status
    return await table(RUNS_TABLE, workspace_id).select(order="started_at", desc=True, limit=min(limit, 200), **filters)


async def run_stats(workspace_id: str, *, window_hours: int = 24) -> dict[str, Any]:
    since = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
    rows = await table(RUNS_TABLE, workspace_id).select(order="started_at", desc=True, limit=1000, started_at__gte=since)
    failed = [r for r in rows if r.get("status") == "failed"]
    durations = [int(r["duration_ms"]) for r in rows if r.get("duration_ms") is not None]
    return {
        "window_hours": window_hours,
        "runs": len(rows),
        "failed": len(failed),
        "success_rate": round(100 * (len(rows) - len(failed)) / len(rows), 1) if rows else None,
        "avg_duration_ms": int(sum(durations) / len(durations)) if durations else None,
        "last_failure": failed[0] if failed else None,
    }
