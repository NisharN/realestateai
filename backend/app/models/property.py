"""Property Pydantic models."""
from typing import Optional, List, Any, Dict
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class PropertyCreate(BaseModel):
    """Create property request."""
    source: str
    source_id: Optional[str] = None
    source_url: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    price_per_sqft: Optional[float] = None
    area: Optional[str] = None
    property_type: Optional[str] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    size_sqft: Optional[int] = None
    images: Optional[List[str]] = None
    video_url: Optional[str] = None
    floor_plan_url: Optional[str] = None
    map_lat: Optional[float] = None
    map_lng: Optional[float] = None
    amenities: Optional[List[str]] = None
    developer: Optional[str] = None
    completion_date: Optional[str] = None


class PropertyImportRecord(BaseModel):
    """Normalized property import record."""
    source: str
    source_id: Optional[str] = None
    source_url: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    price_per_sqft: Optional[float] = None
    area: Optional[str] = None
    property_type: Optional[str] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    size_sqft: Optional[int] = None
    images: Optional[List[str]] = None
    video_url: Optional[str] = None
    floor_plan_url: Optional[str] = None
    map_lat: Optional[float] = None
    map_lng: Optional[float] = None
    amenities: Optional[List[str]] = None
    developer: Optional[str] = None
    completion_date: Optional[str] = None
    raw_payload: Optional[Dict[str, Any]] = None


class PropertyJsonImportRequest(BaseModel):
    """Bulk JSON property import."""
    source: str = Field(..., description="crm_export, broker_csv, inventory_db, partner_feed, manual")
    records: List[Dict[str, Any]]
    dedupe: bool = True


class ManualUrlImportRequest(BaseModel):
    """Import by manually supplied listing URLs."""
    urls: List[str]
    fetch_details: bool = True


class PropertyImportResponse(BaseModel):
    """Bulk import response."""
    source: str
    received: int
    saved: int
    skipped: int
    errors: List[str] = []


class PropertyResponse(BaseModel):
    """Property response model."""
    id: str
    source: str
    title: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    area: Optional[str] = None
    property_type: Optional[str] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    size_sqft: Optional[int] = None
    images: Optional[List[str]] = None
    video_url: Optional[str] = None
    floor_plan_url: Optional[str] = None
    map_lat: Optional[float] = None
    map_lng: Optional[float] = None
    amenities: Optional[List[str]] = None
    developer: Optional[str] = None
    scraped_at: Optional[datetime] = None
    is_active: bool = True

    model_config = ConfigDict(from_attributes=True)
