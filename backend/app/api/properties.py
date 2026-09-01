"""API routes for property search and multi-source ingestion."""
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from app.config import get_settings
from app.auth import RequestContext, WorkspaceRole, get_request_context
from app.database import get_db, get_property_repository
from app.models.property import (
    ManualUrlImportRequest,
    PropertyImportResponse,
    PropertyJsonImportRequest,
)
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


class MultiSourceIngestRequest(BaseModel):
    """Trigger multiple supported sources in one request."""
    sources: list[str]
    property_type: str = "buy_apartment"
    area: Optional[str] = None
    pages: int = 1
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
    """Search properties from the database."""
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
    try:
        payload = await file.read()
        context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
        result = await _ingestion_service(context.workspace_id).import_csv_bytes(
            source=source,
            data=payload,
            dedupe=dedupe,
        )
        return PropertyImportResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/import/json", response_model=PropertyImportResponse)
async def import_properties_json(request: PropertyJsonImportRequest, context: RequestContext = Depends(get_request_context)):
    """Import properties from JSON records such as CRM exports or partner feeds."""
    try:
        context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
        result = await _ingestion_service(context.workspace_id).import_records(
            source=request.source,
            records=request.records,
            dedupe=request.dedupe,
        )
        return PropertyImportResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/import/manual-urls", response_model=PropertyImportResponse)
async def import_manual_urls(request: ManualUrlImportRequest, context: RequestContext = Depends(get_request_context)):
    """Import listing details from manually supplied listing URLs."""
    try:
        context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
        result = await _ingestion_service(context.workspace_id).import_manual_urls(
            urls=request.urls,
            fetch_details=request.fetch_details,
            dedupe=True,
        )
        return PropertyImportResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/import/inventory", response_model=PropertyImportResponse)
async def import_inventory_records(request: InventoryImportRequest, context: RequestContext = Depends(get_request_context)):
    """Import first-party inventory from your own database or export."""
    try:
        context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
        result = await _ingestion_service(context.workspace_id).import_records(
            source="inventory_db",
            records=request.records,
            dedupe=request.dedupe,
        )
        return PropertyImportResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scrape/propertyfinder", response_model=PropertyImportResponse)
async def scrape_propertyfinder_endpoint(
    property_type: str = "buy_apartment",
    area: Optional[str] = None,
    pages: int = Query(1, ge=1, le=5),
    context: RequestContext = Depends(get_request_context),
):
    """Scrape Property Finder through the shared ingestion pipeline."""
    try:
        context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
        result = await _ingestion_service(context.workspace_id).scrape_source(
            source="propertyfinder",
            property_type=property_type,
            area=area,
            pages=pages,
            dedupe=True,
        )
        return PropertyImportResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scrape/bayut", response_model=PropertyImportResponse)
async def scrape_bayut_endpoint(
    property_type: str = "buy_apartment",
    area: Optional[str] = None,
    pages: int = Query(1, ge=1, le=5),
    context: RequestContext = Depends(get_request_context),
):
    """Scrape Bayut through the shared ingestion pipeline.

    Deferred by default (see config.ENABLE_BAYUT_DUBIZZLE_SCRAPING) — Bayut
    is CAPTCHA-protected on its public browse path and reliably scraping it
    requires proxy/session infrastructure most workspaces won't have set
    up. Use CSV import, an approved feed, or RapidAPI instead unless you've
    deliberately opted back in.
    """
    if not get_settings().ENABLE_BAYUT_DUBIZZLE_SCRAPING:
        raise HTTPException(
            status_code=400,
            detail=(
                "Bayut scraping is deferred by default (CAPTCHA-protected — "
                "see docs/scraper_operations.md). Set "
                "ENABLE_BAYUT_DUBIZZLE_SCRAPING=true to opt in, or use "
                "CSV import / approved feed / RapidAPI instead."
            ),
        )
    try:
        context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
        result = await _ingestion_service(context.workspace_id).scrape_source(
            source="bayut",
            property_type=property_type,
            area=area,
            pages=pages,
            dedupe=True,
        )
        return PropertyImportResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scrape/dubizzle", response_model=PropertyImportResponse)
async def scrape_dubizzle_endpoint(
    property_type: str = "buy_apartment",
    area: Optional[str] = None,
    pages: int = Query(1, ge=1, le=5),
    context: RequestContext = Depends(get_request_context),
):
    """Scrape Dubizzle through the shared ingestion pipeline.

    Deferred by default (see config.ENABLE_BAYUT_DUBIZZLE_SCRAPING) —
    Dubizzle sits behind Incapsula on its public browse path. Same
    guidance as Bayut: use CSV import, an approved feed, or RapidAPI
    unless you've deliberately opted back in with proxy/session infra.
    """
    if not get_settings().ENABLE_BAYUT_DUBIZZLE_SCRAPING:
        raise HTTPException(
            status_code=400,
            detail=(
                "Dubizzle scraping is deferred by default (Incapsula-"
                "protected — see docs/scraper_operations.md). Set "
                "ENABLE_BAYUT_DUBIZZLE_SCRAPING=true to opt in, or use "
                "CSV import / approved feed / RapidAPI instead."
            ),
        )
    try:
        context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
        result = await _ingestion_service(context.workspace_id).scrape_source(
            source="dubizzle",
            property_type=property_type,
            area=area,
            pages=pages,
            dedupe=True,
        )
        return PropertyImportResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scrape/approved-feed", response_model=PropertyImportResponse)
async def scrape_approved_feed_endpoint(
    area: Optional[str] = None,
    property_type: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    context: RequestContext = Depends(get_request_context),
):
    """Ingest listings from an approved JSON feed."""
    try:
        context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
        records = await scrape_approved_feed(
            area=area,
            property_type=property_type,
            limit=limit,
        )
        result = await _ingestion_service(context.workspace_id).import_records(
            source="approved_feed",
            records=records,
            dedupe=True,
        )
        return PropertyImportResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scrape/rapidapi", response_model=PropertyImportResponse)
async def scrape_rapidapi_endpoint(request: RapidApiIngestRequest, context: RequestContext = Depends(get_request_context)):
    """Ingest properties from the RapidAPI UAE real-estate provider."""
    try:
        context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
        records = await scrape_rapidapi_properties(
            endpoint=request.endpoint,
            params=request.params,
        )
        result = await _ingestion_service(context.workspace_id).import_records(
            source="rapidapi_uae",
            records=records,
            dedupe=request.dedupe,
        )
        return PropertyImportResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/lookup/rapidapi/developer")
async def rapidapi_developer_lookup(request: RapidApiDeveloperSearchRequest, context: RequestContext = Depends(get_request_context)):
    """Run developer search by name through the RapidAPI UAE real-estate source."""
    try:
        context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
        return await rapidapi_developer_search_by_name(
            query=request.query,
            page=request.page,
            langs=request.langs,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingest/multi-source")
async def ingest_multi_source(request: MultiSourceIngestRequest, context: RequestContext = Depends(get_request_context)):
    """Run multiple supported property sources through one normalized pipeline."""
    context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
    service = _ingestion_service(context.workspace_id)
    results = []
    for source in request.sources:
        try:
            if source == "approved_feed":
                records = await scrape_approved_feed(
                    area=request.area,
                    property_type=request.property_type.replace("buy_", "").replace("rent_", ""),
                    limit=100,
                )
                result = await service.import_records(
                    source="approved_feed",
                    records=records,
                    dedupe=request.dedupe,
                )
            elif source == "rapidapi_uae":
                records = await scrape_rapidapi_properties(
                    endpoint="developer-search-by-name",
                    params={"query": request.area or "emaar", "page": 1, "langs": "en"},
                )
                result = await service.import_records(
                    source="rapidapi_uae",
                    records=records,
                    dedupe=request.dedupe,
                )
            elif source in {"bayut", "dubizzle"} and not get_settings().ENABLE_BAYUT_DUBIZZLE_SCRAPING:
                result = {
                    "source": source,
                    "received": 0,
                    "saved": 0,
                    "skipped": 0,
                    "errors": [
                        f"{source} scraping is deferred by default "
                        "(anti-bot protected). Set ENABLE_BAYUT_DUBIZZLE_SCRAPING=true "
                        "to opt in, or use csv/approved_feed/rapidapi_uae instead."
                    ],
                }
            elif source in {"propertyfinder", "bayut", "dubizzle"}:
                result = await service.scrape_source(
                    source=source,
                    property_type=request.property_type,
                    area=request.area,
                    pages=request.pages,
                    dedupe=request.dedupe,
                )
            else:
                result = {
                    "source": source,
                    "received": 0,
                    "saved": 0,
                    "skipped": 0,
                    "errors": [f"unsupported source: {source}"],
                }
            results.append(result)
        except Exception as exc:
            results.append(
                {
                    "source": source,
                    "received": 0,
                    "saved": 0,
                    "skipped": 0,
                    "errors": [str(exc)],
                }
            )
    return {"results": results}


@router.get("/{property_id}")
async def get_property(property_id: str, context: RequestContext = Depends(get_request_context), db=Depends(get_db)):
    """Get property by ID."""
    prop_repo = get_property_repository(context.workspace_id)
    prop = await prop_repo.get_by_id(property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return prop
