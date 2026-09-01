import pytest
from fastapi import HTTPException

from app.lifecycle import WorkspaceLifecycle, require_service_enabled


@pytest.mark.parametrize("service", ["ai", "ingestion", "whatsapp", "new_lead"])
def test_read_only_workspace_blocks_mutating_services(service):
    with pytest.raises(HTTPException) as denied:
        require_service_enabled(WorkspaceLifecycle.READ_ONLY, service)
    assert denied.value.status_code == 402
    assert denied.value.detail["code"] == "workspace_read_only"


def test_grace_workspace_remains_operational():
    require_service_enabled(WorkspaceLifecycle.GRACE, "ai")
