"""Admin: connectors, field maps, review queue, data health (architecture §13)."""
from __future__ import annotations

import secrets
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import RequestContext, WorkspaceRole, get_request_context
from app.modules.ingestion.connectors.crm_pull import poll_connector
from app.modules.ingestion.field_maps import save_field_map, suggest_field_map
from app.modules.ingestion.pipeline.processor import process_many, resolve_review, retry_errors
from app.modules.store import now_iso, table

router = APIRouter()

CONNECTOR_TYPES = ("csv_upload", "webhook", "google_sheets", "portal_email", "hubspot", "zoho", "salesforce", "bitrix24", "generic_crm", "manual")


def _admin(context: RequestContext) -> RequestContext:
    context.require_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)
    return context


class ConnectorCreate(BaseModel):
    type: str
    display_name: str | None = None
    mode: Literal["pull", "push"] | None = None
    schedule_seconds: int = Field(300, ge=0, le=86_400)
    config: dict[str, Any] = Field(default_factory=dict)
    credential: str | None = Field(None, max_length=4096, description="API token for pull connectors; stored, never echoed")


class ConnectorPatch(BaseModel):
    display_name: str | None = None
    status: Literal["active", "paused", "disabled"] | None = None
    schedule_seconds: int | None = Field(None, ge=0, le=86_400)
    config: dict[str, Any] | None = None
    credential: str | None = Field(None, max_length=4096)
    rotate_secret: bool = False


def _public(row: dict[str, Any], *, reveal_secret: bool = False) -> dict[str, Any]:
    out = {k: v for k, v in row.items() if k not in ("secret", "auth_encrypted")}
    out["has_secret"] = bool(row.get("secret"))
    if reveal_secret and row.get("secret"):
        out["secret"] = row["secret"]
    return out


@router.get("/connectors")
async def list_connectors(context: RequestContext = Depends(get_request_context)):
    _admin(context)
    rows = await table("connectors", context.workspace_id).select(order="created_at", desc=True, limit=200)
    return [_public(r) for r in rows]


@router.post("/connectors", status_code=201)
async def create_connector(body: ConnectorCreate, context: RequestContext = Depends(get_request_context)):
    _admin(context)
    if body.type not in CONNECTOR_TYPES:
        raise HTTPException(400, detail={"code": "unknown_connector_type", "message": f"type must be one of {CONNECTOR_TYPES}"})
    mode = body.mode or ("push" if body.type in ("csv_upload", "webhook", "manual") else "pull")
    row = await table("connectors", context.workspace_id).insert(
        {
            "type": body.type,
            "mode": mode,
            "display_name": body.display_name or body.type,
            "status": "active",
            "consecutive_failures": 0,
            "schedule_seconds": body.schedule_seconds,
            "config": body.config,
            "secret": secrets.token_urlsafe(32) if body.type == "webhook" else body.credential,
            "cursor": None,
            "created_by": context.user_id,
            "updated_at": now_iso(),
        }
    )
    out = _public(row, reveal_secret=row.get("type") == "webhook")
    if row.get("type") == "webhook":
        out["webhook_path"] = f"/api/v1/ingest/webhook/{row['id']}?workspace_id={context.workspace_id}"
    return out


@router.get("/connectors/{connector_id}")
async def get_connector_detail(connector_id: str, context: RequestContext = Depends(get_request_context)):
    _admin(context)
    row = await table("connectors", context.workspace_id).get(id=connector_id)
    if not row:
        raise HTTPException(404, detail={"code": "connector_not_found", "message": "Connector not found"})
    return _public(row)


@router.patch("/connectors/{connector_id}")
async def patch_connector(connector_id: str, body: ConnectorPatch, context: RequestContext = Depends(get_request_context)):
    _admin(context)
    connectors = table("connectors", context.workspace_id)
    row = await connectors.get(id=connector_id)
    if not row:
        raise HTTPException(404, detail={"code": "connector_not_found", "message": "Connector not found"})
    updates: dict[str, Any] = {k: v for k, v in body.model_dump(exclude={"rotate_secret", "credential"}).items() if v is not None}
    if body.credential and row.get("type") != "webhook":
        updates["secret"] = body.credential
    if body.status == "active":
        updates["consecutive_failures"] = 0
    if body.rotate_secret and row.get("type") == "webhook":
        updates["secret"] = secrets.token_urlsafe(32)
    updates["updated_at"] = now_iso()
    updated = await connectors.update(updates, id=connector_id)
    return _public(updated[0], reveal_secret=body.rotate_secret)


class FieldMapEntry(BaseModel):
    source_field: str
    target_field: str | None = None
    transform: str | None = None


class FieldMapPut(BaseModel):
    mappings: list[FieldMapEntry]


@router.get("/connectors/{connector_id}/field-map")
async def get_field_map(connector_id: str, context: RequestContext = Depends(get_request_context)):
    _admin(context)
    approved = await table("field_maps", context.workspace_id).select(connector_id=connector_id, limit=500)
    sample = await table("raw_lead_records", context.workspace_id).select(connector_id=connector_id, order="received_at", desc=True, limit=20)
    headers: list[str] = []
    samples: dict[str, list[str]] = {}
    for r in sample:
        for k, v in (r.get("payload") or {}).items():
            if k.startswith("__"):
                continue
            if k not in headers:
                headers.append(k)
            samples.setdefault(k, []).append(str(v))
    return {
        "connector_id": connector_id,
        "approved": [{k: r.get(k) for k in ("source_field", "target_field", "transform", "approved_at")} for r in approved],
        "suggested": suggest_field_map(headers, samples),
    }


@router.put("/connectors/{connector_id}/field-map")
async def put_field_map(connector_id: str, body: FieldMapPut, context: RequestContext = Depends(get_request_context)):
    _admin(context)
    if not await table("connectors", context.workspace_id).get(id=connector_id):
        raise HTTPException(404, detail={"code": "connector_not_found", "message": "Connector not found"})
    try:
        saved = await save_field_map(connector_id, context.workspace_id, [m.model_dump() for m in body.mappings], approved_by=context.user_id)
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "invalid_field_map", "message": str(exc)})
    return {"connector_id": connector_id, "approved": len([s for s in saved if s.get("target_field")])}


@router.get("/review-queue")
async def list_review_queue(resolved: bool = False, limit: int = 100, context: RequestContext = Depends(get_request_context)):
    _admin(context)
    rows = await table("review_queue", context.workspace_id).select(order="created_at", desc=True, limit=min(limit, 500), resolved_at__isnull=not resolved)
    raw = table("raw_lead_records", context.workspace_id)
    out = []
    for r in rows:
        record = await raw.get(id=r["raw_record_id"])
        out.append({**r, "payload": (record or {}).get("payload"), "record_status": (record or {}).get("status")})
    return out


class ReviewResolve(BaseModel):
    action: Literal["retry", "discard"] = "retry"
    fixed_payload: dict[str, Any] | None = None


@router.post("/review-queue/{item_id}/resolve")
async def resolve_review_item(item_id: str, body: ReviewResolve, context: RequestContext = Depends(get_request_context)):
    _admin(context)
    outcome = await resolve_review(item_id, workspace_id=context.workspace_id, fixed_payload=body.fixed_payload, action=body.action, user_id=context.user_id)
    if outcome is None:
        raise HTTPException(404, detail={"code": "review_item_not_found", "message": "Review item not found or already resolved"})
    return outcome.model_dump()


@router.post("/connectors/{connector_id}/run")
async def run_connector_now(connector_id: str, context: RequestContext = Depends(get_request_context)):
    _admin(context)
    row = await table("connectors", context.workspace_id).get(id=connector_id)
    if not row:
        raise HTTPException(404, detail={"code": "connector_not_found", "message": "Connector not found"})
    if row.get("mode") != "pull":
        raise HTTPException(400, detail={"code": "not_a_pull_connector", "message": "Only pull connectors can be run on demand"})
    result = await poll_connector(connector_id, workspace_id=context.workspace_id)
    outcomes = await process_many(result.get("raw_ids", [])[:500], workspace_id=context.workspace_id)
    return {**{k: v for k, v in result.items() if k != "raw_ids"}, "processed": len(outcomes), "published": sum(1 for o in outcomes if o.status == "published")}


@router.post("/pipeline/retry-errors")
async def retry_pipeline_errors(context: RequestContext = Depends(get_request_context)):
    _admin(context)
    outcomes = await retry_errors(context.workspace_id)
    return {"retried": len(outcomes), "published": sum(1 for o in outcomes if o.status == "published")}


@router.get("/data-health")
async def data_health(context: RequestContext = Depends(get_request_context)):
    _admin(context)
    ws = context.workspace_id
    raw = table("raw_lead_records", ws)
    connectors = await table("connectors", ws).select(limit=200)
    per_connector = []
    for c in connectors:
        counts = {s: await raw.count(connector_id=c["id"], status=s) for s in ("landed", "published", "review", "error")}
        total = await raw.count(connector_id=c["id"])
        per_connector.append(
            {
                "connector_id": c["id"],
                "type": c["type"],
                "display_name": c.get("display_name"),
                "status": c.get("status"),
                "consecutive_failures": c.get("consecutive_failures", 0),
                "last_run_at": c.get("last_run_at"),
                "last_success_at": c.get("last_success_at"),
                "records": total,
                **counts,
                "publish_rate": round(counts["published"] / total, 3) if total else None,
            }
        )
    return {
        "connectors": per_connector,
        "totals": {s: await raw.count(status=s) for s in ("landed", "mapped", "cleaned", "validated", "merged", "enriched", "published", "review", "error")},
        "review_open": await table("review_queue", ws).count(resolved_at__isnull=True),
        "events_total": await table("lead_events", ws).count(),
    }
