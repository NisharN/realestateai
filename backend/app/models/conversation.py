"""Conversation Pydantic models."""
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel


class ConversationCreate(BaseModel):
    """Create conversation request."""
    lead_id: str
    agent_type: str = "conversational"
    channel: str = "chat"
    messages: Optional[List[Dict[str, Any]]] = None
    language: str = "en"


class ConversationResponse(BaseModel):
    """Conversation response model."""
    id: str
    lead_id: str
    agent_type: str
    channel: str
    messages: Optional[List[Dict[str, Any]]] = None
    sentiment: Optional[str] = None
    language: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
