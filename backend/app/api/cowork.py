"""Co-work: integrations, scheduled jobs, task automations, run history and audit.

Aggregates the operational surface that used to be split across the admin
ingestion page, the automations page and the Celery beat schedule.
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.auth import RequestContext, WorkspaceRole, get_request_context
from app.modules.cowork import automations, connections, integrations, jobs, routines
from app.modules.ingestion.connectors.base import SignatureError
from app.modules.leads.stages import PIPELINE_STAGES
from app.modules.store import table

router = APIRouter()


def _admin(context: RequestContext) -> None:
    context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)


@router.get("/overview")
async def overview(context: RequestContext = Depends(get_request_context)) -> dict[str, Any]:
    _admin(context)
    ws = context.workspace_id
    integ = await integrations.list_integrations(ws)
    job_list = await jobs.list_jobs(ws)
    stats = await jobs.run_stats(ws)
    rules = await automations.list_rules(ws)
    open_tasks = await automations.list_tasks(ws, status="open", limit=500)
    review = await table("review_queue", ws).select(status="open", limit=500)
    conns = await connections.list_connections(ws)
    routine_list = await routines.list_routines(ws)
    return {
        "integrations": integ["counts"],
        "connections": {"total": len(conns), **connections.counts_by_health(conns)},
        "routines": {"total": len(routine_list), "enabled": sum(1 for r in routine_list if r.get("enabled")), "failing": sum(1 for r in routine_list if r.get("last_status") in ("failed", "partial"))},
        "jobs": {"total": len(job_list), "enabled": sum(1 for j in job_list if j["enabled"]), "failing": sum(1 for j in job_list if (j.get("last_run") or {}).get("status") == "failed")},
        "runs": stats,
        "automations": {"total": len(rules), "enabled": sum(1 for r in rules if r.get("enabled")), "fired_total": sum(int(r.get("run_count") or 0) for r in rules)},
        "tasks_open": len(open_tasks),
        "review_open": len(review),
    }


@router.get("/integrations")
async def list_integrations(context: RequestContext = Depends(get_request_context)) -> dict[str, Any]:
    _admin(context)
    return await integrations.list_integrations(context.workspace_id)


@router.get("/jobs")
async def list_jobs(context: RequestContext = Depends(get_request_context)) -> list[dict[str, Any]]:
    _admin(context)
    return await jobs.list_jobs(context.workspace_id)


class JobPatch(BaseModel):
    enabled: bool | None = None
    interval_s: int | None = Field(None, ge=30, le=7 * 86_400)


@router.patch("/jobs/{job_id}")
async def patch_job(job_id: str, body: JobPatch, context: RequestContext = Depends(get_request_context)) -> dict[str, Any]:
    _admin(context)
    try:
        return await jobs.update_job(context.workspace_id, job_id, enabled=body.enabled, interval_s=body.interval_s)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown_job")


@router.post("/jobs/{job_id}/run")
async def run_job_now(job_id: str, context: RequestContext = Depends(get_request_context)) -> dict[str, Any]:
    _admin(context)
    try:
        return await jobs.run_job(context.workspace_id, job_id, trigger="manual", actor=context.user_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown_job")


@router.get("/runs")
async def list_runs(
    job_id: str | None = None,
    status: Literal["running", "success", "failed"] | None = None,
    limit: int = Query(50, ge=1, le=200),
    context: RequestContext = Depends(get_request_context),
) -> list[dict[str, Any]]:
    _admin(context)
    return await jobs.list_runs(context.workspace_id, job_id=job_id, status=status, limit=limit)


@router.get("/automations/catalog")
async def automation_catalog(context: RequestContext = Depends(get_request_context)) -> dict[str, Any]:
    _admin(context)
    return {
        "triggers": automations.TRIGGERS,
        "actions": automations.ACTIONS,
        "condition_fields": list(automations.CONDITION_FIELDS),
        "operators": ["eq", "ne", "gte", "lte", "in", "contains", "exists"],
        "jobs": [{"id": j.id, "label": j.label} for j in jobs.JOBS if j.id not in automations.FORBIDDEN_JOBS],
        "stages": list(PIPELINE_STAGES),
    }


@router.get("/automations")
async def list_automations(context: RequestContext = Depends(get_request_context)) -> list[dict[str, Any]]:
    _admin(context)
    return await automations.list_rules(context.workspace_id)


@router.post("/automations", status_code=201)
async def create_automation(body: automations.AutomationIn, context: RequestContext = Depends(get_request_context)) -> dict[str, Any]:
    _admin(context)
    return await automations.create_rule(context.workspace_id, body, actor=context.user_id)


@router.patch("/automations/{rule_id}")
async def patch_automation(rule_id: str, body: automations.AutomationPatch, context: RequestContext = Depends(get_request_context)) -> dict[str, Any]:
    _admin(context)
    try:
        row = await automations.patch_rule(context.workspace_id, rule_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not row:
        raise HTTPException(status_code=404, detail="not_found")
    return row


@router.delete("/automations/{rule_id}")
async def delete_automation(rule_id: str, context: RequestContext = Depends(get_request_context)) -> dict[str, bool]:
    _admin(context)
    if not await automations.delete_rule(context.workspace_id, rule_id):
        raise HTTPException(status_code=404, detail="not_found")
    return {"deleted": True}


@router.post("/automations/{rule_id}/test")
async def test_automation(rule_id: str, context: RequestContext = Depends(get_request_context)) -> dict[str, Any]:
    _admin(context)
    rule = await table(automations.RULES_TABLE, context.workspace_id).get(id=rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="not_found")
    return await automations.test_rule(context.workspace_id, rule)


@router.post("/automations/run")
async def run_automations_now(context: RequestContext = Depends(get_request_context)) -> dict[str, Any]:
    _admin(context)
    return await jobs.run_job(context.workspace_id, "run_automations", trigger="manual", actor=context.user_id)


@router.get("/automations/runs")
async def list_automation_runs(
    automation_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    context: RequestContext = Depends(get_request_context),
) -> list[dict[str, Any]]:
    _admin(context)
    return await automations.list_runs(context.workspace_id, automation_id=automation_id, limit=limit)


@router.get("/tasks")
async def list_tasks(
    status: Literal["open", "done", "dismissed"] | None = None,
    limit: int = Query(100, ge=1, le=500),
    context: RequestContext = Depends(get_request_context),
) -> list[dict[str, Any]]:
    _admin(context)
    return await automations.list_tasks(context.workspace_id, status=status, limit=limit)


class TaskPatch(BaseModel):
    status: Literal["open", "done", "dismissed"]


@router.patch("/tasks/{task_id}")
async def patch_task(task_id: str, body: TaskPatch, context: RequestContext = Depends(get_request_context)) -> dict[str, Any]:
    _admin(context)
    row = await automations.update_task(context.workspace_id, task_id, status=body.status)
    if not row:
        raise HTTPException(status_code=404, detail="not_found")
    return row


@router.get("/audit")
async def audit(
    limit: int = Query(100, ge=1, le=300),
    context: RequestContext = Depends(get_request_context),
) -> list[dict[str, Any]]:
    """Unified, newest-first feed of job runs and automation firings."""
    _admin(context)
    ws = context.workspace_id
    job_runs = await jobs.list_runs(ws, limit=limit)
    auto_runs = await automations.list_runs(ws, limit=limit)
    feed: list[dict[str, Any]] = []
    for r in job_runs:
        feed.append({"id": r["id"], "at": r.get("started_at"), "kind": "job", "subject": jobs.JOB_INDEX[r["job_id"]].label if r["job_id"] in jobs.JOB_INDEX else r["job_id"], "status": r.get("status"), "trigger": r.get("trigger"), "actor": r.get("actor"), "detail": r.get("error") or r.get("summary") or {}})
    for r in auto_runs:
        feed.append({"id": r["id"], "at": r.get("created_at"), "kind": "automation", "subject": r.get("automation_name") or r.get("automation_id"), "status": r.get("status"), "trigger": r.get("event_type"), "actor": r.get("lead_id"), "detail": r.get("error") or r.get("result") or {}})
    for r in await routines.list_runs(ws, limit=limit):
        feed.append({"id": r["id"], "at": r.get("started_at"), "kind": "routine", "subject": r.get("routine_name") or r.get("routine_id"), "status": r.get("status"), "trigger": r.get("trigger"), "actor": r.get("actor"), "detail": r.get("error") or r.get("summary") or {}})
    feed.sort(key=lambda x: x["at"] or "", reverse=True)
    return feed[:limit]


# --------------------------------------------------------------------------- connections


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": "invalid", "message": str(exc)})


@router.get("/connections/catalog")
async def connections_catalog(context: RequestContext = Depends(get_request_context)) -> list[dict[str, Any]]:
    _admin(context)
    return connections.catalog()


@router.get("/connections")
async def list_connections(context: RequestContext = Depends(get_request_context)) -> dict[str, Any]:
    _admin(context)
    rows = await connections.list_connections(context.workspace_id)
    return {"connections": rows, "counts": connections.counts_by_health(rows)}


@router.post("/connections", status_code=201)
async def create_connection(body: connections.ConnectionIn, context: RequestContext = Depends(get_request_context)) -> dict[str, Any]:
    _admin(context)
    try:
        return await connections.create_connection(context.workspace_id, body, actor=context.user_id)
    except ValueError as exc:
        raise _bad(exc)


@router.patch("/connections/{connection_id}")
async def patch_connection(connection_id: str, body: connections.ConnectionPatch, context: RequestContext = Depends(get_request_context)) -> dict[str, Any]:
    _admin(context)
    try:
        row = await connections.patch_connection(context.workspace_id, connection_id, body)
    except ValueError as exc:
        raise _bad(exc)
    if not row:
        raise HTTPException(status_code=404, detail="not_found")
    return row


@router.delete("/connections/{connection_id}")
async def delete_connection(connection_id: str, context: RequestContext = Depends(get_request_context)) -> dict[str, bool]:
    _admin(context)
    return {"deleted": await connections.delete_connection(context.workspace_id, connection_id)}


@router.post("/connections/{connection_id}/test")
async def test_connection(connection_id: str, context: RequestContext = Depends(get_request_context)) -> dict[str, Any]:
    _admin(context)
    try:
        return await connections.test_connection(context.workspace_id, connection_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="not_found")


@router.post("/connections/{connection_id}/webhook/test")
async def test_connection_webhook(connection_id: str, context: RequestContext = Depends(get_request_context)) -> dict[str, Any]:
    _admin(context)
    try:
        return await connections.test_webhook(context.workspace_id, connection_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="not_found")


@router.get("/connections/{connection_id}/webhook")
async def reveal_connection_webhook(connection_id: str, context: RequestContext = Depends(get_request_context)) -> dict[str, Any]:
    """Owner/admin-only: returns the inbound URL and signing secret to paste into the provider."""
    _admin(context)
    out = await connections.reveal_webhook(context.workspace_id, connection_id)
    if not out:
        raise HTTPException(status_code=404, detail="not_found")
    return out


@router.post("/webhooks/{connection_id}")
async def inbound_connection_webhook(
    connection_id: str,
    request: Request,
    background: BackgroundTasks,
    workspace_id: str = Query(..., description="Workspace that owns the connection"),
) -> dict[str, Any]:
    """Unauthenticated inbound webhook; the per-connection HMAC secret is the credential."""
    from app.modules.ingestion.pipeline.processor import process_many

    body = await request.body()
    try:
        out = await connections.handle_inbound(workspace_id, connection_id, dict(request.headers), body)
    except LookupError:
        raise HTTPException(status_code=404, detail={"code": "connection_not_found", "message": "Connection not found"})
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail={"code": "connection_inactive", "message": str(exc)})
    except SignatureError:
        raise HTTPException(status_code=401, detail={"code": "invalid_signature", "message": "Invalid signature"})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_payload", "message": str(exc)})
    raw_ids = out.pop("raw_ids", [])
    if raw_ids:
        background.add_task(process_many, raw_ids, workspace_id=workspace_id)
    return out


# --------------------------------------------------------------------------- routines


@router.get("/routines/catalog")
async def routines_catalog(context: RequestContext = Depends(get_request_context)) -> dict[str, Any]:
    _admin(context)
    return routines.step_catalog()


@router.get("/routines")
async def list_routines(context: RequestContext = Depends(get_request_context)) -> list[dict[str, Any]]:
    _admin(context)
    return await routines.list_routines(context.workspace_id)


@router.post("/routines", status_code=201)
async def create_routine(body: routines.RoutineIn, context: RequestContext = Depends(get_request_context)) -> dict[str, Any]:
    _admin(context)
    try:
        return await routines.create_routine(context.workspace_id, body, actor=context.user_id)
    except ValueError as exc:
        raise _bad(exc)


class TemplateIn(BaseModel):
    template_id: str = Field(..., min_length=1, max_length=60)


@router.post("/routines/from-template", status_code=201)
async def routine_from_template(body: TemplateIn, context: RequestContext = Depends(get_request_context)) -> dict[str, Any]:
    _admin(context)
    try:
        return await routines.instantiate_template(context.workspace_id, body.template_id, actor=context.user_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="template_not_found")
    except ValueError as exc:
        raise _bad(exc)


@router.get("/routines/runs")
async def list_routine_runs(
    routine_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    context: RequestContext = Depends(get_request_context),
) -> list[dict[str, Any]]:
    _admin(context)
    return await routines.list_runs(context.workspace_id, routine_id=routine_id, limit=limit)


@router.patch("/routines/{routine_id}")
async def patch_routine(routine_id: str, body: routines.RoutinePatch, context: RequestContext = Depends(get_request_context)) -> dict[str, Any]:
    _admin(context)
    try:
        row = await routines.patch_routine(context.workspace_id, routine_id, body)
    except ValueError as exc:
        raise _bad(exc)
    if not row:
        raise HTTPException(status_code=404, detail="not_found")
    return row


@router.delete("/routines/{routine_id}")
async def delete_routine(routine_id: str, context: RequestContext = Depends(get_request_context)) -> dict[str, bool]:
    _admin(context)
    return {"deleted": await routines.delete_routine(context.workspace_id, routine_id)}


@router.post("/routines/{routine_id}/run")
async def run_routine_now(routine_id: str, context: RequestContext = Depends(get_request_context)) -> dict[str, Any]:
    _admin(context)
    try:
        return await routines.run_routine(context.workspace_id, routine_id, trigger="manual", actor=context.user_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="not_found")
