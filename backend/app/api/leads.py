"""API routes for lead management."""
import logging
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.database import (
    get_db,
    get_lead_repository,
    get_broker_repository,
    get_activity_repository,
)
from app.agents.orchestrator import agent_graph, AgentState
from app.auth import RequestContext, get_request_context
from app.models.lead import LeadCreate, LeadResponse, LeadUpdate

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

        # Initialize agent state
        initial_state: AgentState = {
            "lead_id": lead_id,
            "workspace_id": context.workspace_id,
            "lead_data": lead_data,
            "messages": [],
            "language": request.preferred_language,
            "intent_score": 0,
            "qualification": {},
            "matched_properties": [],
            "conversation_complete": False,
            "needs_human": False,
            "handoff_reason": None,
            "next_node": "scoring",
            "created_at": "",
            "error": None,
        }

        # Add initial message if provided
        if request.message:
            from langchain_core.messages import HumanMessage
            initial_state["messages"] = [HumanMessage(content=request.message)]

        # Run agent graph
        result = await agent_graph.ainvoke(initial_state)

        # Update lead with results
        await lead_repo.update(lead_id, {
            "intent_score": result.get("intent_score", 0),
            "status": "qualified" if result.get("intent_score", 0) >= 60 else "nurture",
            "conversation_history": [{
                "role": "ai" if i % 2 else "user",
                "content": msg.content if hasattr(msg, "content") else str(msg)
            } for i, msg in enumerate(result.get("messages", []))]
        })

        # Log activity
        activity_repo = get_activity_repository(context.workspace_id)
        await activity_repo.create({
            "lead_id": lead_id,
            "activity_type": "ai_qualification",
            "description": f"AI scored lead {result.get('intent_score', 0)}/100",
            "performed_by": "ai_agent",
            "outcome": "qualified" if result.get("intent_score", 0) >= 60 else "nurture"
        })

        # Determine next action
        next_action = "conversation"
        if result.get("needs_human"):
            next_action = "broker_handoff"
            # Try to assign broker
            broker_repo = get_broker_repository(context.workspace_id)
            broker = await broker_repo.get_available_broker(
                specialization=lead_data.get("area_preference")
            )
            if broker:
                await lead_repo.assign_broker(lead_id, broker["id"])
                await broker_repo.increment_lead_count(broker["id"])
        elif result.get("intent_score", 0) < 30:
            next_action = "nurture_sequence"

        return LeadIngestResponse(
            lead_id=lead_id,
            status="success",
            intent_score=result.get("intent_score", 0),
            next_action=next_action,
            message="Lead processed successfully"
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


@router.post("/{lead_id}/message")
async def send_message(
    lead_id: str,
    message: dict,
    context: RequestContext = Depends(get_request_context),
    db=Depends(get_db),
):
    """Send a message to a lead (continues conversation)."""
    try:
        lead_repo = get_lead_repository(context.workspace_id)
        lead = await lead_repo.get_by_id(lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        if not context.can_access_lead(lead):
            raise HTTPException(status_code=404, detail="Lead not found")

        from langchain_core.messages import HumanMessage, AIMessage

        # Build state from lead history
        state: AgentState = {
            "lead_id": lead_id,
            "workspace_id": context.workspace_id,
            "lead_data": lead,
            "messages": [HumanMessage(content=msg["content"]) if msg["role"] == "user" else AIMessage(content=msg["content"])
                        for msg in lead.get("conversation_history", [])],
            "language": lead.get("preferred_language", "en"),
            "intent_score": lead.get("intent_score", 0),
            "qualification": lead,
            "matched_properties": [],
            "conversation_complete": False,
            "needs_human": False,
            "handoff_reason": None,
            "next_node": "conversation",
            "created_at": "",
            "error": None,
        }

        # Add new message
        state["messages"].append(HumanMessage(content=message.get("text", "")))

        # Run conversation agent
        result = await agent_graph.ainvoke(state)

        # Update lead
        await lead_repo.update(lead_id, {
            "conversation_history": [{
                "role": "ai" if i % 2 else "user",
                "content": msg.content if hasattr(msg, "content") else str(msg)
            } for i, msg in enumerate(result.get("messages", []))],
            "last_contact_at": datetime.utcnow().isoformat()
        })

        # Check for handoff
        if result.get("needs_human"):
            broker_repo = get_broker_repository(context.workspace_id)
            if not lead.get("assigned_broker"):
                broker = await broker_repo.get_available_broker()
                if broker:
                    await lead_repo.assign_broker(lead_id, broker["id"])

        # Get last AI message
        ai_messages = [m for m in result.get("messages", []) if isinstance(m, AIMessage)]
        last_response = ai_messages[-1].content if ai_messages else "I\'ll get back to you shortly."

        return {
            "lead_id": lead_id,
            "response": last_response,
            "needs_human": result.get("needs_human", False),
            "matched_properties": result.get("matched_properties", [])[:3]
        }

    except Exception as e:
        logger.error(f"Message error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
