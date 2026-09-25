"""Public webhook boundaries.

WhatsApp events are signature-verified, persisted raw, then routed through
the shared turn engine. Website-form intake fails closed until widget keys
resolve to a workspace.
"""
import json
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from app.config import get_settings
from app.modules.channels.whatsapp_inbound import handle_payload
from app.webhook_security import verify_meta_signature

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/whatsapp")
async def whatsapp_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(None),
):
    body = await request.body()
    if not verify_meta_signature(
        body, x_hub_signature_256, get_settings().META_APP_SECRET
    ):
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_signature", "message": "Invalid webhook signature"},
        )
    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail={"code": "invalid_json"})
    result = await handle_payload(payload if isinstance(payload, dict) else {})
    return {
        "status": "ok",
        "stored": result.stored,
        "replied": result.replied,
        "skipped": result.skipped,
        "errors": len(result.errors),
    }


@router.get("/whatsapp")
async def verify_whatsapp_webhook(
    hub_mode: str,
    hub_verify_token: str,
    hub_challenge: str,
):
    settings = get_settings()
    if hub_mode == "subscribe" and hub_verify_token == settings.WHATSAPP_VERIFY_TOKEN:
        return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/website-form")
async def website_form_webhook(_request: Request):
    raise HTTPException(
        status_code=401,
        detail={
            "code": "widget_key_required",
            "message": "A workspace widget key is required",
        },
    )
