"""Database client and repository factories.

Falls back to in-memory mock repositories when Supabase credentials are
missing or unreachable so the API still works in development/demo mode.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.config import get_settings
from app.mock_store import (
    MockActivityRepository,
    MockBrokerRepository,
    MockConversationRepository,
    MockLeadRepository,
    MockPropertyRepository,
    MockWorkspaceRepository,
)

logger = logging.getLogger(__name__)

# Supabase is imported lazily so the app boots even if the SDK is absent
# or the configured URL/key are invalid placeholders.
try:
    from supabase import create_client, Client  # type: ignore
    from postgrest.exceptions import APIError  # type: ignore
    _SUPABASE_AVAILABLE = True
except Exception:  # pragma: no cover - defensive
    create_client = None  # type: ignore
    Client = None  # type: ignore
    APIError = Exception  # type: ignore
    _SUPABASE_AVAILABLE = False


def _use_mock_store() -> bool:
    """Decide whether to bypass Supabase and use the in-memory store."""
    if not _SUPABASE_AVAILABLE:
        return True
    settings = get_settings()
    url = (settings.SUPABASE_URL or "").strip()
    key = (settings.SUPABASE_SERVICE_KEY or settings.SUPABASE_KEY or "").strip()
    if not url or not key:
        return True
    # Real Supabase project URLs include `supabase.co` or `supabase.in`.
    if "supabase.co" not in url and "supabase.in" not in url:
        return True
    # Heuristic: a clearly fake/placeholder key.
    if key.startswith("your-") or "placeholder" in key.lower():
        return True
    return False


class DatabaseClient:
    """Lazy Supabase client wrapper.

    Returns ``None`` when mock mode is active so the dependency layer can
    substitute mock repositories transparently.
    """

    _instance: Optional["Client"] = None

    @classmethod
    def get_client(cls) -> Optional["Client"]:
        if _use_mock_store():
            return None
        if cls._instance is None:
            settings = get_settings()
            try:
                cls._instance = create_client(  # type: ignore[misc]
                    settings.supabase_url,
                    settings.supabase_service_key,
                )
            except Exception as exc:
                logger.warning("Failed to initialize Supabase client: %s", exc)
                return None
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None


def get_db() -> Any:
    """FastAPI dependency. Returns a Supabase client or ``None``."""
    return DatabaseClient.get_client()


def current_workspace_id() -> str:
    """This deployment's single workspace id (see PILOT.md, single-tenant)."""
    return get_settings().WORKSPACE_ID


def _repo(supabase_cls, mock_cls, workspace_id: Optional[str] = None):
    """Return a Supabase-backed repo if a client is available, else the mock.

    ``workspace_id`` stays on the signature so every query remains explicitly
    scoped (and so a future multi-tenant deployment wouldn't need a rewrite),
    but it defaults to this deployment's single workspace rather than being
    resolved from a request header.
    """
    resolved = workspace_id or current_workspace_id()
    client = DatabaseClient.get_client()
    if client is None:
        return mock_cls(resolved)
    return supabase_cls(client, resolved)


def get_lead_repository(workspace_id: Optional[str] = None) -> Any:
    return _repo(LeadRepository, MockLeadRepository, workspace_id)


def get_property_repository(workspace_id: Optional[str] = None) -> Any:
    return _repo(PropertyRepository, MockPropertyRepository, workspace_id)


def get_conversation_repository(workspace_id: Optional[str] = None) -> Any:
    return _repo(ConversationRepository, MockConversationRepository, workspace_id)


def get_broker_repository(workspace_id: Optional[str] = None) -> Any:
    return _repo(BrokerRepository, MockBrokerRepository, workspace_id)


def get_activity_repository(workspace_id: Optional[str] = None) -> Any:
    return _repo(ActivityRepository, MockActivityRepository, workspace_id)


def get_workspace_repository(workspace_id: Optional[str] = None) -> Any:
    return _repo(WorkspaceRepository, MockWorkspaceRepository, workspace_id)


# --- Supabase-backed repositories (used only when a real client is available) ---

class LeadRepository:
    """Repository pattern for the ``leads`` table."""

    def __init__(self, db: "Client", workspace_id: str):
        self.db = db
        self.workspace_id = workspace_id
        self.table = db.table("leads")

    async def create(self, lead_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            result = self.table.insert({**lead_data, "workspace_id": self.workspace_id}).execute()
            return result.data[0] if result.data else None
        except APIError as e:  # pragma: no cover - thin wrapper
            logger.error("Error creating lead: %s", e)
            raise

    async def get_by_id(self, lead_id: str) -> Optional[Dict[str, Any]]:
        result = self.table.select("*").eq("workspace_id", self.workspace_id).eq("id", lead_id).maybe_single().execute()
        return result.data if result.data else None

    async def get_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        result = self.table.select("*").eq("workspace_id", self.workspace_id).eq("phone", phone).maybe_single().execute()
        return result.data if result.data else None

    async def update(self, lead_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        result = self.table.update(updates).eq("workspace_id", self.workspace_id).eq("id", lead_id).execute()
        return result.data[0] if result.data else None

    async def list_by_status(
        self,
        status: str,
        limit: int = 50,
        offset: int = 0,
        assigned_broker_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        query = (
            self.table.select("*")
            .eq("workspace_id", self.workspace_id)
            .eq("status", status)
        )
        if assigned_broker_id:
            query = query.eq("assigned_broker", assigned_broker_id)
        result = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
        return result.data or []

    async def get_unassigned_high_intent(
        self,
        min_score: int = 60,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        result = (
            self.table.select("*")
            .eq("workspace_id", self.workspace_id)
            .is_("assigned_broker", None)
            .gte("intent_score", min_score)
            .order("intent_score", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []

    async def assign_broker(self, lead_id: str, broker_id: str) -> Dict[str, Any]:
        return await self.update(
            lead_id,
            {
                "assigned_broker": broker_id,
                "status": "contacted",
                "updated_at": "now()",
            },
        )


class PropertyRepository:
    """Repository pattern for the ``properties`` table."""

    def __init__(self, db: "Client", workspace_id: str):
        self.db = db
        self.workspace_id = workspace_id
        self.table = db.table("properties")

    async def create(self, property_data: Dict[str, Any]) -> Dict[str, Any]:
        result = self.table.insert({**property_data, "workspace_id": self.workspace_id}).execute()
        return result.data[0] if result.data else None

    async def get_by_source_ref(
        self,
        source: str,
        source_id: Optional[str] = None,
        source_url: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if source_id:
            result = (
                self.table.select("*")
                .eq("workspace_id", self.workspace_id)
                .eq("source", source)
                .eq("source_id", source_id)
                .maybe_single()
                .execute()
            )
            if result.data:
                return result.data
        if source_url:
            result = (
                self.table.select("*")
                .eq("workspace_id", self.workspace_id)
                .eq("source", source)
                .eq("source_url", source_url)
                .maybe_single()
                .execute()
            )
            return result.data if result.data else None
        return None

    async def update(self, property_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        result = self.table.update(updates).eq("workspace_id", self.workspace_id).eq("id", property_id).execute()
        return result.data[0] if result.data else None

    async def search_by_criteria(
        self,
        area: Optional[str] = None,
        property_type: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        bedrooms: Optional[int] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        query = self.table.select("*").eq("workspace_id", self.workspace_id).eq("is_active", True)

        if area:
            query = query.ilike("area", f"%{area}%")
        if property_type:
            query = query.eq("property_type", property_type)
        if min_price is not None:
            query = query.gte("price", min_price)
        if max_price is not None:
            query = query.lte("price", max_price)
        if bedrooms is not None:
            query = query.eq("bedrooms", bedrooms)

        result = query.order("price").limit(limit).execute()
        return result.data or []

    async def get_by_id(self, property_id: str) -> Optional[Dict[str, Any]]:
        result = self.table.select("*").eq("workspace_id", self.workspace_id).eq("id", property_id).maybe_single().execute()
        return result.data if result.data else None


class ConversationRepository:
    """Repository for conversation history."""

    def __init__(self, db: "Client", workspace_id: str):
        self.db = db
        self.workspace_id = workspace_id
        self.table = db.table("conversations")

    async def create(self, conversation_data: Dict[str, Any]) -> Dict[str, Any]:
        result = self.table.insert({**conversation_data, "workspace_id": self.workspace_id}).execute()
        return result.data[0] if result.data else None

    async def get_by_lead(self, lead_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        result = (
            self.table.select("*")
            .eq("workspace_id", self.workspace_id)
            .eq("lead_id", lead_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []

    async def add_message(self, conversation_id: str, message: Dict[str, Any]) -> Dict[str, Any]:
        conv = self.table.select("messages").eq("workspace_id", self.workspace_id).eq("id", conversation_id).maybe_single().execute()
        if not conv.data:
            raise ValueError("Conversation not found")

        messages = conv.data.get("messages", []) or []
        messages.append(message)

        result = self.table.update({"messages": messages}).eq("workspace_id", self.workspace_id).eq("id", conversation_id).execute()
        return result.data[0] if result.data else None


class BrokerRepository:
    """Repository for brokers."""

    def __init__(self, db: "Client", workspace_id: str):
        self.db = db
        self.workspace_id = workspace_id
        self.table = db.table("brokers")

    async def get_available_broker(self, specialization: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        query = (
            self.table.select("*")
            .eq("workspace_id", self.workspace_id)
            .eq("is_active", True)
            .lt("active_leads", "max_leads")
            .order("active_leads")
            .limit(1)
        )

        if specialization:
            query = query.overlaps("specialization", specialization)

        result = query.maybe_single().execute()
        return result.data if result.data else None

    async def increment_lead_count(self, broker_id: str) -> Optional[Dict[str, Any]]:
        broker = await self.get_by_id(broker_id)
        if broker:
            new_count = (broker.get("active_leads", 0) or 0) + 1
            result = self.table.update({"active_leads": new_count}).eq("workspace_id", self.workspace_id).eq("id", broker_id).execute()
            return result.data[0] if result.data else None
        return None

    async def get_by_id(self, broker_id: str) -> Optional[Dict[str, Any]]:
        result = self.table.select("*").eq("workspace_id", self.workspace_id).eq("id", broker_id).maybe_single().execute()
        return result.data if result.data else None


class ActivityRepository:
    """Repository for pipeline activities."""

    def __init__(self, db: "Client", workspace_id: str):
        self.db = db
        self.workspace_id = workspace_id
        self.table = db.table("activities")

    async def create(self, activity_data: Dict[str, Any]) -> Dict[str, Any]:
        result = self.table.insert({**activity_data, "workspace_id": self.workspace_id}).execute()
        return result.data[0] if result.data else None

    async def get_by_lead(self, lead_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        result = (
            self.table.select("*")
            .eq("workspace_id", self.workspace_id)
            .eq("lead_id", lead_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []


class WorkspaceRepository:
    """Repository for the ``workspaces`` table (broker/agency configuration).

    POC scope: this table stores configuration only. Leads/properties are
    not yet filtered by workspace_id anywhere else in the codebase — see
    docs/poc_scope.md for what full multi-tenancy would additionally need.
    """

    def __init__(self, db: "Client", workspace_id: str):
        self.db = db
        self.workspace_id = workspace_id
        self.table = db.table("workspaces")

    async def create(self, workspace_data: Dict[str, Any]) -> Dict[str, Any]:
        result = self.table.insert({**workspace_data, "id": self.workspace_id}).execute()
        return result.data[0] if result.data else None

    async def get_by_id(self, workspace_id: str) -> Optional[Dict[str, Any]]:
        if workspace_id != self.workspace_id:
            return None
        result = self.table.select("*").eq("id", self.workspace_id).maybe_single().execute()
        return result.data if result.data else None

    async def update(self, workspace_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        if workspace_id != self.workspace_id:
            return None
        result = self.table.update(updates).eq("id", self.workspace_id).execute()
        return result.data[0] if result.data else None

    async def list_all(self, limit: int = 50) -> List[Dict[str, Any]]:
        result = (
            self.table.select("*").eq("id", self.workspace_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []
