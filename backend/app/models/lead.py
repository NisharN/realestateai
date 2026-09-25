"""Lead Pydantic models."""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field


class LeadCreate(BaseModel):
    """Create lead request."""
    source: str = Field(..., description="Lead source")
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


class LeadResponse(BaseModel):
    """Lead response model."""
    id: str
    source: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    preferred_language: str
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    property_type: Optional[str] = None
    area_preference: Optional[List[str]] = None
    timeline: Optional[str] = None
    intent_score: int
    status: str
    assigned_broker: Optional[str] = None
    scraped_data: Optional[Dict[str, Any]] = None
    conversation_history: Optional[List[Dict[str, Any]]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    last_contact_at: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class LeadUpdate(BaseModel):
    """Update lead request."""
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    status: Optional[str] = None
    intent_score: Optional[int] = None
    assigned_broker: Optional[str] = None
