"""API routes for property search and licensed-source ingestion.

Portal scraping is out of scope (BRD §1.4): the only inventory paths are the
brokerage's own uploads (CSV / JSON / inventory), an approved partner feed
and a licensed RapidAPI provider.
"""
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from app.auth import RequestContext, WorkspaceRole, get_request_context
from app.database import get_db, get_property_repository
from app.models.property import PropertyImportResponse, PropertyJsonImportRequest
from app.scrapers import (
    rapidapi_developer_search_by_name,
    scrape_approved_feed,
    scrape_rapidapi_properties,
)
from app.services.property_ingestion import PropertyIngestionService

logger = logging.getLogger(__name__)
router = APIRouter()


class InventoryImportRequest(BaseModel):
    """Import properties from internal inventory objects."""
    records: list[dict[str, Any]]
    dedupe: bool = True


class RapidApiIngestRequest(BaseModel):
    """RapidAPI source ingestion request."""
    endpoint: str
    params: dict[str, Any] = {}
    dedupe: bool = True


class RapidApiDeveloperSearchRequest(BaseModel):
    """Developer lookup request for the UAE real-estate RapidAPI source."""
    query: str
    page: int = 1
    langs: str = "en"


def _ingestion_service(workspace_id: str) -> PropertyIngestionService:
    return PropertyIngestionService(get_property_repository(workspace_id))


def _import_error(exc: Exception) -> HTTPException:
    logger.error("Property import failed: %s", exc, exc_info=True)
    return HTTPException(
        status_code=500,
        detail={"code": "import_failed", "message": "Property import failed"},
    )


@router.get("/search")
async def search_properties(
    area: Optional[str] = None,
    property_type: Optional[str] = None,
    min_price: Optional[float] = Query(None, ge=0),
    max_price: Optional[float] = Query(None, ge=0),
    bedrooms: Optional[int] = Query(None, ge=0),
    limit: int = Query(10, ge=1, le=50),
    context: RequestContext = Depends(get_request_context),
    db=Depends(get_db),
):
    """Search properties from the workspace's own inventory."""
    prop_repo = get_property_repository(context.workspace_id)
    return await prop_repo.search_by_criteria(
        area=area,
        property_type=property_type,
        min_price=min_price,
        max_price=max_price,
        bedrooms=bedrooms,
        limit=limit,
    )


@router.post("/import/csv", response_model=PropertyImportResponse)
async def import_properties_csv(
    source: str = Query(..., description="broker_csv, crm_export, inventory_db"),
    dedupe: bool = Query(True),
    file: UploadFile = File(...),
    context: RequestContext = Depends(get_request_context),
):
    """Import properties from a CSV upload."""
    context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
    try:
        payload = await file.read()
        result = await _ingestion_service(context.workspace_id).import_csv_bytes(
            source=source, data=payload, dedupe=dedupe
        )
        return PropertyImportResponse(**result)
    except Exception as exc:
        raise _import_error(exc)


@router.post("/import/json", response_model=PropertyImportResponse)
async def import_properties_json(
    request: PropertyJsonImportRequest,
    context: RequestContext = Depends(get_request_context),
):
    """Import properties from JSON records such as CRM exports or partner feeds."""
    context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
    try:
        result = await _ingestion_service(context.workspace_id).import_records(
            source=request.source, records=request.records, dedupe=request.dedupe
        )
        return PropertyImportResponse(**result)
    except Exception as exc:
        raise _import_error(exc)


@router.post("/import/inventory", response_model=PropertyImportResponse)
async def import_inventory_records(
    request: InventoryImportRequest,
    context: RequestContext = Depends(get_request_context),
):
    """Import first-party inventory from your own database or export."""
    context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
    try:
        result = await _ingestion_service(context.workspace_id).import_records(
            source="inventory_db", records=request.records, dedupe=request.dedupe
        )
        return PropertyImportResponse(**result)
    except Exception as exc:
        raise _import_error(exc)


@router.post("/import/approved-feed", response_model=PropertyImportResponse)
async def import_approved_feed(
    area: Optional[str] = None,
    property_type: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    context: RequestContext = Depends(get_request_context),
):
    """Ingest listings from an approved JSON feed."""
    context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
    try:
        records = await scrape_approved_feed(area=area, property_type=property_type, limit=limit)
        result = await _ingestion_service(context.workspace_id).import_records(
            source="approved_feed", records=records, dedupe=True
        )
        return PropertyImportResponse(**result)
    except Exception as exc:
        raise _import_error(exc)


@router.post("/import/rapidapi", response_model=PropertyImportResponse)
async def import_rapidapi(
    request: RapidApiIngestRequest,
    context: RequestContext = Depends(get_request_context),
):
    """Ingest properties from the licensed RapidAPI UAE real-estate provider."""
    context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
    try:
        records = await scrape_rapidapi_properties(endpoint=request.endpoint, params=request.params)
        result = await _ingestion_service(context.workspace_id).import_records(
            source="rapidapi_uae", records=records, dedupe=request.dedupe
        )
        return PropertyImportResponse(**result)
    except Exception as exc:
        raise _import_error(exc)


@router.post("/lookup/rapidapi/developer")
async def rapidapi_developer_lookup(
    request: RapidApiDeveloperSearchRequest,
    context: RequestContext = Depends(get_request_context),
):
    """Run developer search by name through the RapidAPI UAE real-estate source."""
    context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
    try:
        return await rapidapi_developer_search_by_name(
            query=request.query, page=request.page, langs=request.langs
        )
    except Exception as exc:
        raise _import_error(exc)


@router.get("/{property_id}")
async def get_property(
    property_id: str,
    context: RequestContext = Depends(get_request_context),
    db=Depends(get_db),
):
    """Get property by ID."""
    prop_repo = get_property_repository(context.workspace_id)
    prop = await prop_repo.get_by_id(property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return prop
