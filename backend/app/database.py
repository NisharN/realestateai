"""Supabase database client and utilities."""
from supabase import create_client, Client
from postgrest.exceptions import APIError
from typing import Optional, Dict, Any, List
import logging

from app.config import get_settings

logger = logging.getLogger(__name__)


class DatabaseClient:
    """Singleton Supabase client wrapper."""

    _instance: Optional[Client] = None

    @classmethod
    def get_client(cls) -> Client:
        if cls._instance is None:
            settings = get_settings()
            cls._instance = create_client(
                settings.supabase_url,
                settings.supabase_service_key
            )
        return cls._instance

    @classmethod
    def reset(cls):
        cls._instance = None


def get_db() -> Client:
    """FastAPI dependency to get database client."""
    return DatabaseClient.get_client()


class LeadRepository:
    """Repository pattern for leads table."""

    def __init__(self, db: Client):
        self.db = db
        self.table = db.table("leads")

    async def create(self, lead_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new lead."""
        try:
            result = self.table.insert(lead_data).execute()
            return result.data[0] if result.data else None
        except APIError as e:
            logger.error(f"Error creating lead: {e}")
            raise

    async def get_by_id(self, lead_id: str) -> Optional[Dict[str, Any]]:
        """Get lead by ID."""
        result = self.table.select("*").eq("id", lead_id).single().execute()
        return result.data if result.data else None

    async def get_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        """Get lead by phone number."""
        result = self.table.select("*").eq("phone", phone).maybe_single().execute()
        return result.data if result.data else None

    async def update(self, lead_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update lead fields."""
        result = self.table.update(updates).eq("id", lead_id).execute()
        return result.data[0] if result.data else None

    async def list_by_status(
        self, 
        status: str, 
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """List leads by status with pagination."""
        result = (self.table.select("*")
                 .eq("status", status)
                 .order("created_at", desc=True)
                 .range(offset, offset + limit - 1)
                 .execute())
        return result.data or []

    async def get_unassigned_high_intent(
        self, 
        min_score: int = 60,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get high-intent leads not yet assigned to a broker."""
        result = (self.table.select("*")
                 .is_("assigned_broker", None)
                 .gte("intent_score", min_score)
                 .order("intent_score", desc=True)
                 .limit(limit)
                 .execute())
        return result.data or []

    async def assign_broker(self, lead_id: str, broker_id: str) -> Dict[str, Any]:
        """Assign lead to broker."""
        return await self.update(lead_id, {
            "assigned_broker": broker_id,
            "status": "contacted",
            "updated_at": "now()"
        })


class PropertyRepository:
    """Repository pattern for properties table."""

    def __init__(self, db: Client):
        self.db = db
        self.table = db.table("properties")

    async def create(self, property_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new property listing."""
        result = self.table.insert(property_data).execute()
        return result.data[0] if result.data else None

    async def search_by_criteria(
        self,
        area: Optional[str] = None,
        property_type: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        bedrooms: Optional[int] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Search properties by criteria."""
        query = self.table.select("*").eq("is_active", True)

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
        """Get property by ID."""
        result = self.table.select("*").eq("id", property_id).single().execute()
        return result.data if result.data else None


class ConversationRepository:
    """Repository for conversation history."""

    def __init__(self, db: Client):
        self.db = db
        self.table = db.table("conversations")

    async def create(self, conversation_data: Dict[str, Any]) -> Dict[str, Any]:
        result = self.table.insert(conversation_data).execute()
        return result.data[0] if result.data else None

    async def get_by_lead(self, lead_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        result = (self.table.select("*")
                 .eq("lead_id", lead_id)
                 .order("created_at", desc=True)
                 .limit(limit)
                 .execute())
        return result.data or []

    async def add_message(self, conversation_id: str, message: Dict[str, Any]) -> Dict[str, Any]:
        """Append message to existing conversation."""
        # Get existing messages
        conv = self.table.select("messages").eq("id", conversation_id).single().execute()
        if not conv.data:
            raise ValueError("Conversation not found")

        messages = conv.data.get("messages", []) or []
        messages.append(message)

        result = self.table.update({"messages": messages}).eq("id", conversation_id).execute()
        return result.data[0] if result.data else None


class BrokerRepository:
    """Repository for brokers."""

    def __init__(self, db: Client):
        self.db = db
        self.table = db.table("brokers")

    async def get_available_broker(self, specialization: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        """Get broker with capacity."""
        query = (self.table.select("*")
                .eq("is_active", True)
                .lt("active_leads", "max_leads")
                .order("active_leads")
                .limit(1))

        if specialization:
            # Simple overlap check - in production use proper array overlap
            query = query.overlaps("specialization", specialization)

        result = query.maybe_single().execute()
        return result.data if result.data else None

    async def increment_lead_count(self, broker_id: str) -> Dict[str, Any]:
        broker = await self.get_by_id(broker_id)
        if broker:
            new_count = (broker.get("active_leads", 0) or 0) + 1
            result = self.table.update({"active_leads": new_count}).eq("id", broker_id).execute()
            return result.data[0] if result.data else None
        return None

    async def get_by_id(self, broker_id: str) -> Optional[Dict[str, Any]]:
        result = self.table.select("*").eq("id", broker_id).single().execute()
        return result.data if result.data else None


class ActivityRepository:
    """Repository for pipeline activities."""

    def __init__(self, db: Client):
        self.db = db
        self.table = db.table("activities")

    async def create(self, activity_data: Dict[str, Any]) -> Dict[str, Any]:
        result = self.table.insert(activity_data).execute()
        return result.data[0] if result.data else None

    async def get_by_lead(self, lead_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        result = (self.table.select("*")
                 .eq("lead_id", lead_id)
                 .order("created_at", desc=True)
                 .limit(limit)
                 .execute())
        return result.data or []
