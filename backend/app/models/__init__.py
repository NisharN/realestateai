"""Pydantic models for API validation."""
from .lead import LeadCreate, LeadResponse, LeadUpdate
from .property import (
    ManualUrlImportRequest,
    PropertyCreate,
    PropertyImportRecord,
    PropertyImportResponse,
    PropertyJsonImportRequest,
    PropertyResponse,
)
from .conversation import ConversationCreate, ConversationResponse

__all__ = [
    "LeadCreate", "LeadResponse", "LeadUpdate",
    "PropertyCreate", "PropertyResponse",
    "PropertyImportRecord", "PropertyJsonImportRequest",
    "ManualUrlImportRequest", "PropertyImportResponse",
    "ConversationCreate", "ConversationResponse"
]
