"""Authentication and role authorization primitives.

Single-tenant model (see PILOT.md): one deployment serves exactly one
brokerage, whose id comes from ``settings.WORKSPACE_ID`` rather than from a
request header. Roles (owner/admin/agent) still matter and are enforced here
— what's gone is cross-workspace switching, multi-membership resolution, and
the ``X-Workspace-ID`` header, none of which mean anything when there is only
ever one workspace per deployment.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional, Protocol

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings


class WorkspaceRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    AGENT = "agent"


def can_manage_membership(
    actor_role: WorkspaceRole,
    current_role: WorkspaceRole,
    requested_role: WorkspaceRole,
) -> bool:
    """Enforce that only owners can create or modify owner memberships."""
    if actor_role == WorkspaceRole.OWNER:
        return True
    if actor_role != WorkspaceRole.ADMIN:
        return False
    return (
        current_role != WorkspaceRole.OWNER
        and requested_role != WorkspaceRole.OWNER
    )


@dataclass(frozen=True)
class RequestContext:
    """Authenticated identity and its active workspace membership."""

    user_id: str
    workspace_id: str
    role: WorkspaceRole
    broker_id: Optional[str] = None

    def can_access_lead(self, lead: Mapping[str, Any]) -> bool:
        if lead.get("workspace_id") != self.workspace_id:
            return False
        if self.role in (WorkspaceRole.OWNER, WorkspaceRole.ADMIN):
            return True
        return bool(self.broker_id) and lead.get("assigned_broker") == self.broker_id

    def require_roles(self, *allowed: WorkspaceRole) -> None:
        if self.role not in allowed:
            raise HTTPException(
                status_code=403,
                detail={"code": "insufficient_role", "message": "Insufficient workspace role"},
            )


@dataclass(frozen=True)
class AuthenticatedUser:
    """Verified Supabase identity that may not have an active membership yet."""

    user_id: str
    email: Optional[str] = None


_bearer = HTTPBearer(auto_error=False)


class AuthBackend(Protocol):
    async def authenticate(self, token: str) -> RequestContext: ...


class IdentityBackend(Protocol):
    async def get_user(self, token: str) -> AuthenticatedUser: ...


class SupabaseIdentityBackend:
    async def get_user(self, token: str) -> AuthenticatedUser:
        from app.database import DatabaseClient

        client = DatabaseClient.get_client()
        if client is None:
            raise HTTPException(
                status_code=503,
                detail={"code": "auth_unavailable", "message": "Authentication unavailable"},
            )
        try:
            response = client.auth.get_user(token)
            user = getattr(response, "user", None)
            if user is None:
                raise ValueError("Token has no user")
            return AuthenticatedUser(
                user_id=str(user.id), email=getattr(user, "email", None)
            )
        except Exception:
            raise HTTPException(
                status_code=401,
                detail={"code": "invalid_token", "message": "Invalid access token"},
                headers={"WWW-Authenticate": "Bearer"},
            ) from None


class SupabaseAuthBackend:
    """Validate a Supabase token and resolve this deployment's membership.

    Single-tenant: the workspace is always ``settings.WORKSPACE_ID``. We look
    the caller up in ``workspace_members`` purely to establish their *role*
    (and optional broker linkage) — not to decide which workspace they land
    in, because there is only one.
    """

    async def authenticate(self, token: str) -> RequestContext:
        from app.database import DatabaseClient

        workspace_id = get_settings().WORKSPACE_ID
        client = DatabaseClient.get_client()
        if client is None:
            raise HTTPException(
                status_code=503,
                detail={"code": "auth_unavailable", "message": "Authentication unavailable"},
            )
        try:
            user_response = client.auth.get_user(token)
            user = getattr(user_response, "user", None)
            if user is None:
                raise ValueError("Token has no user")
            result = (
                client.table("workspace_members")
                .select("workspace_id,role,broker_id,status")
                .eq("user_id", user.id)
                .eq("workspace_id", workspace_id)
                .eq("status", "active")
                .execute()
            )
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                status_code=401,
                detail={"code": "invalid_token", "message": "Invalid access token"},
                headers={"WWW-Authenticate": "Bearer"},
            ) from None

        memberships = result.data or []
        if not memberships:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "membership_required",
                    "message": "Active membership required for this workspace",
                },
            )
        membership = memberships[0]
        return RequestContext(
            user_id=str(user.id),
            workspace_id=workspace_id,
            role=WorkspaceRole(membership["role"]),
            broker_id=membership.get("broker_id"),
        )


class DemoAuthBackend:
    """Authenticate everyone as a local demo user.

    Exists so the product can be demonstrated end to end with no Supabase
    project, no accounts, and no API keys — which is the point of mock data
    mode. ``demo_auth_enabled`` refuses to activate under APP_ENV=production,
    so a real customer deployment cannot silently run without authentication.
    """

    async def authenticate(self, token: str) -> RequestContext:
        settings = get_settings()
        try:
            role = WorkspaceRole(settings.DEMO_ROLE.lower())
        except ValueError:
            role = WorkspaceRole.OWNER
        return RequestContext(
            user_id="demo-user",
            workspace_id=settings.WORKSPACE_ID,
            role=role,
            broker_id="broker-1" if role == WorkspaceRole.AGENT else None,
        )


def get_auth_backend() -> AuthBackend:
    if get_settings().demo_auth_enabled:
        return DemoAuthBackend()
    return SupabaseAuthBackend()


def get_identity_backend() -> IdentityBackend:
    return SupabaseIdentityBackend()


async def get_authenticated_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    backend: IdentityBackend = Depends(get_identity_backend),
) -> AuthenticatedUser:
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "authentication_required", "message": "Authentication required"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await backend.get_user(credentials.credentials)


async def get_request_context(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    backend: AuthBackend = Depends(get_auth_backend),
) -> RequestContext:
    """Resolve a bearer token to this deployment's role context."""
    if isinstance(backend, DemoAuthBackend):
        return await backend.authenticate("")
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "authentication_required",
                "message": "Authentication required",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await backend.authenticate(credentials.credentials)
