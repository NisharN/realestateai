from enum import Enum

from fastapi import HTTPException


class WorkspaceLifecycle(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    GRACE = "grace"
    READ_ONLY = "read_only"
    SUSPENDED = "suspended"


def require_service_enabled(lifecycle: WorkspaceLifecycle, service: str) -> None:
    if lifecycle in {WorkspaceLifecycle.READ_ONLY, WorkspaceLifecycle.SUSPENDED}:
        raise HTTPException(
            status_code=402,
            detail={
                "code": "workspace_read_only",
                "message": f"Workspace cannot use {service} while billing is inactive",
            },
        )
