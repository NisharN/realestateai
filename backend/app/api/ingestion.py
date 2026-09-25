from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import RequestContext, WorkspaceRole, get_request_context
from app.database import DatabaseClient

router = APIRouter()


class ScheduleRequest(BaseModel):
    source: str
    cron_expression: str
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    interval_minutes: int = Field(60, ge=1, le=24 * 60)


def schedule_insert_payload(request: ScheduleRequest, workspace_id: str, now: datetime) -> dict[str, Any]:
    """Row for ``ingestion_schedules`` matching the migration's columns exactly."""
    config = {**request.config, "interval_minutes": request.interval_minutes}
    return {
        "workspace_id": workspace_id,
        "source": request.source,
        "cron_expression": request.cron_expression,
        "config": config,
        "enabled": request.enabled,
        "consecutive_failures": 0,
        "next_run_at": now.isoformat(),
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }


def _client():
    client = DatabaseClient.get_client()
    if client is None:
        raise HTTPException(503, detail={"code": "database_unavailable", "message": "Database unavailable"})
    return client


@router.get("/schedules")
async def list_schedules(context: RequestContext = Depends(get_request_context)):
    context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
    return _client().table("ingestion_schedules").select("*").eq("workspace_id", context.workspace_id).order("created_at").execute().data or []


@router.post("/schedules", status_code=201)
async def create_schedule(request: ScheduleRequest, context: RequestContext = Depends(get_request_context)):
    context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
    payload = schedule_insert_payload(request, context.workspace_id, datetime.now(timezone.utc))
    return _client().table("ingestion_schedules").insert(payload).execute().data[0]


@router.get("/runs")
async def list_runs(limit: int = 50, context: RequestContext = Depends(get_request_context)):
    context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
    return _client().table("job_runs").select("*").eq("workspace_id", context.workspace_id).order("created_at", desc=True).limit(min(limit, 100)).execute().data or []
