"""In-memory storage for local development without Supabase."""
from __future__ import annotations

import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.modules.leads.stages import CLOSED_STAGES, lead_stage
from app.services.dashboard import summarize_leads


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


# Seed demo properties
MOCK_PROPERTIES: List[Dict[str, Any]] = [
    {
        "id": "prop-1",
        "source": "demo",
        "title": "Burj Vista Tower 1 - Luxury 2BR",
        "description": "Stunning 2-bedroom apartment in Downtown Dubai with Burj Khalifa views.",
        "price": 3200000,
        "price_per_sqft": 2666,
        "area": "Downtown Dubai",
        "property_type": "apartment",
        "bedrooms": 2,
        "bathrooms": 2,
        "size_sqft": 1200,
        "images": [
            "https://images.unsplash.com/photo-1545324418-cc1a3fa10c00?w=800",
            "https://images.unsplash.com/photo-1502672260266-1c1ef2d93688?w=800",
        ],
        "map_lat": 25.1972,
        "map_lng": 55.2744,
        "amenities": ["Gym", "Pool", "Concierge", "Parking"],
        "developer": "Emaar",
        "is_active": True,
        "scraped_at": _now(),
    },
    {
        "id": "prop-2",
        "source": "demo",
        "title": "Address Boulevard - 3BR Penthouse",
        "description": "Luxury penthouse with private pool and smart home features.",
        "price": 8500000,
        "area": "Downtown Dubai",
        "property_type": "penthouse",
        "bedrooms": 3,
        "bathrooms": 3,
        "size_sqft": 2500,
        "images": ["https://images.unsplash.com/photo-1512917774080-9991f1c4c750?w=800"],
        "map_lat": 25.2048,
        "map_lng": 55.2708,
        "amenities": ["Private Pool", "Smart Home", "Valet", "Spa"],
        "developer": "Emaar",
        "is_active": True,
        "scraped_at": _now(),
    },
    {
        "id": "prop-3",
        "source": "demo",
        "title": "Marina Gate - Sea View 1BR",
        "description": "Modern 1-bedroom with full marina and sea views.",
        "price": 1800000,
        "area": "Dubai Marina",
        "property_type": "apartment",
        "bedrooms": 1,
        "bathrooms": 1,
        "size_sqft": 800,
        "images": ["https://images.unsplash.com/photo-1522708323590-d24dbb6b0267?w=800"],
        "map_lat": 25.0895,
        "map_lng": 55.1515,
        "amenities": ["Beach Access", "Gym", "Parking"],
        "developer": "Select Group",
        "is_active": True,
        "scraped_at": _now(),
    },
]

MOCK_BROKERS: List[Dict[str, Any]] = [
    {
        "id": "broker-1",
        "name": "Sarah Al-Maktoum",
        "email": "sarah@dubairealestate.ai",
        "phone": "+971501234567",
        "specialization": ["Downtown Dubai", "Business Bay"],
        "is_active": True,
        "active_leads": 2,
        "max_leads": 10,
    },
    {
        "id": "broker-2",
        "name": "Ahmed Hassan",
        "email": "ahmed@dubairealestate.ai",
        "phone": "+971509876543",
        "specialization": ["Dubai Marina", "Palm Jumeirah"],
        "is_active": True,
        "active_leads": 1,
        "max_leads": 10,
    },
]

_leads: Dict[str, Dict[str, Any]] = {}
_properties: Dict[str, Dict[str, Any]] = {}
_conversations: Dict[str, Dict[str, Any]] = {}
_activities: Dict[str, Dict[str, Any]] = {}
_workspaces: Dict[str, Dict[str, Any]] = {}


def load_seed_data() -> Dict[str, int]:
    """Populate the in-memory store from ``app.seed_data``.

    This is what makes mock mode a usable product demo rather than an empty
    shell: leads spread across pipeline stages, a listing book with a
    realistic proportion already stale, and brokers to assign to. Called at
    import so every repository sees the same world, and re-callable from the
    seed script to reset a demo between walkthroughs.
    """
    from app.config import get_settings
    from app.seed_data import mock_leads, mock_property_records

    workspace_id = get_settings().WORKSPACE_ID

    _properties.clear()
    for record in mock_property_records():
        record = deepcopy(record)
        record["workspace_id"] = workspace_id
        _properties[record["id"]] = record
    # Keep the original hand-written demo listings too — they have recognisable
    # Dubai landmark names that read well in a screenshot.
    for record in MOCK_PROPERTIES:
        record = deepcopy(record)
        record["workspace_id"] = workspace_id
        record.setdefault("last_refreshed_at", record.get("scraped_at"))
        _properties[record["id"]] = record

    _leads.clear()
    for record in mock_leads():
        record = deepcopy(record)
        record["workspace_id"] = workspace_id
        _leads[record["id"]] = record

    return {"properties": len(_properties), "leads": len(_leads)}


def load_scale_data(scale: int, tables: Dict[str, List[Dict[str, Any]]]) -> Dict[str, int]:
    """Add ``scale`` generated leads and listings, plus handoffs/viewings/follow-ups
    into ``tables`` (the generic in-memory tables). Mock mode only; called from the
    app lifespan once ``DEMO_SEED_SCALE`` is set. Idempotent per process."""
    from app.config import get_settings
    from app.demo_scale import scale_leads, scale_properties, scale_related

    workspace_id = get_settings().WORKSPACE_ID
    for record in scale_properties(max(50, scale // 4)):
        record["workspace_id"] = workspace_id
        _properties[record["id"]] = record

    generated = list(scale_leads(scale))
    for record in generated:
        record["workspace_id"] = workspace_id
        _leads[record["id"]] = record

    related = scale_related(generated)
    for name, rows in related.items():
        existing = tables[name]
        existing[:] = [r for r in existing if not str(r.get("id", "")).startswith("scale-")]
        for row in rows:
            row["workspace_id"] = workspace_id
        existing.extend(rows)

    return {"properties": len(_properties), "leads": len(_leads), **{k: len(v) for k, v in related.items()}}


load_seed_data()


class MockLeadRepository:
    """In-memory lead storage."""

    def __init__(self, workspace_id: str):
        self.workspace_id = workspace_id

    async def create(self, lead_data: Dict[str, Any]) -> Dict[str, Any]:
        lead_id = _new_id()
        record = {
            **lead_data,
            "id": lead_id,
            "workspace_id": self.workspace_id,
            "intent_score": lead_data.get("intent_score", 0),
            "status": lead_data.get("status", "new"),
            "conversation_history": lead_data.get("conversation_history", []),
            "created_at": _now(),
            "updated_at": _now(),
        }
        _leads[lead_id] = record
        return deepcopy(record)

    async def get_by_id(self, lead_id: str) -> Optional[Dict[str, Any]]:
        lead = _leads.get(lead_id)
        if not lead or lead.get("workspace_id") != self.workspace_id:
            return None
        return deepcopy(lead)

    async def get_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        for lead in _leads.values():
            if lead.get("workspace_id") == self.workspace_id and lead.get("phone") == phone:
                return deepcopy(lead)
        return None

    async def get_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        wanted = email.strip().lower()
        for lead in _leads.values():
            if lead.get("workspace_id") == self.workspace_id and (lead.get("email") or "").lower() == wanted:
                return deepcopy(lead)
        return None

    def _mine(self, assigned_broker_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return [
            l for l in _leads.values()
            if l.get("workspace_id") == self.workspace_id
            and (assigned_broker_id is None or l.get("assigned_broker") == assigned_broker_id)
        ]

    async def list_all(self, limit: int = 200, offset: int = 0, assigned_broker_id: Optional[str] = None) -> List[Dict[str, Any]]:
        items = self._mine(assigned_broker_id)
        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return [deepcopy(l) for l in items[offset : offset + limit]]

    async def list_hot(self, min_score: int = 70, limit: int = 50, assigned_broker_id: Optional[str] = None) -> List[Dict[str, Any]]:
        items = [
            l for l in self._mine(assigned_broker_id)
            if (l.get("band") == "hot" or (l.get("intent_score") or 0) >= min_score)
            and lead_stage(l) not in CLOSED_STAGES
        ]
        items.sort(key=lambda x: (-(x.get("score") or x.get("intent_score") or 0), x.get("created_at", "")), reverse=False)
        return [deepcopy(l) for l in items[:limit]]

    async def count_by_stage(self, assigned_broker_id: Optional[str] = None) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for l in self._mine(assigned_broker_id):
            stage = lead_stage(l)
            counts[stage] = counts.get(stage, 0) + 1
        return counts

    async def summary(self, assigned_broker_id: Optional[str] = None) -> Dict[str, Any]:
        return summarize_leads(self._mine(assigned_broker_id))

    async def update(self, lead_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        if lead_id not in _leads or _leads[lead_id].get("workspace_id") != self.workspace_id:
            raise ValueError(f"Lead {lead_id} not found")
        _leads[lead_id].update(updates)
        _leads[lead_id]["updated_at"] = _now()
        return deepcopy(_leads[lead_id])

    async def list_by_status(
        self,
        status: str,
        limit: int = 50,
        offset: int = 0,
        assigned_broker_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        items = [
            l for l in _leads.values()
            if l.get("workspace_id") == self.workspace_id and l.get("status") == status
        ]
        if assigned_broker_id:
            items = [l for l in items if l.get("assigned_broker") == assigned_broker_id]
        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return [deepcopy(l) for l in items[offset : offset + limit]]

    async def get_unassigned_high_intent(
        self, min_score: int = 60, limit: int = 10
    ) -> List[Dict[str, Any]]:
        items = [
            l
            for l in _leads.values()
            if l.get("workspace_id") == self.workspace_id
            and not l.get("assigned_broker")
            and l.get("intent_score", 0) >= min_score
        ]
        items.sort(key=lambda x: x.get("intent_score", 0), reverse=True)
        return [deepcopy(l) for l in items[:limit]]

    async def assign_broker(self, lead_id: str, broker_id: str) -> Dict[str, Any]:
        return await self.update(
            lead_id, {"assigned_broker": broker_id, "status": "contacted"}
        )


class MockPropertyRepository:
    """In-memory property storage."""

    def __init__(self, workspace_id: str):
        self.workspace_id = workspace_id

    async def create(self, property_data: Dict[str, Any]) -> Dict[str, Any]:
        prop_id = property_data.get("id") or _new_id()
        record = {
            **property_data,
            "id": prop_id,
            "workspace_id": self.workspace_id,
            "is_active": True,
            "scraped_at": _now(),
        }
        _properties[prop_id] = record
        return deepcopy(record)

    async def get_by_source_ref(
        self,
        source: str,
        source_id: Optional[str] = None,
        source_url: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        for prop in _properties.values():
            if prop.get("workspace_id") != self.workspace_id or prop.get("source") != source:
                continue
            if source_id and prop.get("source_id") == source_id:
                return deepcopy(prop)
            if source_url and prop.get("source_url") == source_url:
                return deepcopy(prop)
        return None

    async def update(self, property_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        if (
            property_id not in _properties
            or _properties[property_id].get("workspace_id") != self.workspace_id
        ):
            raise ValueError(f"Property {property_id} not found")
        _properties[property_id].update(updates)
        return deepcopy(_properties[property_id])

    async def search_by_criteria(
        self,
        area: Optional[str] = None,
        property_type: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        bedrooms: Optional[int] = None,
        limit: int = 10,
        listing_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        results = [
            p for p in _properties.values()
            if p.get("workspace_id") == self.workspace_id and p.get("is_active", True)
        ]
        if area:
            results = [p for p in results if area.lower() in (p.get("area") or "").lower()]
        if property_type:
            results = [p for p in results if p.get("property_type") == property_type]
        if min_price is not None:
            results = [p for p in results if (p.get("price") or 0) >= min_price]
        if max_price is not None:
            results = [p for p in results if (p.get("price") or 0) <= max_price]
        if bedrooms is not None:
            results = [p for p in results if p.get("bedrooms") == bedrooms]
        if listing_type:
            results = [p for p in results if (p.get("listing_type") or listing_type) == listing_type]
        if max_price is not None:
            results.sort(key=lambda x: abs((x.get("price") or 0) - max_price))
        else:
            results.sort(key=lambda x: x.get("price") or 0)
        return [deepcopy(p) for p in results[:limit]]

    async def get_by_id(self, property_id: str) -> Optional[Dict[str, Any]]:
        prop = _properties.get(property_id)
        if not prop or prop.get("workspace_id") != self.workspace_id:
            return None
        return deepcopy(prop)


class MockConversationRepository:
    """In-memory conversation storage."""

    def __init__(self, workspace_id: str):
        self.workspace_id = workspace_id

    async def create(self, conversation_data: Dict[str, Any]) -> Dict[str, Any]:
        conv_id = _new_id()
        record = {**conversation_data, "id": conv_id, "workspace_id": self.workspace_id, "created_at": _now()}
        _conversations[conv_id] = record
        return deepcopy(record)

    async def get_by_lead(self, lead_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        items = [c for c in _conversations.values() if c.get("workspace_id") == self.workspace_id and c.get("lead_id") == lead_id]
        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return [deepcopy(c) for c in items[:limit]]

    async def add_message(self, conversation_id: str, message: Dict[str, Any]) -> Dict[str, Any]:
        if conversation_id not in _conversations or _conversations[conversation_id].get("workspace_id") != self.workspace_id:
            raise ValueError("Conversation not found")
        messages = _conversations[conversation_id].get("messages", []) or []
        messages.append(message)
        _conversations[conversation_id]["messages"] = messages
        return deepcopy(_conversations[conversation_id])


class MockBrokerRepository:
    """In-memory broker storage."""

    def __init__(self, workspace_id: str):
        self.workspace_id = workspace_id
        self.brokers = [
            {**deepcopy(broker), "workspace_id": workspace_id}
            for broker in MOCK_BROKERS
        ]

    async def get_available_broker(
        self, specialization: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        for broker in self.brokers:
            if not broker.get("is_active"):
                continue
            if broker.get("active_leads", 0) >= broker.get("max_leads", 10):
                continue
            if specialization:
                if not set(specialization) & set(broker.get("specialization", [])):
                    continue
            return deepcopy(broker)
        return None

    async def increment_lead_count(self, broker_id: str) -> Optional[Dict[str, Any]]:
        for broker in self.brokers:
            if broker["id"] == broker_id:
                broker["active_leads"] = (broker.get("active_leads", 0) or 0) + 1
                return deepcopy(broker)
        return None

    async def get_by_id(self, broker_id: str) -> Optional[Dict[str, Any]]:
        for broker in self.brokers:
            if broker["id"] == broker_id:
                return deepcopy(broker)
        return None


class MockActivityRepository:
    """In-memory activity storage."""

    def __init__(self, workspace_id: str):
        self.workspace_id = workspace_id

    async def create(self, activity_data: Dict[str, Any]) -> Dict[str, Any]:
        activity_id = _new_id()
        record = {**activity_data, "id": activity_id, "workspace_id": self.workspace_id, "created_at": _now()}
        _activities[activity_id] = record
        return deepcopy(record)

    async def get_by_lead(self, lead_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        items = [a for a in _activities.values() if a.get("workspace_id") == self.workspace_id and a.get("lead_id") == lead_id]
        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return [deepcopy(a) for a in items[:limit]]


class MockWorkspaceRepository:
    """In-memory workspace (broker/agency configuration) storage.

    Backs the /configure workflow builder for the POC. See
    app/models/workspace.py for the shape of a workspace record.
    """

    async def create(self, workspace_data: Dict[str, Any]) -> Dict[str, Any]:
        workspace_id = self.workspace_id
        record = {
            **workspace_data,
            "id": workspace_id,
            "status": workspace_data.get("status", "draft"),
            "created_at": _now(),
            "updated_at": _now(),
        }
        _workspaces[workspace_id] = record
        return deepcopy(record)

    async def get_by_id(self, workspace_id: str) -> Optional[Dict[str, Any]]:
        if workspace_id != self.workspace_id:
            return None
        record = _workspaces.get(workspace_id)
        return deepcopy(record) if record else None

    async def update(self, workspace_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        if workspace_id != self.workspace_id:
            raise ValueError("Workspace not found")
        if workspace_id not in _workspaces:
            raise ValueError(f"Workspace {workspace_id} not found")
        _workspaces[workspace_id].update(updates)
        _workspaces[workspace_id]["updated_at"] = _now()
        return deepcopy(_workspaces[workspace_id])

    async def list_all(self, limit: int = 50) -> List[Dict[str, Any]]:
        items = [w for w in _workspaces.values() if w.get("id") == self.workspace_id]
        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return [deepcopy(w) for w in items[:limit]]
    def __init__(self, workspace_id: str):
        self.workspace_id = workspace_id
