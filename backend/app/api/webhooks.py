"""Webhook handlers for external integrations."""
import logging
import hmac
import hashlib
from fastapi import APIRouter, Request, HTTPException, Depends

from app.config import get_settings
from app.database import get_db, LeadRepository
from app.api.leads import ingest_lead, LeadIngestRequest

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/whatsapp")
async def whatsapp_webhook(request: Request, db=Depends(get_db)):
    """Handle incoming WhatsApp messages."""
    try:
        body = await request.json()

        # Extract message data
        entry = body.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            return {"status": "no_messages"}

        msg = messages[0]
        from_number = msg.get("from")
        msg_text = msg.get("text", {}).get("body", "")
        msg_type = msg.get("type", "text")

        logger.info(f"WhatsApp message from {from_number}: {msg_text[:50]}...")

        # Check if lead exists
        lead_repo = LeadRepository(db)
        lead = await lead_repo.get_by_phone(from_number)

        if lead:
            # Continue conversation
            from app.api.leads import send_message
            result = await send_message(
                lead["id"],
                {"text": msg_text},
                db
            )

            # TODO: Send WhatsApp response back
            return {"status": "replied", "lead_id": lead["id"]}
        else:
            # New lead from WhatsApp
            new_lead = LeadIngestRequest(
                source="whatsapp",
                phone=from_number,
                message=msg_text,
                preferred_language="en"  # TODO: Detect language
            )
            result = await ingest_lead(new_lead, db)
            return {"status": "new_lead", "lead_id": result.lead_id}

    except Exception as e:
        logger.error(f"WhatsApp webhook error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/whatsapp")
async def verify_whatsapp_webhook(
    hub_mode: str,
    hub_verify_token: str,
    hub_challenge: str
):
    """Verify WhatsApp webhook subscription."""
    settings = get_settings()
    if hub_mode == "subscribe" and hub_verify_token == settings.WHATSAPP_VERIFY_TOKEN:
        return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/website-form")
async def website_form_webhook(request: Request, db=Depends(get_db)):
    """Handle website form submissions."""
    try:
        data = await request.json()

        new_lead = LeadIngestRequest(
            source="website",
            first_name=data.get("first_name"),
            last_name=data.get("last_name"),
            phone=data.get("phone"),
            email=data.get("email"),
            budget_min=data.get("budget_min"),
            budget_max=data.get("budget_max"),
            property_type=data.get("property_type"),
            area_preference=data.get("area_preference", []),
            timeline=data.get("timeline", "just_browsing"),
            message=data.get("message"),
            preferred_language=data.get("preferred_language", "en")
        )

        result = await ingest_lead(new_lead, db)
        return {"status": "success", "lead_id": result.lead_id}

    except Exception as e:
        logger.error(f"Website form error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
