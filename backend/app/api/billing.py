from fastapi import APIRouter, Depends, HTTPException

from app.auth import RequestContext, WorkspaceRole, get_request_context
from app.config import get_settings
from app.database import DatabaseClient

router = APIRouter()


def _workspace(context: RequestContext):
    client = DatabaseClient.get_client()
    if client is None:
        raise HTTPException(503, detail={"code": "database_unavailable", "message": "Database unavailable"})
    result = client.table("workspaces").select("id,lifecycle_status,stripe_customer_id,stripe_subscription_id,grace_ends_at").eq("id", context.workspace_id).maybe_single().execute()
    if not result.data:
        raise HTTPException(404, detail={"code": "workspace_not_found", "message": "Workspace not found"})
    return client, result.data


@router.get("/status")
async def billing_status(context: RequestContext = Depends(get_request_context)):
    _, workspace = _workspace(context)
    return {"lifecycle_status": workspace["lifecycle_status"], "subscription_id": workspace.get("stripe_subscription_id"), "grace_ends_at": workspace.get("grace_ends_at")}


@router.post("/checkout")
async def create_checkout(context: RequestContext = Depends(get_request_context)):
    context.require_roles(WorkspaceRole.OWNER)
    _, workspace = _workspace(context)
    settings = get_settings()
    if not settings.STRIPE_SECRET_KEY or not settings.STRIPE_PRICE_ID:
        raise HTTPException(503, detail={"code": "billing_unavailable", "message": "Billing is not configured"})
    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY
    session = stripe.checkout.Session.create(mode="subscription", line_items=[{"price": settings.STRIPE_PRICE_ID, "quantity": 1}], customer=workspace.get("stripe_customer_id") or None, client_reference_id=context.workspace_id, success_url=settings.BILLING_SUCCESS_URL, cancel_url=settings.BILLING_CANCEL_URL)
    return {"url": session.url}


@router.post("/portal")
async def create_portal(context: RequestContext = Depends(get_request_context)):
    context.require_roles(WorkspaceRole.OWNER)
    _, workspace = _workspace(context)
    if not workspace.get("stripe_customer_id"):
        raise HTTPException(409, detail={"code": "customer_missing", "message": "Complete checkout first"})
    settings = get_settings()
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(503, detail={"code": "billing_unavailable", "message": "Billing is not configured"})
    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY
    session = stripe.billing_portal.Session.create(customer=workspace["stripe_customer_id"], return_url=settings.BILLING_SUCCESS_URL)
    return {"url": session.url}
