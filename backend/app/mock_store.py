"""In-memory storage for local development without Supabase."""
from __future__ import annotations

import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


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
_properties: Dict[str, Dict[str, Any]] = {p["id"]: deepcopy(p) for p in MOCK_PROPERTIES}
_conversations: Dict[str, Dict[str, Any]] = {}
_activities: Dict[str, Dict[str, Any]] = {}


class MockLeadRepository:
    """In-memory lead storage."""

    async def create(self, lead_data: Dict[str, Any]) -> Dict[str, Any]:
        lead_id = _new_id()
        record = {
            **lead_data,
            "id": lead_id,
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
        return deepcopy(lead) if lead else None

    async def get_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        for lead in _leads.values():
            if lead.get("phone") == phone:
                return deepcopy(lead)
        return None

    async def update(self, lead_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        if lead_id not in _leads:
            raise ValueError(f"Lead {lead_id} not found")
        _leads[lead_id].update(updates)
        _leads[lead_id]["updated_at"] = _now()
        return deepcopy(_leads[lead_id])

    async def list_by_status(
        self, status: str, limit: int = 50, offset: int = 0
    ) -> List[Dict[str, Any]]:
        items = [l for l in _leads.values() if l.get("status") == status]
        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return [deepcopy(l) for l in items[offset : offset + limit]]

    async def get_unassigned_high_intent(
        self, min_score: int = 60, limit: int = 10
    ) -> List[Dict[str, Any]]:
        items = [
            l
            for l in _leads.values()
            if not l.get("assigned_broker") and l.get("intent_score", 0) >= min_score
        ]
        items.sort(key=lambda x: x.get("intent_score", 0), reverse=True)
        return [deepcopy(l) for l in items[:limit]]

    async def assign_broker(self, lead_id: str, broker_id: str) -> Dict[str, Any]:
        return await self.update(
            lead_id, {"assigned_broker": broker_id, "status": "contacted"}
        )


class MockPropertyRepository:
    """In-memory property storage."""

    async def create(self, property_data: Dict[str, Any]) -> Dict[str, Any]:
        prop_id = property_data.get("id") or _new_id()
        record = {**property_data, "id": prop_id, "is_active": True, "scraped_at": _now()}
        _properties[prop_id] = record
        return deepcopy(record)

    async def search_by_criteria(
        self,
        area: Optional[str] = None,
        property_type: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        bedrooms: Optional[int] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        results = [p for p in _properties.values() if p.get("is_active", True)]
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
        results.sort(key=lambda x: x.get("price") or 0)
        return [deepcopy(p) for p in results[:limit]]

    async def get_by_id(self, property_id: str) -> Optional[Dict[str, Any]]:
        prop = _properties.get(property_id)
        return deepcopy(prop) if prop else None


class MockConversationRepository:
    """In-memory conversation storage."""

    async def create(self, conversation_data: Dict[str, Any]) -> Dict[str, Any]:
        conv_id = _new_id()
        record = {**conversation_data, "id": conv_id, "created_at": _now()}
        _conversations[conv_id] = record
        return deepcopy(record)

    async def get_by_lead(self, lead_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        items = [c for c in _conversations.values() if c.get("lead_id") == lead_id]
        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return [deepcopy(c) for c in items[:limit]]

    async def add_message(self, conversation_id: str, message: Dict[str, Any]) -> Dict[str, Any]:
        if conversation_id not in _conversations:
            raise ValueError("Conversation not found")
        messages = _conversations[conversation_id].get("messages", []) or []
        messages.append(message)
        _conversations[conversation_id]["messages"] = messages
        return deepcopy(_conversations[conversation_id])


class MockBrokerRepository:
    """In-memory broker storage."""

    async def get_available_broker(
        self, specialization: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        for broker in MOCK_BROKERS:
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
        for broker in MOCK_BROKERS:
            if broker["id"] == broker_id:
                broker["active_leads"] = (broker.get("active_leads", 0) or 0) + 1
                return deepcopy(broker)
        return None

    async def get_by_id(self, broker_id: str) -> Optional[Dict[str, Any]]:
        for broker in MOCK_BROKERS:
            if broker["id"] == broker_id:
                return deepcopy(broker)
        return None


class MockActivityRepository:
    """In-memory activity storage."""

    async def create(self, activity_data: Dict[str, Any]) -> Dict[str, Any]:
        activity_id = _new_id()
        record = {**activity_data, "id": activity_id, "created_at": _now()}
        _activities[activity_id] = record
        return deepcopy(record)

    async def get_by_lead(self, lead_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        items = [a for a in _activities.values() if a.get("lead_id") == lead_id]
        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return [deepcopy(a) for a in items[:limit]]
