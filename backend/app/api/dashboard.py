"""Live workspace dashboard endpoints."""
from fastapi import APIRouter, Depends

from app.auth import RequestContext, WorkspaceRole, get_request_context
from app.database import get_lead_repository

router = APIRouter()


@router.get("/summary")
async def dashboard_summary(context: RequestContext = Depends(get_request_context)):
    repository = get_lead_repository(context.workspace_id)
    assigned_broker_id = context.broker_id if context.role == WorkspaceRole.AGENT else None
    return await repository.summary(assigned_broker_id)
