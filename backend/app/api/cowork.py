"""Co-work: integrations, scheduled jobs, task automations, run history and audit.

Aggregates the operational surface that used to be split across the admin
ingestion page, the automations page and the Celery beat schedule.
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import RequestContext, WorkspaceRole, get_request_context
from app.modules.cowork import automations, integrations, jobs
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
    return {
        "integrations": integ["counts"],
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
    feed.sort(key=lambda x: x["at"] or "", reverse=True)
    return feed[:limit]
