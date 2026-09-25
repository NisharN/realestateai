"""Deterministic broker routing: language → area → capacity → rotation (§9.2)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.modules.geo.communities import resolve_area

DUBAI = ZoneInfo("Asia/Dubai")


@dataclass
class BrokerProfile:
    id: str
    name: str
    phone: str | None = None
    languages: list[str] = field(default_factory=lambda: ["en"])
    community_ids: list[str] = field(default_factory=list)
    active_leads: int = 0
    max_leads: int = 10
    is_active: bool = True
    shift_start: time | None = None  # Dubai local time; None = always on shift
    shift_end: time | None = None
    last_assigned_at: datetime | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "BrokerProfile":
        communities: list[str] = list(row.get("community_ids") or [])
        for spec in row.get("specialization") or []:
            for m in resolve_area(str(spec)):
                if m.confidence >= 0.8 and m.community.id not in communities:
                    communities.append(m.community.id)
        last = row.get("last_assigned_at")
        return cls(
            id=str(row["id"]),
            name=row.get("name") or "Specialist",
            phone=row.get("phone"),
            languages=list(row.get("languages") or ["en"]),
            community_ids=communities,
            active_leads=int(row.get("active_leads") or 0),
            max_leads=int(row.get("max_leads") or 10),
            is_active=bool(row.get("is_active", True)),
            shift_start=_parse_time(row.get("shift_start")),
            shift_end=_parse_time(row.get("shift_end")),
            last_assigned_at=datetime.fromisoformat(last) if isinstance(last, str) else last,
        )

    def on_shift(self, now: datetime) -> bool:
        if self.shift_start is None or self.shift_end is None:
            return True
        local = now.astimezone(DUBAI).time()
        if self.shift_start <= self.shift_end:
            return self.shift_start <= local <= self.shift_end
        return local >= self.shift_start or local <= self.shift_end

    def has_capacity(self) -> bool:
        return self.is_active and self.active_leads < self.max_leads


def _parse_time(value: Any) -> time | None:
    if value is None or value == "":
        return None
    if isinstance(value, time):
        return value
    try:
        return time.fromisoformat(str(value))
    except ValueError:
        return None


@dataclass(frozen=True)
class RoutingDecision:
    broker: BrokerProfile | None
    reasons: list[str]


def route(
    brokers: list[BrokerProfile],
    *,
    language: str,
    community_ids: list[str],
    now: datetime | None = None,
    exclude_ids: set[str] | None = None,
) -> RoutingDecision:
    now = now or datetime.now(timezone.utc)
    exclude = exclude_ids or set()
    reasons: list[str] = []

    pool = [b for b in brokers if b.has_capacity() and b.id not in exclude]
    if not pool:
        return RoutingDecision(None, ["no broker with capacity"])
    reasons.append(f"{len(pool)} brokers with capacity")

    on_shift = [b for b in pool if b.on_shift(now)]
    if on_shift:
        pool = on_shift
        reasons.append("filtered to brokers on shift")
    else:
        reasons.append("nobody on shift; using full pool")

    lang_match = [b for b in pool if language in b.languages]
    if lang_match:
        pool = lang_match
        reasons.append(f"speaks {language}")
    else:
        reasons.append(f"no {language} speaker available; language filter relaxed")

    if community_ids:
        area_match = [b for b in pool if set(b.community_ids) & set(community_ids)]
        if area_match:
            pool = area_match
            reasons.append("covers the buyer's area")
        else:
            reasons.append("no area specialist available; area filter relaxed")

    # Least loaded first, then least-recently assigned (round-robin), then id for determinism.
    pool.sort(
        key=lambda b: (
            b.active_leads / max(b.max_leads, 1),
            b.last_assigned_at or datetime.min.replace(tzinfo=timezone.utc),
            b.id,
        )
    )
    chosen = pool[0]
    reasons.append(f"least loaded / round-robin → {chosen.name}")
    return RoutingDecision(chosen, reasons)
