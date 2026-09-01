import pytest
from fastapi.testclient import TestClient

from app.auth import (
    DemoAuthBackend,
    RequestContext,
    SupabaseAuthBackend,
    WorkspaceRole,
    get_auth_backend,
    get_request_context,
)
from app.config import get_settings
from app.main import app

client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def real_auth():
    """Force real authentication.

    Demo deployments authenticate everyone as a local demo owner so the
    product can be walked through with no accounts (DEMO_AUTH). These tests
    are about the *real* path, so they override the backend explicitly.
    """
    app.dependency_overrides[get_auth_backend] = lambda: SupabaseAuthBackend()
    try:
        yield
    finally:
        app.dependency_overrides.clear()


def test_lead_list_requires_authentication(real_auth):
    response = client.get("/api/v1/leads/")

    assert response.status_code == 401
    assert response.json() == {
        "detail": {"code": "authentication_required", "message": "Authentication required"}
    }


def test_workspace_list_requires_authentication(real_auth):
    response = client.get("/api/v1/workspace/")

    assert response.status_code == 401


def test_demo_auth_is_refused_in_production():
    """The demo bypass must never be reachable in a real deployment."""
    settings = get_settings()
    original_env, original_flag = settings.APP_ENV, settings.DEMO_AUTH
    try:
        settings.APP_ENV = "production"
        settings.DEMO_AUTH = True
        assert settings.demo_auth_enabled is False
        assert isinstance(get_auth_backend(), SupabaseAuthBackend)

        settings.APP_ENV = "development"
        assert settings.demo_auth_enabled is True
        assert isinstance(get_auth_backend(), DemoAuthBackend)
    finally:
        settings.APP_ENV, settings.DEMO_AUTH = original_env, original_flag


def test_auth_me_returns_active_membership_context():
    async def authenticated_context():
        return RequestContext(
            user_id="user-1",
            workspace_id="workspace-a",
            role=WorkspaceRole.ADMIN,
            broker_id=None,
        )

    app.dependency_overrides[get_request_context] = authenticated_context
    try:
        response = client.get("/api/v1/auth/me")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "user_id": "user-1",
        "workspace_id": "workspace-a",
        "role": "admin",
        "broker_id": None,
    }
