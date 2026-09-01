from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import RequestContext, WorkspaceRole, get_request_context
from app.database import DatabaseClient

router = APIRouter()


class ScheduleRequest(BaseModel):
    source: str
    cron_expression: str
    configuration: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


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
    payload = {**request.model_dump(), "workspace_id": context.workspace_id, "failure_count": 0, "created_at": datetime.now(timezone.utc).isoformat()}
    return _client().table("ingestion_schedules").insert(payload).execute().data[0]


@router.get("/runs")
async def list_runs(limit: int = 50, context: RequestContext = Depends(get_request_context)):
    context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
    return _client().table("job_runs").select("*").eq("workspace_id", context.workspace_id).order("created_at", desc=True).limit(min(limit, 100)).execute().data or []
