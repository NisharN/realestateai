"""Authenticated session endpoints."""
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import RequestContext, WorkspaceRole, get_request_context

router = APIRouter()


class SessionResponse(BaseModel):
    user_id: str
    workspace_id: str
    role: WorkspaceRole
    broker_id: Optional[str] = None


@router.get("/me", response_model=SessionResponse)
async def get_session(
    context: RequestContext = Depends(get_request_context),
) -> SessionResponse:
    return SessionResponse(
        user_id=context.user_id,
        workspace_id=context.workspace_id,
        role=context.role,
        broker_id=context.broker_id,
    )
