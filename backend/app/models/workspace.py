"""Workspace configuration models.

A ``Workspace`` is one broker/agency's configuration of this product: their
team roster, which data sources feed their property inventory, and which
channels (WhatsApp, languages) their leads reach them through. This is the
POC's "light FDE" concept — instead of an engineer hand-configuring a new
deployment per customer, a workspace is set up through the /configure
wizard in the frontend and stored here.

POC scope note: a Workspace record is real and persisted, but it does not
yet scope leads/properties/conversations by workspace_id — those remain a
single shared pool. See docs/poc_scope.md for what "real multi-tenancy"
would require on top of this.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class TeamMember(BaseModel):
    """One broker or agent on a workspace's roster."""
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    role: str = "agent"  # "agent" | "broker" | "team_lead"
    languages: List[str] = Field(default_factory=lambda: ["en"])
    specialization: List[str] = Field(default_factory=list)  # e.g. ["Downtown Dubai"]
    max_leads: int = 20


class DataSourceConfig(BaseModel):
    """One data source toggled on/off for a workspace's property inventory."""
    source: str  # "broker_csv" | "crm_export" | "approved_feed" | "rapidapi_uae" | "propertyfinder"
    enabled: bool = False
    status: str = "not_configured"  # "not_configured" | "testing" | "connected" | "error"
    last_tested_at: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


class ChannelConfig(BaseModel):
    """Channel/language settings for a workspace."""
    whatsapp_number: Optional[str] = None
    whatsapp_connected: bool = False  # POC: always false — no real WhatsApp send
    languages: List[str] = Field(default_factory=lambda: ["en", "ar"])
    web_widget_enabled: bool = True


class WorkspaceCreate(BaseModel):
    """Request body to create a new workspace."""
    name: str
    team: List[TeamMember] = Field(default_factory=list)
    data_sources: List[DataSourceConfig] = Field(default_factory=list)
    channels: ChannelConfig = Field(default_factory=ChannelConfig)


class WorkspaceUpdate(BaseModel):
    """Partial update to an existing workspace."""
    name: Optional[str] = None
    team: Optional[List[TeamMember]] = None
    data_sources: Optional[List[DataSourceConfig]] = None
    channels: Optional[ChannelConfig] = None
    status: Optional[str] = None  # "draft" | "live"


class WorkspaceResponse(BaseModel):
    """Workspace as returned by the API."""
    id: str
    name: str
    team: List[TeamMember] = Field(default_factory=list)
    data_sources: List[DataSourceConfig] = Field(default_factory=list)
    channels: ChannelConfig = Field(default_factory=ChannelConfig)
    status: str = "draft"  # "draft" | "live"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class DataSourceTestResult(BaseModel):
    """Result of a "test this data source" call from the workflow builder."""
    source: str
    ok: bool
    message: str
    sample_count: int = 0
