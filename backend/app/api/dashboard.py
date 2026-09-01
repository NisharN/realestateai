"""Live workspace dashboard endpoints."""
from fastapi import APIRouter, Depends

from app.auth import RequestContext, WorkspaceRole, get_request_context
from app.database import get_lead_repository
from app.services.dashboard import summarize_leads

router = APIRouter()


@router.get("/summary")
async def dashboard_summary(context: RequestContext = Depends(get_request_context)):
    repository = get_lead_repository(context.workspace_id)
    assigned_broker_id = context.broker_id if context.role == WorkspaceRole.AGENT else None
    leads = []
    for status in ("new", "contacted", "qualified", "nurture", "closed", "lost"):
        leads.extend(await repository.list_by_status(status, 1000, 0, assigned_broker_id))
    return summarize_leads(leads)
