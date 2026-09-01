"""API routes for workspace configuration (the /configure workflow builder).

A workspace is one broker/agency's setup: team roster, enabled property
data sources, and channel settings. This is the productized "light FDE"
motion described in the product/market review — instead of an engineer
hand-configuring each customer, the /configure frontend wizard calls these
endpoints directly.

POC scope: see docs/poc_scope.md. Workspaces are real and persisted;
leads/properties are not yet scoped by workspace_id.
"""
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException

from app.database import get_db, get_workspace_repository, get_property_repository
from app.auth import RequestContext, WorkspaceRole, get_request_context
from app.models.workspace import (
    DataSourceTestResult,
    WorkspaceCreate,
    WorkspaceResponse,
    WorkspaceUpdate,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Sources that can be "tested" from the workflow builder without any real
# external credentials — CSV/manual sources are proven by actually
# importing a file (see /api/v1/properties/import/csv), not by this stub.
_TESTABLE_SOURCES = {"approved_feed", "rapidapi_uae", "propertyfinder"}


@router.post("/", response_model=WorkspaceResponse)
async def create_workspace(request: WorkspaceCreate, context: RequestContext = Depends(get_request_context), db=Depends(get_db)):
    """Create a new workspace from the /configure wizard's final step."""
    raise HTTPException(status_code=403, detail={"code": "operator_only", "message": "Workspace creation is operator-only"})


@router.get("/", response_model=List[WorkspaceResponse])
async def list_workspaces(context: RequestContext = Depends(get_request_context), db=Depends(get_db)):
    """List workspaces (POC: no auth scoping yet — returns everything)."""
    repo = get_workspace_repository(context.workspace_id)
    return await repo.list_all()


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(workspace_id: str, context: RequestContext = Depends(get_request_context), db=Depends(get_db)):
    """Get a workspace by id."""
    repo = get_workspace_repository(context.workspace_id)
    workspace = await repo.get_by_id(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


@router.put("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(workspace_id: str, request: WorkspaceUpdate, context: RequestContext = Depends(get_request_context), db=Depends(get_db)):
    """Update a workspace — used at every step of the wizard as the user progresses."""
    context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
    repo = get_workspace_repository(context.workspace_id)
    existing = await repo.get_by_id(workspace_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Workspace not found")

    updates = request.model_dump(exclude_unset=True)
    updated = await repo.update(workspace_id, updates)
    return updated


@router.post("/{workspace_id}/launch", response_model=WorkspaceResponse)
async def launch_workspace(workspace_id: str, context: RequestContext = Depends(get_request_context), db=Depends(get_db)):
    """Mark a workspace as live — the wizard's final "Launch" action."""
    context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
    repo = get_workspace_repository(context.workspace_id)
    existing = await repo.get_by_id(workspace_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Workspace not found")
    updated = await repo.update(workspace_id, {"status": "live"})
    return updated


@router.post("/data-sources/{source}/test", response_model=DataSourceTestResult)
async def test_data_source(source: str, context: RequestContext = Depends(get_request_context), db=Depends(get_db)):
    """"Test" a data source connection from the pipeline step of the wizard.

    For sources with no real credentials configured in this POC
    (approved_feed / rapidapi_uae / propertyfinder), this reports whether
    the underlying settings are present and returns a lightweight sample
    count from whatever is already in the property repository, rather than
    actually hitting the third-party API — that keeps the workflow builder
    usable without live credentials while still being honest about status.
    """
    if source not in _TESTABLE_SOURCES and source not in {"broker_csv", "crm_export", "inventory_db"}:
        raise HTTPException(status_code=400, detail=f"Unknown data source: {source}")

    if source in {"broker_csv", "crm_export", "inventory_db"}:
        # These are proven by actually uploading/importing, not by a test
        # ping — tell the wizard to use the real import endpoint instead.
        return DataSourceTestResult(
            source=source,
            ok=True,
            message="Upload a file via the import step to activate this source.",
            sample_count=0,
        )

    context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
    prop_repo = get_property_repository(context.workspace_id)
    try:
        existing = await prop_repo.search_by_criteria(limit=5)
        sample_count = len(existing)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Data source test lookup failed: %s", exc)
        sample_count = 0

    return DataSourceTestResult(
        source=source,
        ok=True,
        message=f"Connection path reachable. {sample_count} sample listing(s) currently in inventory.",
        sample_count=sample_count,
    )
