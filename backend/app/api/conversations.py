"""API routes for conversation management."""
import logging
from fastapi import APIRouter, Depends, HTTPException

from app.database import get_db, ConversationRepository

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/{lead_id}")
async def get_conversations(lead_id: str, db=Depends(get_db)):
    """Get conversation history for a lead."""
    conv_repo = ConversationRepository(db)
    conversations = await conv_repo.get_by_lead(lead_id)
    return conversations


@router.post("/{lead_id}")
async def create_conversation(
    lead_id: str,
    conversation: dict,
    db=Depends(get_db)
):
    """Create a new conversation thread."""
    conv_repo = ConversationRepository(db)
    conv = await conv_repo.create({
        "lead_id": lead_id,
        "agent_type": conversation.get("agent_type", "conversational"),
        "channel": conversation.get("channel", "chat"),
        "messages": conversation.get("messages", []),
        "language": conversation.get("language", "en")
    })
    return conv
