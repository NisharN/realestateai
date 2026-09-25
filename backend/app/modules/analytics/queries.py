"""Analytics query API: one typed query shape answers the operational questions
brokers actually ask ("top 5 leads", "who wants Palm Jumeirah", "which source
brings hot leads", "who went quiet").

``AnalyticsQuery`` is the contract used by the HTTP endpoint, the dashboard
Copilot and the ``analytics.query`` routine step. ``parse_question`` turns a
plain-language question into that query deterministically (no LLM needed), so
the Copilot works offline and every answer is reproducible.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.database import get_lead_repository
from app.modules.leads.stages import lead_stage
from app.modules.store import Row, table

Metric = Literal[
    "top_leads",  # highest score, open stages
    "area_demand",  # leads by wanted area
    "leads_for_area",  # leads wanting a given area
    "stale_leads",  # open leads with no contact for N hours
    "source_mix",  # leads + hot share per source
    "pipeline",  # count per stage
    "score_changes",  # biggest movers in the window
    "new_leads",  # created within window
    "viewings",  # upcoming / recent viewings
    "budget_bands",  # budget distribution
]

SCAN_LIMIT = 5000
OPEN_STAGES_EXCLUDED = ("closed", "lost", "opted_out")


class AnalyticsQuery(BaseModel):
    metric: Metric = "top_leads"
    area: str | None = None
    band: Literal["hot", "warm", "cold"] | None = None
    stage: str | None = None
    source: str | None = None
    purpose: Literal["buy", "rent", "invest"] | None = None
    property_type: str | None = None
    min_budget_aed: int | None = None
    max_budget_aed: int | None = None
    days: int = Field(default=30, ge=1, le=365)
    stale_hours: int = Field(default=72, ge=1, le=24 * 90)
    broker_id: str | None = None
    limit: int = Field(default=5, ge=1, le=100)


class AnalyticsResult(BaseModel):
    query: AnalyticsQuery
    title: str
    rows: list[dict[str, Any]]
    total: int
    summary: str
    suggested_actions: list[dict[str, Any]] = Field(default_factory=list)


def _hours_since(ts: Any) -> float | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600)


def lead_areas(lead: Row) -> list[str]:
    raw = lead.get("area_preference") or lead.get("areas") or lead.get("area")
    if isinstance(raw, list):
        return [str(a) for a in raw if a]
    return [str(raw)] if raw else []


def _name(lead: Row) -> str:
    return lead.get("name") or " ".join(x for x in (lead.get("first_name"), lead.get("last_name")) if x) or lead.get("phone") or lead.get("id", "")[:8]


def _view(lead: Row) -> dict[str, Any]:
    return {
        "id": lead.get("id"),
        "name": _name(lead),
        "phone": lead.get("phone"),
        "score": int(lead.get("score") or 0),
        "band": (lead.get("band") or "cold").lower(),
        "stage": lead_stage(lead),
        "areas": lead_areas(lead),
        "budget_max_aed": lead.get("budget_max_aed"),
        "purpose": lead.get("purpose"),
        "property_type": lead.get("property_type"),
        "source": lead.get("source"),
        "assigned_broker": lead.get("assigned_broker"),
        "last_contact_at": lead.get("last_contact_at"),
        "created_at": lead.get("created_at"),
        "score_reasons": (lead.get("score_reasons") or [])[:3],
    }


def _matches(lead: Row, q: AnalyticsQuery) -> bool:
    if q.band and (lead.get("band") or "").lower() != q.band:
        return False
    if q.stage and lead_stage(lead) != q.stage:
        return False
    if q.source and (lead.get("source") or "").lower() != q.source.lower():
        return False
    if q.purpose and (lead.get("purpose") or "").lower() != q.purpose:
        return False
    if q.property_type and (lead.get("property_type") or "").lower() != q.property_type.lower():
        return False
    if q.broker_id and lead.get("assigned_broker") != q.broker_id:
        return False
    budget = lead.get("budget_max_aed")
    if q.min_budget_aed and (budget is None or int(budget) < q.min_budget_aed):
        return False
    if q.max_budget_aed and (budget is None or int(budget) > q.max_budget_aed):
        return False
    return not (q.area and not any(q.area.lower() in a.lower() for a in lead_areas(lead)))


async def run_query(q: AnalyticsQuery, *, workspace_id: str) -> AnalyticsResult:
    repo = get_lead_repository(workspace_id)
    leads: list[Row] = await repo.list_all(limit=SCAN_LIMIT)
    pool = [lead for lead in leads if _matches(lead, q)]
    open_pool = [lead for lead in pool if lead_stage(lead) not in OPEN_STAGES_EXCLUDED]

    if q.metric in ("top_leads", "leads_for_area"):
        ranked = sorted(open_pool, key=lambda x: (int(x.get("score") or 0), x.get("last_contact_at") or ""), reverse=True)[: q.limit]
        rows = [_view(x) for x in ranked]
        where = f" wanting {q.area}" if q.area else ""
        title = f"Top {len(rows)} leads{where}"
        summary = f"{len(open_pool)} open leads{where}; showing the {len(rows)} highest scored." if rows else f"No open leads{where}."
        actions = [{"type": "followups.schedule", "label": "Schedule follow-ups for these leads", "lead_ids": [r["id"] for r in rows]}] if rows else []
        return AnalyticsResult(query=q, title=title, rows=rows, total=len(open_pool), summary=summary, suggested_actions=actions)

    if q.metric == "area_demand":
        counter: Counter[str] = Counter()
        hot: Counter[str] = Counter()
        for lead in open_pool:
            for a in lead_areas(lead):
                counter[a] += 1
                if (lead.get("band") or "").lower() == "hot":
                    hot[a] += 1
        rows = [{"area": a, "leads": n, "hot": hot[a], "share": round(n / max(1, len(open_pool)), 3)} for a, n in counter.most_common(q.limit)]
        top = rows[0]["area"] if rows else None
        return AnalyticsResult(query=q, title="Demand by area", rows=rows, total=len(open_pool), summary=(f"{top} is the most requested area ({rows[0]['leads']} leads, {rows[0]['hot']} hot)." if top else "No area preferences recorded."))

    if q.metric == "stale_leads":
        stale = []
        for lead in open_pool:
            age = _hours_since(lead.get("last_contact_at") or lead.get("updated_at") or lead.get("created_at"))
            if age is not None and age >= q.stale_hours:
                stale.append((age, lead))
        stale.sort(key=lambda t: (-int(t[1].get("score") or 0), -t[0]))
        rows = [{**_view(x), "silent_hours": round(age)} for age, x in stale[: q.limit]]
        days = q.stale_hours / 24
        return AnalyticsResult(
            query=q,
            title=f"Leads silent for {days:g}+ days",
            rows=rows,
            total=len(stale),
            summary=f"{len(stale)} open leads have had no contact for {days:g}+ days." if stale else f"No open lead has been silent for {days:g}+ days.",
            suggested_actions=([{"type": "followups.schedule", "label": "Re-engage these leads", "lead_ids": [r["id"] for r in rows]}, {"type": "leads.reject", "label": "Auto-close the cold ones", "lead_ids": [r["id"] for r in rows if r["band"] == "cold"]}] if rows else []),
        )

    if q.metric == "source_mix":
        counter = Counter((lead.get("source") or "unknown") for lead in pool)
        hot = Counter((lead.get("source") or "unknown") for lead in pool if (lead.get("band") or "").lower() == "hot")
        rows = [{"source": s, "leads": n, "hot": hot[s], "hot_rate": round(hot[s] / n, 3)} for s, n in counter.most_common(q.limit)]
        best = max(rows, key=lambda r: r["hot_rate"]) if rows else None
        return AnalyticsResult(query=q, title="Leads by source", rows=rows, total=len(pool), summary=(f"{best['source']} has the best hot-lead rate ({best['hot_rate']:.0%})." if best else "No leads yet."))

    if q.metric == "pipeline":
        counter = Counter(lead_stage(lead) for lead in pool)
        rows = [{"stage": s, "leads": n} for s, n in counter.most_common()]
        return AnalyticsResult(query=q, title="Pipeline by stage", rows=rows, total=len(pool), summary=f"{len(open_pool)} open of {len(pool)} leads.")

    if q.metric == "new_leads":
        fresh = [lead for lead in pool if (_hours_since(lead.get("created_at")) or 1e9) <= q.days * 24]
        fresh.sort(key=lambda x: x.get("created_at") or "", reverse=True)
        rows = [_view(x) for x in fresh[: q.limit]]
        hot_n = sum(1 for x in fresh if (x.get("band") or "").lower() == "hot")
        return AnalyticsResult(query=q, title=f"New leads (last {q.days} days)", rows=rows, total=len(fresh), summary=f"{len(fresh)} new leads in {q.days} days, {hot_n} hot.")

    if q.metric == "score_changes":
        hist = await table("lead_score_history", workspace_id).select(order="created_at", desc=True, limit=2000)
        cutoff_h = q.days * 24
        by_lead: dict[str, dict[str, Any]] = {}
        for h in hist:
            if (_hours_since(h.get("created_at")) or 1e9) > cutoff_h:
                continue
            e = by_lead.setdefault(h["lead_id"], {"lead_id": h["lead_id"], "delta": 0, "latest": h.get("score"), "band": h.get("band"), "reasons": h.get("reasons") or []})
            e["delta"] += int(h.get("delta") or 0)
        movers = sorted(by_lead.values(), key=lambda e: abs(e["delta"]), reverse=True)[: q.limit]
        by_id = {lead["id"]: lead for lead in leads}
        rows = [{**_view(by_id[m["lead_id"]]), "delta": m["delta"]} if m["lead_id"] in by_id else m for m in movers]
        up = sum(1 for e in by_lead.values() if e["delta"] > 0)
        down = sum(1 for e in by_lead.values() if e["delta"] < 0)
        return AnalyticsResult(query=q, title=f"Biggest score moves (last {q.days} days)", rows=rows, total=len(by_lead), summary=f"{up} leads improved, {down} dropped." if by_lead else "No re-scoring activity yet.")

    if q.metric == "viewings":
        vs = await table("viewings", workspace_id).select(limit=1000)
        lead_ids = {lead["id"] for lead in pool} if (q.area or q.band or q.broker_id or q.source) else None
        rows_v = [v for v in vs if v.get("status") in ("requested", "booked", "confirmed") and (lead_ids is None or v.get("lead_id") in lead_ids)]
        rows_v.sort(key=lambda v: v.get("scheduled_at") or v.get("starts_at") or "")
        return AnalyticsResult(query=q, title="Upcoming viewings", rows=rows_v[: q.limit], total=len(rows_v), summary=f"{len(rows_v)} viewings pending or confirmed.")

    # budget_bands
    bands = [("< 1M", 0, 1_000_000), ("1–2M", 1_000_000, 2_000_000), ("2–5M", 2_000_000, 5_000_000), ("5–10M", 5_000_000, 10_000_000), ("10M+", 10_000_000, 10**12)]
    counter = Counter()
    for lead in open_pool:
        b = lead.get("budget_max_aed")
        if b is None:
            counter["unknown"] += 1
            continue
        for label, lo, hi in bands:
            if lo <= int(b) < hi:
                counter[label] += 1
                break
    rows = [{"band": label, "leads": counter[label]} for label, _, _ in bands] + [{"band": "unknown", "leads": counter["unknown"]}]
    return AnalyticsResult(query=q, title="Budget distribution (open leads)", rows=rows, total=len(open_pool), summary=f"{len(open_pool) - counter['unknown']} of {len(open_pool)} open leads have a budget on file.")


# --------------------------------------------------------------------------- plain-language parsing

_AREA_ALIASES = {
    "palm": "Palm Jumeirah", "palm jumeirah": "Palm Jumeirah", "marina": "Dubai Marina", "dubai marina": "Dubai Marina",
    "downtown": "Downtown Dubai", "business bay": "Business Bay", "jvc": "JVC", "jumeirah village circle": "JVC",
    "dubai hills": "Dubai Hills", "hills estate": "Dubai Hills", "arabian ranches": "Arabian Ranches", "ranches": "Arabian Ranches",
    "damac hills": "DAMAC Hills", "jbr": "JBR", "creek harbour": "Dubai Creek Harbour", "creek": "Dubai Creek Harbour",
    "mbr": "MBR City", "meydan": "Meydan", "barsha": "Al Barsha", "jlt": "JLT", "dubai south": "Dubai South",
    "beachfront": "Emaar Beachfront", "bluewaters": "Bluewaters", "dubai islands": "Dubai Islands", "tilal al ghaf": "Tilal Al Ghaf",
    "springs": "The Springs", "meadows": "The Meadows", "emirates hills": "Emirates Hills", "furjan": "Al Furjan",
    "motor city": "Motor City", "sports city": "Sports City", "silicon oasis": "Silicon Oasis", "mirdif": "Mirdif",
    "yas": "Yas Island", "saadiyat": "Saadiyat", "reem": "Al Reem",
}
_NUM = re.compile(r"\btop\s*(\d{1,3})\b|\b(\d{1,3})\s*(?:leads|buyers|people|clients)\b", re.IGNORECASE)
_DAYS = re.compile(r"(?:last|past)\s*(\d{1,3})\s*(day|week|month)s?|\bthis\s*(week|month)\b|\btoday\b|\byesterday\b", re.IGNORECASE)
_BUDGET_RANGE = re.compile(r"(?:under|below|up to|max)\s*(?:aed)?\s*([\d.]+)\s*(m|k|million)?|(?:over|above|more than|min)\s*(?:aed)?\s*([\d.]+)\s*(m|k|million)?", re.IGNORECASE)


def _amount(n: str, unit: str | None) -> int:
    v = float(n)
    u = (unit or "").lower()
    if u in ("m", "million"):
        v *= 1_000_000
    elif u == "k":
        v *= 1_000
    return int(v) if v >= 10_000 else int(v * 1_000_000)


def parse_question(text: str, *, default_limit: int = 5) -> AnalyticsQuery:
    """Deterministic mapping from a broker's question to an ``AnalyticsQuery``."""
    low = " ".join((text or "").lower().split())
    q = AnalyticsQuery(limit=default_limit)

    m = _NUM.search(low)
    if m:
        q.limit = max(1, min(100, int(m.group(1) or m.group(2))))

    for alias, canonical in sorted(_AREA_ALIASES.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{re.escape(alias)}\b", low):
            q.area = canonical
            break

    for band in ("hot", "warm", "cold"):
        if re.search(rf"\b{band}\b", low):
            q.band = band  # type: ignore[assignment]
            break
    for purpose, pat in (("rent", r"\b(rent|rental|tenant)s?\b"), ("invest", r"\b(invest|investor|yield|roi)s?\b"), ("buy", r"\b(buy|buyer|purchase)s?\b")):
        if re.search(pat, low):
            q.purpose = purpose  # type: ignore[assignment]
            break
    for ptype in ("villa", "townhouse", "penthouse", "apartment", "studio", "plot"):
        if re.search(rf"\b{ptype}s?\b", low):
            q.property_type = ptype
            break
    for src in ("bayut", "dubizzle", "property finder", "property_finder", "meta", "facebook", "instagram", "whatsapp", "website", "gmail", "referral"):
        if src in low:
            q.source = {"property finder": "property_finder", "facebook": "meta_lead_ads", "instagram": "meta_lead_ads", "meta": "meta_lead_ads"}.get(src, src)
            break

    d = _DAYS.search(low)
    if d:
        if d.group(1):
            n, unit = int(d.group(1)), d.group(2)
            q.days = n * {"day": 1, "week": 7, "month": 30}[unit]
        elif d.group(3):
            q.days = 7 if d.group(3) == "week" else 30
        else:
            q.days = 1
    for bm in _BUDGET_RANGE.finditer(low):
        if bm.group(1):
            q.max_budget_aed = _amount(bm.group(1), bm.group(2))
        if bm.group(3):
            q.min_budget_aed = _amount(bm.group(3), bm.group(4))

    if re.search(r"\b(stale|quiet|silent|no (?:reply|response|contact)|not (?:replied|responded)|went cold|ghost)", low):
        q.metric = "stale_leads"
        sm = re.search(r"(\d{1,3})\s*(day|week|hour)s?", low)
        if sm:
            q.stale_hours = int(sm.group(1)) * {"hour": 1, "day": 24, "week": 168}[sm.group(2)]
    elif re.search(r"\b(demand|popular|most (?:wanted|requested|searched)|which areas?|by area|areas? (?:are|do))", low):
        q.metric = "area_demand"
    elif re.search(r"\b(source|channel|where (?:do|are) .*(?:come|from)|portal performance|campaign)", low):
        q.metric = "source_mix"
    elif re.search(r"\b(pipeline|stages?|funnel|by stage)\b", low):
        q.metric = "pipeline"
    elif re.search(r"\b(viewings?|appointments?|visits?)\b", low):
        q.metric = "viewings"
    elif re.search(r"\b(improv|dropp|moved|movers|score change|rescor|went up|went down)", low):
        q.metric = "score_changes"
    elif re.search(r"\b(budget|price range|how much)\b", low) and not q.area:
        q.metric = "budget_bands"
    elif re.search(r"\b(new|recent|latest|came in|arrived|this week|today)\b", low) and not re.search(r"\btop\b", low):
        q.metric = "new_leads"
    elif q.area:
        q.metric = "leads_for_area"
    else:
        q.metric = "top_leads"
    return q


SUGGESTED_QUESTIONS = [
    "Top 5 leads to call today",
    "Who wants Palm Jumeirah?",
    "Hot leads that went quiet for 3 days",
    "Which areas are most in demand?",
    "New leads this week",
    "Which source brings the hottest leads?",
    "Investors with budget over 3M",
    "Whose score dropped this month?",
]
