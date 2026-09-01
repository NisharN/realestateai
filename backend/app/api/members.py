"""Invite-only workspace membership management."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from app.auth import (
    AuthenticatedUser,
    RequestContext,
    WorkspaceRole,
    get_authenticated_user,
    get_request_context,
)
from app.config import get_settings
from app.database import DatabaseClient

router = APIRouter()


class MemberResponse(BaseModel):
    user_id: str
    workspace_id: str
    role: WorkspaceRole
    status: str
    broker_id: Optional[str] = None


class InvitationRequest(BaseModel):
    email: EmailStr
    role: WorkspaceRole
    broker_id: Optional[str] = None


class InvitationAcceptanceRequest(BaseModel):
    workspace_id: str


async def accept_pending_membership(
    client: Any, user: AuthenticatedUser, workspace_id: str
) -> dict[str, Any]:
    pending = (
        client.table("workspace_members")
        .select("user_id,workspace_id,role,status,broker_id")
        .eq("workspace_id", workspace_id)
        .eq("user_id", user.user_id)
        .eq("status", "invited")
        .maybe_single()
        .execute()
    )
    if not pending.data:
        raise HTTPException(
            status_code=404,
            detail={"code": "invitation_not_found", "message": "Pending invitation not found"},
        )
    accepted_at = datetime.now(timezone.utc).isoformat()
    updated = (
        client.table("workspace_members")
        .update({"status": "active", "updated_at": accepted_at})
        .eq("workspace_id", workspace_id)
        .eq("user_id", user.user_id)
        .eq("status", "invited")
        .execute()
    )
    if user.email:
        (
            client.table("workspace_invitations")
            .update({"accepted_at": accepted_at})
            .eq("workspace_id", workspace_id)
            .eq("email", user.email.lower())
            .execute()
        )
    data = updated.data or []
    return data[0] if isinstance(data, list) else data


@router.get("/", response_model=list[MemberResponse])
async def list_members(context: RequestContext = Depends(get_request_context)):
    context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
    client = DatabaseClient.get_client()
    if client is None:
        return []
    result = client.table("workspace_members").select(
        "user_id,workspace_id,role,status,broker_id"
    ).eq("workspace_id", context.workspace_id).order("created_at").execute()
    return result.data or []


@router.post("/invitations", response_model=MemberResponse, status_code=201)
async def invite_member(
    request: InvitationRequest,
    context: RequestContext = Depends(get_request_context),
):
    context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
    if request.role == WorkspaceRole.OWNER and context.role != WorkspaceRole.OWNER:
        raise HTTPException(status_code=403, detail={"code": "owner_required", "message": "Only an owner can invite another owner"})
    client = DatabaseClient.get_client()
    if client is None:
        raise HTTPException(status_code=503, detail={"code": "database_unavailable", "message": "Database unavailable"})
    invited = client.auth.admin.invite_user_by_email(
        request.email,
        options={
            "redirect_to": (
                f"{get_settings().SUPABASE_INVITE_REDIRECT_URL}?"
                f"{urlencode({'workspace_id': context.workspace_id})}"
            )
        },
    )
    user = getattr(invited, "user", None)
    if user is None:
        raise HTTPException(status_code=502, detail={"code": "invitation_failed", "message": "Supabase invitation failed"})
    payload = {
        "workspace_id": context.workspace_id,
        "user_id": str(user.id),
        "role": request.role.value,
        "status": "invited",
        "broker_id": request.broker_id,
    }
    result = client.table("workspace_members").upsert(
        payload, on_conflict="workspace_id,user_id"
    ).execute()
    raw_token = secrets.token_urlsafe(32)
    client.table("workspace_invitations").insert(
        {
            "workspace_id": context.workspace_id,
            "email": str(request.email).lower(),
            "role": request.role.value,
            "token_hash": hashlib.sha256(raw_token.encode()).hexdigest(),
            "invited_by": context.user_id,
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        }
    ).execute()
    return result.data[0]


@router.post("/invitations/accept", response_model=MemberResponse)
async def accept_invitation(
    request: InvitationAcceptanceRequest,
    user: AuthenticatedUser = Depends(get_authenticated_user),
):
    client = DatabaseClient.get_client()
    if client is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "database_unavailable", "message": "Database unavailable"},
        )
    return await accept_pending_membership(client, user, request.workspace_id)
