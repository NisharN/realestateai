"""viewing_slots tool — deterministic next available call/viewing windows."""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from pydantic import BaseModel

DUBAI = ZoneInfo("Asia/Dubai")
WORK_START, WORK_END = time(10, 0), time(19, 0)
WEEKEND = {5, 6}  # Sat, Sun


class Slot(BaseModel):
    starts_at: str
    label_en: str
    label_ar: str


def next_slots(now: datetime | None = None, count: int = 2) -> list[Slot]:
    now = (now or datetime.now(timezone.utc)).astimezone(DUBAI)
    slots: list[Slot] = []
    cursor = now
    while len(slots) < count:
        cursor = cursor + timedelta(days=1)
        if cursor.weekday() in WEEKEND:
            continue
        for hour, en, ar in ((11, "morning", "صباحاً"), (16, "afternoon", "بعد الظهر")):
            start = cursor.replace(hour=hour, minute=0, second=0, microsecond=0)
            day_en = "tomorrow" if start.date() == (now + timedelta(days=1)).date() else start.strftime("%A")
            day_ar = "غداً" if day_en == "tomorrow" else start.strftime("%A")
            slots.append(
                Slot(
                    starts_at=start.astimezone(timezone.utc).isoformat(),
                    label_en=f"{day_en} {en}",
                    label_ar=f"{day_ar} {ar}",
                )
            )
            if len(slots) >= count:
                break
    return slots
