"""Pydantic models for API validation."""
from .lead import LeadCreate, LeadResponse, LeadUpdate
from .property import PropertyCreate, PropertyResponse
from .conversation import ConversationCreate, ConversationResponse

__all__ = [
    "LeadCreate", "LeadResponse", "LeadUpdate",
    "PropertyCreate", "PropertyResponse",
    "ConversationCreate", "ConversationResponse"
]
