"""Utility helpers for the backend."""
import re
import json
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta


def parse_price_string(price_str: str) -> Optional[float]:
    """Extract numeric price from various string formats.

    Examples:
        "AED 3,200,000" -> 3200000.0
        "3.2M AED" -> 3200000.0
        "1,850,000" -> 1850000.0
    """
    if not price_str:
        return None

    text = str(price_str).upper().replace(",", "").replace("AED", "").strip()

    # Handle "M" for millions
    if "M" in text:
        match = re.search(r'(\d+\.?\d*)\s*M', text)
        if match:
            return float(match.group(1)) * 1_000_000

    # Handle "K" for thousands
    if "K" in text:
        match = re.search(r'(\d+\.?\d*)\s*K', text)
        if match:
            return float(match.group(1)) * 1_000

    # Extract any number
    numbers = re.findall(r'\d+\.?\d*', text)
    if numbers:
        return float(numbers[0])

    return None


def format_price_aed(price: float) -> str:
    """Format price in AED with commas."""
    if price >= 1_000_000:
        return f"AED {price/1_000_000:.1f}M"
    elif price >= 1_000:
        return f"AED {price:,.0f}"
    return f"AED {price}"


def detect_language(text: str) -> str:
    """Detect if text is Arabic or English."""
    # Check for Arabic Unicode range
    arabic_pattern = re.compile(r'[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]')
    if arabic_pattern.search(text):
        return "ar"
    return "en"


def truncate_text(text: str, max_length: int = 200) -> str:
    """Truncate text with ellipsis."""
    if len(text) <= max_length:
        return text
    return text[:max_length].rsplit(" ", 1)[0] + "..."


def generate_lead_id() -> str:
    """Generate a unique lead ID."""
    import uuid
    return f"lead_{uuid.uuid4().hex[:12]}"


def calculate_intent_score(lead_data: Dict[str, Any]) -> int:
    """Calculate intent score based on lead data completeness.

    Scoring criteria:
    - Has phone: +20
    - Has email: +10
    - Has budget: +25
    - Has area preference: +20
    - Has timeline (not 'just_browsing'): +15
    - Has property type: +10
    """
    score = 0

    if lead_data.get("phone"):
        score += 20
    if lead_data.get("email"):
        score += 10
    if lead_data.get("budget_min") or lead_data.get("budget_max"):
        score += 25
    if lead_data.get("area_preference"):
        score += 20
    if lead_data.get("timeline") and lead_data.get("timeline") != "just_browsing":
        score += 15
    if lead_data.get("property_type"):
        score += 10

    return min(100, score)


def get_nurture_schedule(lead_created_at: datetime) -> List[Dict[str, Any]]:
    """Generate nurture email schedule for a lead.

    Returns list of scheduled touchpoints:
    - Day 1: Welcome
    - Day 3: Property recommendations
    - Day 7: Site visit invitation
    - Day 14: Market update
    - Day 30: Re-engagement
    """
    schedule = []

    touchpoints = [
        (1, "welcome", "Welcome to Dubai Real Estate AI"),
        (3, "recommendations", "Properties matching your search"),
        (7, "site_visit", "Schedule your site visit"),
        (14, "market_update", "Dubai market update"),
        (30, "reengagement", "Still searching?"),
    ]

    for days, type_, subject in touchpoints:
        scheduled_time = lead_created_at + timedelta(days=days)
        schedule.append({
            "day": days,
            "type": type_,
            "subject": subject,
            "scheduled_at": scheduled_time.isoformat(),
            "sent": False,
        })

    return schedule


def sanitize_phone(phone: str) -> str:
    """Sanitize phone number to international format."""
    if not phone:
        return ""

    # Remove all non-numeric characters
    digits = re.sub(r'\D', '', phone)

    # Add UAE country code if missing
    if digits.startswith("971"):
        return "+" + digits
    elif digits.startswith("0"):
        return "+971" + digits[1:]
    elif len(digits) == 9:
        return "+971" + digits

    return "+" + digits if not digits.startswith("+") else digits


def extract_area_from_text(text: str) -> Optional[str]:
    """Extract Dubai area name from free text."""
    dubai_areas = [
        "downtown dubai", "dubai marina", "palm jumeirah", "business bay",
        "jumeirah", "jbr", "jlt", "dubai hills", "arabian ranches",
        "emirates hills", "damac hills", "meydan", "city walk",
        "bluewaters", "dubai creek harbour", "al barsha", "tecom",
    ]

    text_lower = text.lower()
    for area in dubai_areas:
        if area in text_lower:
            return area.title()

    return None


def create_broker_brief(lead: Dict[str, Any], properties: List[Dict[str, Any]]) -> str:
    """Create a formatted brief for broker handoff."""
    brief = f"""
╔══════════════════════════════════════════════════════════════╗
║                 BROKER HANDOFF BRIEF                         ║
╠══════════════════════════════════════════════════════════════╣
  Lead: {lead.get('first_name', '')} {lead.get('last_name', '')}
  Phone: {lead.get('phone', 'N/A')}
  Email: {lead.get('email', 'N/A')}
  Language: {lead.get('preferred_language', 'en').upper()}
  Intent Score: {lead.get('intent_score', 0)}/100
╠══════════════════════════════════════════════════════════════╣
  QUALIFICATION:
  • Budget: AED {lead.get('budget_min', 'N/A')} - {lead.get('budget_max', 'N/A')}
  • Property Type: {lead.get('property_type', 'Not specified')}
  • Area: {', '.join(lead.get('area_preference', [])) or 'Not specified'}
  • Timeline: {lead.get('timeline', 'Not specified')}
╠══════════════════════════════════════════════════════════════╣
  TOP MATCHING PROPERTIES:
"""

    for i, prop in enumerate(properties[:3], 1):
        brief += f"""
  {i}. {prop.get('title', 'Unknown')}
     Area: {prop.get('area', 'N/A')} | Price: AED {prop.get('price', 'N/A'):,}
     Match Score: {prop.get('match_score', 'N/A')}%
"""

    brief += """
╠══════════════════════════════════════════════════════════════╣
  CONVERSATION SUMMARY:
  [See full conversation in CRM]
╚══════════════════════════════════════════════════════════════╝
"""
    return brief


def chunk_list(lst: List[Any], chunk_size: int) -> List[List[Any]]:
    """Split list into chunks."""
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]


def safe_json_loads(text: str, default: Any = None) -> Any:
    """Safely parse JSON, return default on failure."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default
