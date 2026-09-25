"""Push ingestion endpoints: signed webhooks and CSV upload (architecture §13).

Both land raw records first and acknowledge; processing runs after the
response (or inline for small CSVs so the wizard can show results).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, UploadFile

from app.auth import RequestContext, WorkspaceRole, get_request_context
from app.modules.ingestion.connectors.base import SignatureError, get_connector, land, record_run
from app.modules.ingestion.connectors.csv_upload import csv_headers, parse_csv
from app.modules.ingestion.connectors.webhook import WebhookConnector
from app.modules.ingestion.field_maps import approved_field_map, suggest_field_map
from app.modules.ingestion.pipeline.processor import process_many
from app.modules.store import table

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_CSV_BYTES = 5 * 1024 * 1024
INLINE_CSV_ROWS = 500


@router.post("/webhook/{connector_id}")
async def push_webhook(
    connector_id: str,
    request: Request,
    background: BackgroundTasks,
    workspace_id: str = Query(..., description="Workspace that owns the connector"),
):
    """Unauthenticated push endpoint; the per-connector HMAC secret is the credential."""
    connector = await get_connector(connector_id, workspace_id)
    if not connector or connector.get("type") != "webhook":
        raise HTTPException(404, detail={"code": "connector_not_found", "message": "Connector not found"})
    if connector.get("status") != "active":
        raise HTTPException(409, detail={"code": "connector_inactive", "message": f"Connector is {connector.get('status')}"})
    body = await request.body()
    try:
        records = await WebhookConnector(connector.get("secret")).handle_push(dict(request.headers), body)
    except SignatureError:
        await record_run(connector_id, workspace_id, ok=False, error="invalid signature")
        raise HTTPException(401, detail={"code": "invalid_signature", "message": "Invalid signature"})
    except ValueError as exc:
        await record_run(connector_id, workspace_id, ok=False, error=str(exc))
        raise HTTPException(400, detail={"code": "invalid_payload", "message": str(exc)})
    result = await land(records, connector_id=connector_id, workspace_id=workspace_id)
    await record_run(connector_id, workspace_id, ok=True)
    background.add_task(process_many, result.ids, workspace_id=workspace_id)
    return {"status": "ok", "landed": len(result.landed), "duplicates": result.duplicates}


@router.post("/csv", status_code=201)
async def upload_csv(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    connector_id: str | None = Query(None),
    process: bool = Query(True, description="Run the pipeline now (inline for small files)"),
    context: RequestContext = Depends(get_request_context),
):
    context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
    body = await file.read()
    if len(body) > MAX_CSV_BYTES:
        raise HTTPException(413, detail={"code": "file_too_large", "message": "CSV exceeds 5 MB"})
    records = parse_csv(body, filename=file.filename)
    if not records:
        raise HTTPException(400, detail={"code": "empty_csv", "message": "No rows found"})

    if connector_id:
        connector = await get_connector(connector_id, context.workspace_id)
        if not connector:
            raise HTTPException(404, detail={"code": "connector_not_found", "message": "Connector not found"})
    else:
        connector = await table("connectors", context.workspace_id).insert(
            {
                "type": "csv_upload",
                "mode": "push",
                "display_name": file.filename or "CSV upload",
                "status": "active",
                "consecutive_failures": 0,
                "schedule_seconds": 0,
            }
        )
        connector_id = connector["id"]

    result = await land(records, connector_id=connector_id, workspace_id=context.workspace_id)
    await record_run(connector_id, context.workspace_id, ok=True)
    headers = csv_headers(body)
    field_map = await approved_field_map(connector_id, context.workspace_id)
    suggestions = suggest_field_map(headers, {h: [str(r.payload.get(h, "")) for r in records[:20]] for h in headers}) if not field_map else []

    outcomes = []
    if process and result.ids:
        if len(result.ids) <= INLINE_CSV_ROWS:
            outcomes = [o.model_dump() for o in await process_many(result.ids, workspace_id=context.workspace_id)]
        else:
            background.add_task(process_many, result.ids, workspace_id=context.workspace_id)
    return {
        "connector_id": connector_id,
        "rows": len(records),
        "landed": len(result.landed),
        "duplicates": result.duplicates,
        "headers": headers,
        "field_map_suggestions": suggestions,
        "processed": len(outcomes),
        "published": sum(1 for o in outcomes if o["status"] == "published"),
        "created": sum(1 for o in outcomes if o.get("created")),
        "review": sum(1 for o in outcomes if o["status"] == "review"),
        "outcomes": outcomes[:100],
    }
