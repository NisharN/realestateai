"""API routes for lead management."""
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import RequestContext, get_request_context
from app.database import (
    get_activity_repository,
    get_broker_repository,
    get_db,
    get_lead_repository,
)
from app.models.lead import LeadResponse
from app.modules.agents import scorer
from app.modules.conversation.engine import TurnResult, handle_turn
from app.modules.conversation.repository import ConversationRepo

logger = logging.getLogger(__name__)
router = APIRouter()


class LeadIngestRequest(BaseModel):
    """Request to ingest a new lead."""
    source: str = Field(..., description="Lead source: website, whatsapp, bayut, etc.")
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    preferred_language: str = "en"
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    property_type: Optional[str] = None
    area_preference: Optional[List[str]] = None
    timeline: Optional[str] = "just_browsing"
    message: Optional[str] = None  # Initial message from lead
    scraped_data: Optional[dict] = {}


class LeadIngestResponse(BaseModel):
    """Response after lead ingestion."""
    lead_id: str
    status: str
    intent_score: int
    next_action: str
    message: str


@router.post("/ingest", response_model=LeadIngestResponse)
async def ingest_lead(
    request: LeadIngestRequest,
    context: RequestContext = Depends(get_request_context),
    db=Depends(get_db),
):
    """Ingest a new lead and trigger AI qualification pipeline."""
    try:
        # Create lead in database
        lead_repo = get_lead_repository(context.workspace_id)

        lead_data = {
            "source": request.source,
            "first_name": request.first_name,
            "last_name": request.last_name,
            "phone": request.phone,
            "email": request.email,
            "preferred_language": request.preferred_language,
            "budget_min": request.budget_min,
            "budget_max": request.budget_max,
            "property_type": request.property_type,
            "area_preference": request.area_preference or [],
            "timeline": request.timeline,
            "scraped_data": request.scraped_data,
            "status": "new",
            "intent_score": 0,
        }

        lead = await lead_repo.create(lead_data)
        lead_id = lead["id"]

        repo = ConversationRepo(context.workspace_id)
        state = await repo.load(lead_id, channel="chat", source=request.source)
        state.score, state.score_reasons = scorer.score(state)
        state.band = scorer.band_for(state.score)
        await repo.save(state)

        reply = ""
        if request.message:
            result = await handle_turn(
                lead_id,
                request.message,
                workspace_id=context.workspace_id,
                channel="chat",
                source=request.source,
                idempotency_key=f"ingest:{lead_id}",
            )
            state.score, state.stage, state.handoff_id = result.score, result.stage, result.handoff_id  # type: ignore[assignment]
            reply = result.reply

        await lead_repo.update(lead_id, {
            "intent_score": state.score,
            "status": "qualified" if state.score >= 60 else "nurture",
        })

        activity_repo = get_activity_repository(context.workspace_id)
        await activity_repo.create({
            "lead_id": lead_id,
            "activity_type": "ai_qualification",
            "description": f"AI scored lead {state.score}/100",
            "performed_by": "ai_agent",
            "outcome": "qualified" if state.score >= 60 else "nurture",
        })

        next_action = "conversation"
        if state.handoff_id:
            next_action = "broker_handoff"
        elif state.score < 30:
            next_action = "nurture_sequence"

        return LeadIngestResponse(
            lead_id=lead_id,
            status="success",
            intent_score=state.score,
            next_action=next_action,
            message=reply or "Lead processed successfully"
        )

    except Exception as e:
        logger.error(f"Lead ingestion error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/", response_model=List[LeadResponse])
async def list_leads(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    context: RequestContext = Depends(get_request_context),
    db=Depends(get_db),
):
    """List leads with optional filtering."""
    lead_repo = get_lead_repository(context.workspace_id)
    assigned_broker_id = context.broker_id if context.role.value == "agent" else None
    if status:
        return await lead_repo.list_by_status(status, limit, offset, assigned_broker_id)
    # No status filter — surface every known status so the dashboard isn't empty
    merged: list = []
    for s in ("new", "contacted", "qualified", "nurture", "closed", "lost"):
        merged.extend(await lead_repo.list_by_status(s, limit, offset, assigned_broker_id))
    return merged[:limit]


@router.get("/{lead_id}", response_model=LeadResponse)
async def get_lead(lead_id: str, context: RequestContext = Depends(get_request_context), db=Depends(get_db)):
    """Get lead by ID."""
    lead_repo = get_lead_repository(context.workspace_id)
    lead = await lead_repo.get_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if not context.can_access_lead(lead):
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


class MessageRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    idempotency_key: Optional[str] = Field(None, max_length=128)
    channel: str = "chat"


class MessageResponse(BaseModel):
    lead_id: str
    response: str
    move: str
    stage: str
    score: int
    band: str
    score_reasons: List[str]
    needs_human: bool
    handoff_id: Optional[str] = None
    matched_properties: List[dict]
    area: Optional[dict] = None
    compare: List[dict] = Field(default_factory=list)
    profile: dict
    ended: bool
    language: str = "en"
    fallbacks: List[str]
    latency_ms: int


def _message_response(lead_id: str, r: TurnResult) -> MessageResponse:
    return MessageResponse(
        lead_id=lead_id,
        response=r.reply,
        move=r.move,
        stage=r.stage,
        score=r.score,
        band=r.band,
        score_reasons=r.score_reasons,
        needs_human=r.handoff_id is not None,
        handoff_id=r.handoff_id,
        matched_properties=r.cards,
        area=r.area,
        compare=r.compare,
        profile=r.profile,
        ended=r.ended,
        language=r.language,
        fallbacks=r.fallbacks,
        latency_ms=r.latency_ms,
    )


@router.post("/{lead_id}/message", response_model=MessageResponse)
async def send_message(
    lead_id: str,
    message: MessageRequest,
    context: RequestContext = Depends(get_request_context),
):
    """Buyer turn: runs the shared conversation engine (chat channel)."""
    lead_repo = get_lead_repository(context.workspace_id)
    lead = await lead_repo.get_by_id(lead_id)
    if not lead or not context.can_access_lead(lead):
        raise HTTPException(status_code=404, detail="Lead not found")

    result = await handle_turn(
        lead_id,
        message.text,
        workspace_id=context.workspace_id,
        channel=message.channel if message.channel in {"chat", "widget", "whatsapp", "voice"} else "chat",
        idempotency_key=message.idempotency_key,
        source=lead.get("source"),
    )
    await lead_repo.update(lead_id, {"last_contact_at": datetime.utcnow().isoformat()})
    return _message_response(lead_id, result)


@router.get("/{lead_id}/conversation")
async def get_conversation(
    lead_id: str,
    limit: int = Query(50, ge=1, le=500),
    context: RequestContext = Depends(get_request_context),
):
    """Normalized message history plus current conversation state."""
    lead_repo = get_lead_repository(context.workspace_id)
    lead = await lead_repo.get_by_id(lead_id)
    if not lead or not context.can_access_lead(lead):
        raise HTTPException(status_code=404, detail="Lead not found")
    repo = ConversationRepo(context.workspace_id)
    state = await repo.load(lead_id)
    messages = await repo.history(lead_id, limit=limit)
    return {
        "lead_id": lead_id,
        "state": {
            "stage": state.stage,
            "language": state.language,
            "turn": state.turn,
            "score": state.score,
            "band": state.band,
            "score_reasons": state.score_reasons,
            "profile": state.profile_values(),
            "shortlist": [s.model_dump(mode="json") for s in state.shortlist],
            "objections": state.objections,
            "handoff_id": state.handoff_id,
        },
        "messages": messages,
    }


@router.post("/{lead_id}/assign")
async def assign_lead(
    lead_id: str,
    broker_id: str,
    context: RequestContext = Depends(get_request_context),
    db=Depends(get_db),
):
    """Manually assign lead to broker."""
    lead_repo = get_lead_repository(context.workspace_id)
    broker_repo = get_broker_repository(context.workspace_id)

    lead = await lead_repo.get_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    broker = await broker_repo.get_by_id(broker_id)
    if not broker:
        raise HTTPException(status_code=404, detail="Broker not found")

    await lead_repo.assign_broker(lead_id, broker_id)
    await broker_repo.increment_lead_count(broker_id)

    return {"status": "assigned", "lead_id": lead_id, "broker_id": broker_id}
