import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.auth import (
    AuthenticatedUser,
    RequestContext,
    WorkspaceRole,
    can_manage_membership,
    get_authenticated_user,
    get_request_context,
)


def test_owner_can_access_any_lead_in_their_workspace():
    context = RequestContext(
        user_id="user-owner",
        workspace_id="workspace-a",
        role=WorkspaceRole.OWNER,
    )

    assert context.can_access_lead(
        {"workspace_id": "workspace-a", "assigned_broker": "broker-2"}
    )


def test_agent_can_only_access_leads_assigned_to_their_broker_profile():
    context = RequestContext(
        user_id="user-agent",
        workspace_id="workspace-a",
        role=WorkspaceRole.AGENT,
        broker_id="broker-1",
    )

    assert context.can_access_lead(
        {"workspace_id": "workspace-a", "assigned_broker": "broker-1"}
    )
    assert not context.can_access_lead(
        {"workspace_id": "workspace-a", "assigned_broker": "broker-2"}
    )


@pytest.mark.parametrize("role", list(WorkspaceRole))
def test_no_role_can_access_a_lead_from_another_workspace(role):
    context = RequestContext(
        user_id="user-1",
        workspace_id="workspace-a",
        role=role,
        broker_id="broker-1",
    )

    assert not context.can_access_lead(
        {"workspace_id": "workspace-b", "assigned_broker": "broker-1"}
    )


@pytest.mark.asyncio
async def test_request_context_is_resolved_from_verified_membership():
    """Single-tenant: the workspace comes from deployment config, not a header.

    ``authenticate`` therefore takes only the token — there is no
    ``X-Workspace-ID`` to pass through, because a deployment serves exactly
    one brokerage.
    """
    expected = RequestContext(
        user_id="user-1",
        workspace_id="workspace-a",
        role=WorkspaceRole.ADMIN,
    )

    class FakeAuthBackend:
        async def authenticate(self, token):
            assert token == "valid-token"
            return expected

    actual = await get_request_context(
        credentials=HTTPAuthorizationCredentials(
            scheme="Bearer", credentials="valid-token"
        ),
        backend=FakeAuthBackend(),
    )

    assert actual == expected


def test_agent_cannot_perform_admin_operation():
    context = RequestContext(
        user_id="user-agent",
        workspace_id="workspace-a",
        role=WorkspaceRole.AGENT,
        broker_id="broker-1",
    )

    with pytest.raises(HTTPException) as denied:
        context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)

    assert denied.value.status_code == 403
    assert denied.value.detail["code"] == "insufficient_role"


def test_admin_cannot_promote_any_member_to_owner():
    assert not can_manage_membership(
        actor_role=WorkspaceRole.ADMIN,
        current_role=WorkspaceRole.AGENT,
        requested_role=WorkspaceRole.OWNER,
    )


def test_owner_can_promote_an_agent_to_admin():
    assert can_manage_membership(
        actor_role=WorkspaceRole.OWNER,
        current_role=WorkspaceRole.AGENT,
        requested_role=WorkspaceRole.ADMIN,
    )


def test_admin_cannot_modify_an_existing_owner():
    assert not can_manage_membership(
        actor_role=WorkspaceRole.ADMIN,
        current_role=WorkspaceRole.OWNER,
        requested_role=WorkspaceRole.ADMIN,
    )


@pytest.mark.asyncio
async def test_authenticated_user_can_be_resolved_before_membership_is_active():
    expected = AuthenticatedUser(user_id="invited-user", email="invite@example.com")

    class FakeIdentityBackend:
        async def get_user(self, token):
            assert token == "invite-token"
            return expected

    actual = await get_authenticated_user(
        credentials=HTTPAuthorizationCredentials(
            scheme="Bearer", credentials="invite-token"
        ),
        backend=FakeIdentityBackend(),
    )

    assert actual == expected
