"""Co-work Routines: scheduled broker workflows built from connector, data and LLM steps.

A routine = schedule + ordered steps. Steps pass a small context (leads,
listings, summary, drafts) forward. Each run is recorded with per-step
status so the Activity tab can show exactly what happened. LLM steps
degrade to deterministic rules when no provider is configured and say so.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator

from app.modules.cowork import connections as conn
from app.modules.cowork.automations import TASKS_TABLE, render_template
from app.modules.leads.stages import PIPELINE_STAGES, lead_stage
from app.modules.store import Row, new_id, now_iso, table

logger = logging.getLogger(__name__)

TABLE = "cowork_routines"
RUNS_TABLE = "cowork_routine_runs"
MAX_STEPS = 12
MAX_LEADS = 200
MAX_MESSAGES_PER_RUN = 50
FORBIDDEN_JOBS = {"run_routines", "run_automations"}

StepType = Literal[
    "connector.pull_listings",
    "connector.pull_leads",
    "connector.push_leads",
    "connector.send_message",
    "connector.send_email",
    "connector.create_event",
    "connector.notify",
    "leads.select",
    "viewings.select",
    "listings.validate",
    "llm.qualify",
    "llm.summarize",
    "llm.draft_message",
    "tasks.create",
    "job.run",
    "analytics.query",
    "followups.schedule",
    "leads.reject",
    "leads.rescore",
    "listings.refresh",
    "voice.send_note",
]

STEP_TYPES: dict[str, dict[str, Any]] = {
    "connector.pull_listings": {"label": "Pull live listings", "group": "connector", "needs_connection": True, "capability": "pull_listings", "params": ["path"]},
    "connector.pull_leads": {"label": "Fetch new leads", "group": "connector", "needs_connection": True, "capability": "pull_leads", "params": ["path"]},
    "connector.push_leads": {"label": "Push selected leads to CRM", "group": "connector", "needs_connection": True, "capability": "push_leads", "params": []},
    "connector.send_message": {"label": "WhatsApp selected leads", "group": "connector", "needs_connection": True, "capability": "send_message", "params": ["template", "use_drafts"]},
    "connector.send_email": {"label": "E-mail summary", "group": "connector", "needs_connection": True, "capability": "send_email", "params": ["to", "subject"]},
    "connector.create_event": {"label": "Create calendar events for viewings", "group": "connector", "needs_connection": True, "capability": "create_event", "params": []},
    "connector.notify": {"label": "Notify team (Slack / WhatsApp)", "group": "connector", "needs_connection": True, "capability": "notify", "params": ["text", "to"]},
    "leads.select": {"label": "Select leads", "group": "data", "needs_connection": False, "params": ["stage", "band", "min_score", "stale_hours", "created_within_hours", "limit"]},
    "viewings.select": {"label": "Select upcoming viewings", "group": "data", "needs_connection": False, "params": ["within_hours", "limit"]},
    "listings.validate": {"label": "Validate listings (permit, price, photos)", "group": "data", "needs_connection": False, "params": ["limit"]},
    "llm.qualify": {"label": "Qualify & score selected leads (Jev)", "group": "llm", "needs_connection": False, "capability": "score_leads", "params": []},
    "llm.summarize": {"label": "AI summary of this run", "group": "llm", "needs_connection": False, "params": ["focus"]},
    "llm.draft_message": {"label": "AI draft follow-up per lead", "group": "llm", "needs_connection": False, "params": ["channel", "tone", "language"]},
    "tasks.create": {"label": "Create broker tasks for selected leads", "group": "data", "needs_connection": False, "params": ["title", "due_in_hours"]},
    "job.run": {"label": "Run a scheduled job", "group": "data", "needs_connection": False, "params": ["job_id"]},
    "analytics.query": {"label": "Ask analytics (e.g. top 5 leads, who wants Palm Jumeirah)", "group": "data", "needs_connection": False, "params": ["question", "metric", "area", "band", "limit"]},
    "followups.schedule": {"label": "Schedule follow-up cadence for selected leads", "group": "data", "needs_connection": False, "params": ["band"]},
    "leads.reject": {"label": "Auto-close unresponsive / unqualified leads", "group": "data", "needs_connection": False, "params": ["max_score", "stale_hours", "reason"]},
    "leads.rescore": {"label": "Re-score selected leads from their latest behaviour", "group": "llm", "needs_connection": False, "capability": "score_leads", "params": []},
    "listings.refresh": {"label": "Expire stale listings & flag price changes", "group": "data", "needs_connection": False, "params": ["stale_days", "limit"]},
    "voice.send_note": {"label": "Send automated WhatsApp voice note", "group": "connector", "needs_connection": True, "capability": "send_voice_note", "params": ["template", "language", "use_drafts"]},
}


class Schedule(BaseModel):
    kind: Literal["interval", "daily", "weekly"] = "daily"
    seconds: int | None = Field(None, ge=300, le=7 * 86_400)
    at: str | None = Field(None, pattern=r"^\d{2}:\d{2}$")
    weekday: int | None = Field(None, ge=0, le=6)
    tz: str = "Asia/Dubai"

    @field_validator("tz")
    @classmethod
    def _tz(cls, v: str) -> str:
        ZoneInfo(v)  # raises for unknown zones
        return v

    def validate_shape(self) -> None:
        if self.kind == "interval" and not self.seconds:
            raise ValueError("interval schedule needs seconds")
        if self.kind in ("daily", "weekly") and not self.at:
            raise ValueError(f"{self.kind} schedule needs at=HH:MM")
        if self.kind == "weekly" and self.weekday is None:
            raise ValueError("weekly schedule needs weekday (0=Mon)")


class Step(BaseModel):
    id: str | None = None
    type: StepType
    connection_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class RoutineIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(None, max_length=500)
    schedule: Schedule
    steps: list[Step] = Field(..., min_length=1, max_length=MAX_STEPS)
    enabled: bool = True
    template_id: str | None = None


class RoutinePatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=500)
    schedule: Schedule | None = None
    steps: list[Step] | None = Field(None, min_length=1, max_length=MAX_STEPS)
    enabled: bool | None = None


async def validate_steps(workspace_id: str, steps: list[Step]) -> list[dict[str, Any]]:
    from app.modules.cowork.jobs import JOB_INDEX

    out: list[dict[str, Any]] = []
    for i, step in enumerate(steps):
        meta = STEP_TYPES[step.type]
        if meta.get("capability") and step.connection_id:
            row = await conn.get_connection(workspace_id, step.connection_id)
            if not row:
                raise ValueError(f"step {i + 1}: connection not found")
            spec = conn.get_provider(row["provider"])
            cap = meta["capability"]
            if not spec or cap not in spec.capabilities:
                raise ValueError(f"step {i + 1}: {row.get('display_name')} cannot {cap}")
        if step.type == "job.run":
            job_id = str(step.params.get("job_id") or "")
            if job_id in FORBIDDEN_JOBS or job_id not in JOB_INDEX:
                raise ValueError(f"step {i + 1}: unknown or forbidden job {job_id!r}")
        if step.type == "leads.select" and step.params.get("stage") and step.params["stage"] not in PIPELINE_STAGES:
            raise ValueError(f"step {i + 1}: stage must be one of {', '.join(PIPELINE_STAGES)}")
        out.append({"id": step.id or new_id(), "type": step.type, "connection_id": step.connection_id, "params": step.params})
    return out


# --------------------------------------------------------------------------- scheduling


def next_run(schedule: dict[str, Any], *, after: datetime | None = None) -> str:
    now = after or datetime.now(timezone.utc)
    kind = schedule.get("kind", "daily")
    if kind == "interval":
        return (now + timedelta(seconds=int(schedule.get("seconds") or 3600))).isoformat()
    tz = ZoneInfo(schedule.get("tz") or "Asia/Dubai")
    hh, mm = (schedule.get("at") or "08:00").split(":")
    local = now.astimezone(tz)
    candidate = local.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    if kind == "weekly":
        target = int(schedule.get("weekday") or 0)
        delta = (target - candidate.weekday()) % 7
        candidate += timedelta(days=delta)
        if candidate <= local:
            candidate += timedelta(days=7)
    elif candidate <= local:
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc).isoformat()


def describe_schedule(schedule: dict[str, Any]) -> str:
    kind = schedule.get("kind")
    if kind == "interval":
        s = int(schedule.get("seconds") or 0)
        return f"every {s // 3600}h" if s % 3600 == 0 else f"every {s // 60} min"
    if kind == "weekly":
        days = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
        return f"weekly · {days[int(schedule.get('weekday') or 0)]} {schedule.get('at')} {schedule.get('tz')}"
    return f"daily · {schedule.get('at')} {schedule.get('tz')}"


# --------------------------------------------------------------------------- CRUD


def public_view(row: Row) -> Row:
    return {**row, "schedule_label": describe_schedule(row.get("schedule") or {})}


async def list_routines(workspace_id: str) -> list[Row]:
    rows = await table(TABLE, workspace_id).select(order="created_at", desc=True, limit=200)
    return [public_view(r) for r in rows]


async def get_routine(workspace_id: str, routine_id: str) -> Row | None:
    return await table(TABLE, workspace_id).get(id=routine_id)


async def create_routine(workspace_id: str, body: RoutineIn, *, actor: str | None) -> Row:
    body.schedule.validate_shape()
    steps = await validate_steps(workspace_id, body.steps)
    schedule = body.schedule.model_dump()
    row = await table(TABLE, workspace_id).insert(
        {
            "id": new_id(),
            "name": body.name,
            "description": body.description,
            "schedule": schedule,
            "steps": steps,
            "enabled": body.enabled,
            "template_id": body.template_id,
            "run_count": 0,
            "last_run_at": None,
            "last_status": None,
            "next_run_at": next_run(schedule) if body.enabled else None,
            "created_by": actor,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
    )
    return public_view(row)


async def patch_routine(workspace_id: str, routine_id: str, body: RoutinePatch) -> Row | None:
    t = table(TABLE, workspace_id)
    current = await t.get(id=routine_id)
    if not current:
        return None
    updates: Row = {"updated_at": now_iso()}
    if body.name is not None:
        updates["name"] = body.name
    if body.description is not None:
        updates["description"] = body.description
    if body.schedule is not None:
        body.schedule.validate_shape()
        updates["schedule"] = body.schedule.model_dump()
    if body.steps is not None:
        updates["steps"] = await validate_steps(workspace_id, body.steps)
    if body.enabled is not None:
        updates["enabled"] = body.enabled
    enabled = updates.get("enabled", current.get("enabled"))
    if "schedule" in updates or "enabled" in updates:
        updates["next_run_at"] = next_run(updates.get("schedule") or current["schedule"]) if enabled else None
    rows = await t.update(updates, id=routine_id)
    return public_view(rows[0]) if rows else None


async def delete_routine(workspace_id: str, routine_id: str) -> bool:
    await table(RUNS_TABLE, workspace_id).update({"routine_id": None}, routine_id=routine_id)
    return (await table(TABLE, workspace_id).delete(id=routine_id)) > 0


async def due_routines(workspace_id: str, *, now: str | None = None, limit: int = 20) -> list[Row]:
    now = now or now_iso()
    rows = await table(TABLE, workspace_id).select(enabled=True, limit=500)
    return [r for r in rows if r.get("next_run_at") and r["next_run_at"] <= now][:limit]


async def list_runs(workspace_id: str, *, routine_id: str | None = None, limit: int = 50) -> list[Row]:
    t = table(RUNS_TABLE, workspace_id)
    if routine_id:
        return await t.select(order="started_at", desc=True, limit=limit, routine_id=routine_id)
    return await t.select(order="started_at", desc=True, limit=limit)


# --------------------------------------------------------------------------- execution


class RunContext:
    def __init__(self, workspace_id: str, routine: Row) -> None:
        self.workspace_id = workspace_id
        self.routine = routine
        self.leads: list[Row] = []
        self.viewings: list[Row] = []
        self.issues: list[dict[str, Any]] = []
        self.qualifications: dict[str, dict[str, Any]] = {}
        self.drafts: dict[str, str] = {}
        self.summary: str | None = None
        self.step_results: list[dict[str, Any]] = []

    def facts(self) -> dict[str, Any]:
        return {
            "routine": self.routine.get("name"),
            "leads_selected": len(self.leads),
            "viewings_selected": len(self.viewings),
            "listing_issues": len(self.issues),
            "steps": [{"type": s["type"], "status": s["status"], **{k: v for k, v in (s.get("summary") or {}).items() if isinstance(v, (int, str, bool))}} for s in self.step_results],
        }


def _hours_since(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds() / 3600


async def _select_leads(ctx: RunContext, params: dict[str, Any]) -> dict[str, Any]:
    from app.database import get_lead_repository

    repo = get_lead_repository(ctx.workspace_id)
    limit = min(int(params.get("limit") or 50), MAX_LEADS)
    rows: list[Row] = await repo.list_all(limit=2000)
    out: list[Row] = []
    for lead in rows:
        if params.get("stage") and lead_stage(lead) != params["stage"]:
            continue
        if params.get("band") and (lead.get("band") or "").lower() != str(params["band"]).lower():
            continue
        if params.get("min_score") is not None and int(lead.get("score") or 0) < int(params["min_score"]):
            continue
        if params.get("source") and (lead.get("source") or "").lower() != str(params["source"]).lower():
            continue
        if params.get("stale_hours"):
            age = _hours_since(lead.get("last_contact_at") or lead.get("updated_at") or lead.get("created_at"))
            if age is None or age < float(params["stale_hours"]):
                continue
            if lead_stage(lead) in ("closed", "lost", "opted_out"):
                continue
        if params.get("created_within_hours"):
            age = _hours_since(lead.get("created_at"))
            if age is None or age > float(params["created_within_hours"]):
                continue
        out.append(lead)
        if len(out) >= limit:
            break
    ctx.leads = out
    return {"selected": len(out), "scanned": len(rows)}


async def _select_viewings(ctx: RunContext, params: dict[str, Any]) -> dict[str, Any]:
    within = float(params.get("within_hours") or 24)
    limit = min(int(params.get("limit") or 50), MAX_LEADS)
    rows = await table("viewings", ctx.workspace_id).select(limit=1000)
    now = datetime.now(timezone.utc)
    out = []
    for v in rows:
        if v.get("status") not in ("requested", "booked", "confirmed"):
            continue
        starts = v.get("starts_at")
        if not starts:
            continue
        try:
            dt = datetime.fromisoformat(str(starts).replace("Z", "+00:00"))
        except ValueError:
            continue
        if now <= dt <= now + timedelta(hours=within):
            out.append(v)
    ctx.viewings = out[:limit]
    return {"selected": len(ctx.viewings)}


async def _validate_listings(ctx: RunContext, params: dict[str, Any]) -> dict[str, Any]:
    limit = min(int(params.get("limit") or 500), 2000)
    rows = await table("properties", ctx.workspace_id).select(limit=limit)
    issues: list[dict[str, Any]] = []
    for p in rows:
        if not p.get("is_active", True):
            continue
        problems = []
        if not p.get("permit_number"):
            problems.append("missing RERA permit")
        if not p.get("price"):
            problems.append("missing price")
        if not p.get("images"):
            problems.append("no photos")
        if not p.get("area") and not p.get("community"):
            problems.append("missing community")
        if problems:
            issues.append({"property_id": p.get("id"), "title": p.get("title"), "problems": problems})
    ctx.issues = issues
    return {"checked": len(rows), "with_issues": len(issues)}


def _rule_qualify(lead: Row) -> dict[str, Any]:
    score = int(lead.get("score") or 0)
    band = (lead.get("band") or ("hot" if score >= 70 else "warm" if score >= 40 else "cold")).lower()
    reasons = []
    if lead.get("budget_max_aed"):
        reasons.append("budget stated")
    if lead.get("timeline"):
        reasons.append(f"timeline {lead['timeline']}")
    if lead.get("area_preference") or lead.get("community_ids"):
        reasons.append("area known")
    return {"band": band, "score": score, "intent": lead.get("purpose") or "unknown", "reasons": reasons or ["insufficient data"], "source": "rules"}


class _Qualification(BaseModel):
    band: Literal["hot", "warm", "cold"]
    score: int = Field(ge=0, le=100)
    intent: str = Field(max_length=40)
    reasons: list[str] = Field(default_factory=list, max_length=5)
    next_action: str = Field(default="", max_length=160)


def _lead_brief(lead: Row) -> str:
    keys = ("first_name", "purpose", "budget_max_aed", "timeline", "area_preference", "bedrooms", "score", "stage", "language", "message", "last_message")
    return "; ".join(f"{k}={lead.get(k)}" for k in keys if lead.get(k) not in (None, "", []))[:800]


def _lead_state(lead: Row) -> dict[str, Any]:
    keys = ("purpose", "budget_max_aed", "budget_min_aed", "timeline", "payment", "area_preference", "property_type", "bedrooms", "score", "band", "stage", "source", "language", "message", "last_message")
    return {k: lead.get(k) for k in keys if lead.get(k) not in (None, "", [])}


async def _jev_credentials(ctx: RunContext, connection_id: str | None) -> dict[str, Any] | None:
    """Jev credentials from the step's connection, else the workspace-wide env key; None when neither."""
    from app.modules.llm import jev

    if connection_id:
        row = await conn.get_connection(ctx.workspace_id, connection_id)
        if row and row.get("provider") == "typesafe_jev" and row.get("status") == "active":
            cfg = dict(row.get("config") or {})
            if cfg.get("api_key"):
                return {"api_key": cfg["api_key"], "model": cfg.get("model") or None, "base_url": cfg.get("base_url") or None}
    return {} if jev.configured() else None


async def _llm_qualify(ctx: RunContext, params: dict[str, Any], *, connection_id: str | None = None) -> dict[str, Any]:
    from app.modules.llm import LLMUnavailable, get_gateway, jev

    creds = await _jev_credentials(ctx, connection_id)
    jev_used = 0
    jev_error: str | None = None
    if creds is not None:
        for lead in ctx.leads[:MAX_LEADS]:
            try:
                q = await jev.qualify(_lead_state(lead), **creds)
            except jev.JevUnavailable as exc:
                jev_error = str(exc)
                break
            ctx.qualifications[lead["id"]] = {"band": q.band, "score": q.score, "intent": q.intent, "reasons": q.reasons, "confidence": q.band_confidence, "needs_human": q.needs_human, "source": "jev", "model": q.model}
            jev_used += 1
        if jev_used == len(ctx.leads[:MAX_LEADS]):
            return {"qualified": jev_used, "jev": jev_used, "llm": 0, "rules": 0, "provider": "typesafe_jev", "simulated": False}

    gw = get_gateway()
    llm_used = 0
    for lead in ctx.leads[:MAX_LEADS]:
        if lead["id"] in ctx.qualifications:
            continue
        result: dict[str, Any] | None = None
        if gw.available:
            try:
                q = await gw.complete_json(
                    [
                        {"role": "system", "content": "You qualify UAE real-estate buyer leads. Return JSON {band: hot|warm|cold, score: 0-100, intent, reasons[], next_action}. Be conservative; missing budget or timeline caps score at 60."},
                        {"role": "user", "content": _lead_brief(lead)},
                    ],
                    _Qualification,
                    purpose="routine.qualify",
                )
                result = {**q.model_dump(), "source": "llm"}
                llm_used += 1
            except LLMUnavailable:
                result = None
        ctx.qualifications[lead["id"]] = result or _rule_qualify(lead)
    out: dict[str, Any] = {
        "qualified": len(ctx.qualifications),
        "jev": jev_used,
        "llm": llm_used,
        "rules": len(ctx.qualifications) - llm_used - jev_used,
        "simulated": jev_used == 0 and llm_used == 0 and bool(ctx.leads),
    }
    if jev_error:
        out["jev_error"] = jev_error
    elif creds is None:
        out["reason"] = "Jev not configured — connect TypeSafe AI or set TYPESAFE_API_KEY"
    return out


async def _llm_summarize(ctx: RunContext, params: dict[str, Any]) -> dict[str, Any]:
    from app.modules.llm import LLMUnavailable, get_gateway

    facts = ctx.facts()
    hot = sum(1 for q in ctx.qualifications.values() if q.get("band") == "hot")
    fallback = (
        f"{facts['routine']}: {facts['leads_selected']} lead(s) selected"
        + (f", {hot} hot" if ctx.qualifications else "")
        + (f", {facts['viewings_selected']} upcoming viewing(s)" if ctx.viewings else "")
        + (f", {facts['listing_issues']} listing(s) need fixes" if ctx.issues else "")
        + "."
    )
    gw = get_gateway()
    if gw.available:
        try:
            c = await gw.complete_text(
                [
                    {"role": "system", "content": f"Write a 3-sentence operational digest for a Dubai brokerage team. Focus: {params.get('focus') or 'what needs action today'}. Plain text, no markdown."},
                    {"role": "user", "content": str(facts)[:3000]},
                ],
                max_tokens=220,
                purpose="routine.summarize",
            )
            ctx.summary = c.text.strip()
            return {"chars": len(ctx.summary), "source": "llm"}
        except LLMUnavailable:
            pass
    ctx.summary = fallback
    return {"chars": len(fallback), "source": "rules", "simulated": True}


async def _llm_draft(ctx: RunContext, params: dict[str, Any]) -> dict[str, Any]:
    from app.modules.llm import LLMUnavailable, get_gateway

    gw = get_gateway()
    lang = str(params.get("language") or "en")
    tone = str(params.get("tone") or "warm, concise, professional")
    llm_used = 0
    for lead in ctx.leads[:MAX_MESSAGES_PER_RUN]:
        name = lead.get("first_name") or ""
        area = lead.get("area_preference") or "Dubai"
        fallback = (
            f"مرحباً {name}، هل ما زلت تبحث عن عقار في {area}؟ يسعدني إرسال أحدث الخيارات أو ترتيب معاينة."
            if lang == "ar"
            else f"Hi {name}, are you still looking in {area}? Happy to share this week's new listings or set up a viewing."
        )
        if gw.available:
            try:
                c = await gw.complete_text(
                    [
                        {"role": "system", "content": f"Draft one short {params.get('channel') or 'WhatsApp'} follow-up (max 60 words, language={lang}, tone={tone}) from a Dubai property broker. No placeholders, no markdown."},
                        {"role": "user", "content": _lead_brief(lead)},
                    ],
                    max_tokens=120,
                    purpose="routine.draft",
                )
                ctx.drafts[lead["id"]] = c.text.strip()
                llm_used += 1
                continue
            except LLMUnavailable:
                pass
        ctx.drafts[lead["id"]] = fallback
    return {"drafted": len(ctx.drafts), "llm": llm_used, "simulated": llm_used == 0 and bool(ctx.drafts)}


async def _create_tasks(ctx: RunContext, params: dict[str, Any]) -> dict[str, Any]:
    tasks = table(TASKS_TABLE, ctx.workspace_id)
    created = 0
    for lead in ctx.leads[:MAX_LEADS]:
        q = ctx.qualifications.get(lead["id"])
        title = render_template(str(params.get("title") or "Follow up with {first_name}"), lead)
        if q and q.get("next_action"):
            title = f"{title} — {q['next_action']}"
        await tasks.insert(
            {
                "id": new_id(),
                "lead_id": lead["id"],
                "broker_id": lead.get("assigned_broker"),
                "title": title[:200],
                "due_in_hours": int(params.get("due_in_hours") or 24),
                "status": "open",
                "automation_id": None,
                "routine_id": ctx.routine["id"],
                "created_at": now_iso(),
            }
        )
        created += 1
    return {"created": created}


async def _run_job(ctx: RunContext, params: dict[str, Any]) -> dict[str, Any]:
    from app.modules.cowork.jobs import run_job

    job_id = str(params.get("job_id") or "")
    if job_id in FORBIDDEN_JOBS:
        return {"error": "forbidden job"}
    run = await run_job(ctx.workspace_id, job_id, trigger="automation", actor=f"routine:{ctx.routine['id']}")
    return {"job_id": job_id, "status": run.get("status"), **{k: v for k, v in (run.get("summary") or {}).items() if isinstance(v, (int, str))}}


def _allowed(lead: Row) -> bool:
    from app.modules.handoff.followups import _allowed as allowed

    return allowed(lead)


async def _connector_step(ctx: RunContext, step: dict[str, Any]) -> dict[str, Any]:
    if not step.get("connection_id"):
        return {"skipped": True, "reason": "no connection selected"}
    row = await conn.get_connection(ctx.workspace_id, step["connection_id"])
    if not row:
        return {"skipped": True, "reason": "connection deleted"}
    action = step["type"].split(".", 1)[1]
    params = dict(step.get("params") or {})
    ws = ctx.workspace_id

    if action in ("pull_listings", "pull_leads"):
        return await conn.execute_action(ws, row, action, params)

    if action == "push_leads":
        sent = failed = 0
        last: dict[str, Any] = {}
        for lead in ctx.leads[:MAX_LEADS]:
            last = await conn.execute_action(ws, row, "push_lead", {"lead": {k: lead.get(k) for k in ("id", "first_name", "last_name", "name", "phone", "email", "stage", "score", "budget_max_aed", "area_preference")}})
            if last.get("simulated"):
                return {"simulated": True, "reason": last.get("reason"), "would_push": len(ctx.leads)}
            sent += 1 if last.get("ok") else 0
            failed += 0 if last.get("ok") else 1
        return {"pushed": sent, "failed": failed}

    if action == "send_message":
        sent = skipped = 0
        template = str(params.get("template") or "")
        for lead in ctx.leads[:MAX_MESSAGES_PER_RUN]:
            if not _allowed(lead):
                skipped += 1
                continue
            body = ctx.drafts.get(lead["id"]) if params.get("use_drafts", True) else None
            body = body or (render_template(template, lead) if template else None)
            if not body:
                skipped += 1
                continue
            res = await conn.execute_action(ws, row, "send_message", {"to": lead.get("phone") or lead.get("phone_e164"), "body": body, "lead_id": lead["id"]})
            if res.get("simulated"):
                return {"simulated": True, "reason": res.get("reason"), "would_send": len(ctx.leads) - skipped}
            sent += 1 if res.get("ok") else 0
        return {"sent": sent, "skipped_no_consent_or_body": skipped}

    if action == "send_email":
        body = ctx.summary or str(ctx.facts())
        return await conn.execute_action(ws, row, "send_email", {"to": params.get("to"), "subject": params.get("subject") or ctx.routine.get("name"), "body": body})

    if action == "create_event":
        created = 0
        for v in ctx.viewings[:MAX_MESSAGES_PER_RUN]:
            start = v.get("starts_at")
            if not start:
                continue
            try:
                end = (datetime.fromisoformat(str(start).replace("Z", "+00:00")) + timedelta(minutes=45)).isoformat()
            except ValueError:
                continue
            res = await conn.execute_action(ws, row, "create_event", {"start": start, "end": end, "summary": f"Viewing · {v.get('property_title') or v.get('property_id')}", "location": v.get('property_title'), "attendees": [e for e in (v.get("buyer_email"), v.get("broker_email")) if e]})
            if res.get("simulated"):
                return {"simulated": True, "reason": res.get("reason"), "would_create": len(ctx.viewings)}
            created += 1 if res.get("ok") else 0
        return {"created": created}

    if action == "notify":
        text = params.get("text") or ctx.summary or f"{ctx.routine.get('name')}: {len(ctx.leads)} lead(s), {len(ctx.issues)} listing issue(s)."
        return await conn.execute_action(ws, row, "notify", {"text": text, "to": params.get("to")})

    if action == "send_note":
        return await _voice_note_step(ctx, row, params)

    return {"error": f"unknown connector action {action}"}


async def _voice_note_step(ctx: RunContext, row: Row, params: dict[str, Any]) -> dict[str, Any]:
    """One voice note per consented lead. A failed TTS/delivery is reported, never converted to a text send."""
    sent = skipped = failed = 0
    errors: list[str] = []
    template = str(params.get("template") or "")
    for lead in ctx.leads[:MAX_MESSAGES_PER_RUN]:
        if not _allowed(lead):
            skipped += 1
            continue
        text = ctx.drafts.get(lead["id"]) if params.get("use_drafts", True) else None
        text = text or (render_template(template, lead) if template else None)
        if not text:
            skipped += 1
            continue
        lang = params.get("language") or ("ar" if lead.get("language") == "ar" else None)
        res = await conn.execute_action(ctx.workspace_id, row, "send_voice_note", {"to": lead.get("phone") or lead.get("phone_e164"), "text": text, "language": lang, "lead_id": lead["id"]})
        if res.get("simulated"):
            return {"simulated": True, "reason": res.get("reason"), "would_send": len(ctx.leads) - skipped}
        if res.get("ok"):
            sent += 1
        else:
            failed += 1
            if len(errors) < 3 and res.get("error"):
                errors.append(str(res["error"])[:120])
    out: dict[str, Any] = {"sent": sent, "failed": failed, "skipped_no_consent_or_text": skipped, "text_fallback": False}
    if failed and not sent:
        out["error"] = f"no voice notes delivered: {'; '.join(errors) or 'connector error'}"
    elif errors:
        out["errors"] = errors
    return out


async def _analytics_query(ctx: RunContext, params: dict[str, Any]) -> dict[str, Any]:
    from app.modules.analytics.queries import AnalyticsQuery, parse_question, run_query

    if params.get("question"):
        q = parse_question(str(params["question"]), default_limit=int(params.get("limit") or 5))
    else:
        q = AnalyticsQuery(**{k: v for k, v in params.items() if k in AnalyticsQuery.model_fields and v not in (None, "")})
    result = await run_query(q, workspace_id=ctx.workspace_id)
    ids = [r["id"] for r in result.rows if isinstance(r, dict) and r.get("id")]
    if ids:
        from app.database import get_lead_repository

        repo = get_lead_repository(ctx.workspace_id)
        ctx.leads = [lead for lead in [await repo.get_by_id(i) for i in ids[:MAX_LEADS]] if lead]
    ctx.summary = f"{result.title}: {result.summary}"
    return {"metric": q.metric, "title": result.title, "total": result.total, "rows": len(result.rows), "selected": len(ids), "answer": result.summary}


async def _schedule_followups(ctx: RunContext, params: dict[str, Any]) -> dict[str, Any]:
    from app.modules.handoff.followups import CADENCE_HOURS, schedule_followups

    scheduled = skipped = broker_owned = 0
    for lead in ctx.leads[:MAX_LEADS]:
        band = str(params.get("band") or lead.get("band") or "warm").lower()
        if not CADENCE_HOURS.get(band):
            broker_owned += 1
            continue
        rows = await schedule_followups(lead["id"], band, workspace_id=ctx.workspace_id)
        if rows:
            scheduled += 1
        else:
            skipped += 1
    return {"scheduled": scheduled, "skipped_no_consent": skipped, "broker_owned": broker_owned}


async def _reject_leads(ctx: RunContext, params: dict[str, Any]) -> dict[str, Any]:
    """Close leads that are both low-scored and silent; never touches viewing/offer stages."""
    from app.database import get_lead_repository
    from app.modules.handoff.followups import cancel_followups
    from app.modules.ingestion import events

    repo = get_lead_repository(ctx.workspace_id)
    max_score = int(params.get("max_score") or 30)
    stale_hours = float(params.get("stale_hours") or 24 * 14)
    reason = str(params.get("reason") or "auto_reject_unresponsive")[:80]
    closed = protected = skipped = 0
    for lead in ctx.leads[:MAX_LEADS]:
        stage = lead_stage(lead)
        if stage in ("viewing_booked", "offer", "closed", "lost", "opted_out"):
            protected += 1
            continue
        age = _hours_since(lead.get("last_contact_at") or lead.get("updated_at") or lead.get("created_at"))
        if int(lead.get("score") or 0) > max_score or age is None or age < stale_hours:
            skipped += 1
            continue
        await repo.update(lead["id"], {"stage": "lost", "lost_reason": reason, "updated_at": now_iso()})
        await cancel_followups(lead["id"], reason=reason, workspace_id=ctx.workspace_id)
        await events.emit(lead["id"], "lead.updated", {"stage": "lost", "reason": reason, "routine_id": ctx.routine["id"]}, workspace_id=ctx.workspace_id)
        closed += 1
    return {"closed": closed, "kept_active": skipped, "protected": protected}


async def _rescore(ctx: RunContext, params: dict[str, Any]) -> dict[str, Any]:
    from app.modules.agents.rescoring import rescore_leads

    out = await rescore_leads([lead["id"] for lead in ctx.leads[:MAX_LEADS]], workspace_id=ctx.workspace_id, trigger=f"routine:{ctx.routine.get('name')}")
    return {k: v for k, v in out.items() if k != "results"}


async def _refresh_listings(ctx: RunContext, params: dict[str, Any]) -> dict[str, Any]:
    """Mark listings not seen from any portal pull in ``stale_days`` as expired; report price moves."""
    props = table("properties", ctx.workspace_id)
    stale_days = float(params.get("stale_days") or 14)
    rows = await props.select(limit=min(int(params.get("limit") or 2000), 5000))
    expired = price_moves = active = 0
    for p in rows:
        if p.get("status") in ("expired", "sold", "rented"):
            continue
        seen = _hours_since(p.get("last_seen_at") or p.get("updated_at") or p.get("created_at"))
        if seen is not None and seen > stale_days * 24 and p.get("source") not in (None, "", "manual", "demo"):
            await props.update({"status": "expired", "expired_at": now_iso()}, id=p["id"])
            expired += 1
            continue
        active += 1
        prev, cur = p.get("previous_price_aed"), p.get("price_aed") or p.get("price")
        if prev and cur and prev != cur:
            price_moves += 1
            ctx.issues.append({"property_id": p["id"], "issue": "price_change", "from": prev, "to": cur})
    return {"active": active, "expired": expired, "price_changes": price_moves}


async def _execute_step(ctx: RunContext, step: dict[str, Any]) -> dict[str, Any]:
    t = step["type"]
    params = dict(step.get("params") or {})
    if t.startswith("connector.") or t == "voice.send_note":
        return await _connector_step(ctx, step)
    if t == "leads.select":
        return await _select_leads(ctx, params)
    if t == "viewings.select":
        return await _select_viewings(ctx, params)
    if t == "listings.validate":
        return await _validate_listings(ctx, params)
    if t == "llm.qualify":
        return await _llm_qualify(ctx, params, connection_id=step.get("connection_id"))
    if t == "llm.summarize":
        return await _llm_summarize(ctx, params)
    if t == "llm.draft_message":
        return await _llm_draft(ctx, params)
    if t == "tasks.create":
        return await _create_tasks(ctx, params)
    if t == "job.run":
        return await _run_job(ctx, params)
    if t == "analytics.query":
        return await _analytics_query(ctx, params)
    if t == "followups.schedule":
        return await _schedule_followups(ctx, params)
    if t == "leads.reject":
        return await _reject_leads(ctx, params)
    if t == "leads.rescore":
        return await _rescore(ctx, params)
    if t == "listings.refresh":
        return await _refresh_listings(ctx, params)
    return {"error": f"unknown step {t}"}


async def run_routine(workspace_id: str, routine_id: str, *, trigger: str = "manual", actor: str | None = None) -> Row:
    routines = table(TABLE, workspace_id)
    routine = await routines.get(id=routine_id)
    if not routine:
        raise LookupError("routine not found")
    runs = table(RUNS_TABLE, workspace_id)
    started = time.monotonic()
    run = await runs.insert(
        {
            "id": new_id(),
            "routine_id": routine_id,
            "routine_name": routine.get("name"),
            "trigger": trigger,
            "actor": actor,
            "status": "running",
            "started_at": now_iso(),
            "finished_at": None,
            "duration_ms": None,
            "steps": [],
            "summary": {},
            "error": None,
            "created_at": now_iso(),
        }
    )
    ctx = RunContext(workspace_id, routine)
    failed = 0
    for step in routine.get("steps") or []:
        t0 = time.monotonic()
        try:
            result = await _execute_step(ctx, step)
            status = "failed" if result.get("error") or result.get("ok") is False else "skipped" if result.get("skipped") else "simulated" if result.get("simulated") else "success"
            error = result.get("error") or result.get("reason") if status in ("failed", "skipped") else None
        except Exception as exc:
            logger.exception("routine step %s failed", step.get("type"))
            result, status, error = {}, "failed", f"{type(exc).__name__}: {exc}"[:300]
        failed += status == "failed"
        ctx.step_results.append(
            {
                "id": step.get("id"),
                "type": step["type"],
                "status": status,
                "summary": {k: v for k, v in result.items() if k not in ("error", "raw_ids")},
                "error": error,
                "duration_ms": int((time.monotonic() - t0) * 1000),
            }
        )
    status = "failed" if failed and failed == len(ctx.step_results) else "partial" if failed else "success"
    finished = {
        "status": status,
        "finished_at": now_iso(),
        "duration_ms": int((time.monotonic() - started) * 1000),
        "steps": ctx.step_results,
        "summary": {"leads": len(ctx.leads), "viewings": len(ctx.viewings), "listing_issues": len(ctx.issues), "digest": ctx.summary},
        "error": next((s["error"] for s in ctx.step_results if s["status"] == "failed"), None),
    }
    rows = await runs.update(finished, id=run["id"])
    await routines.update(
        {
            "run_count": int(routine.get("run_count") or 0) + 1,
            "last_run_at": now_iso(),
            "last_status": status,
            "next_run_at": next_run(routine.get("schedule") or {}) if routine.get("enabled") else None,
            "updated_at": now_iso(),
        },
        id=routine_id,
    )
    return rows[0] if rows else {**run, **finished}


async def run_due(workspace_id: str, *, limit: int = 20) -> dict[str, Any]:
    due = await due_routines(workspace_id, limit=limit)
    counts = {"due": len(due), "success": 0, "partial": 0, "failed": 0}
    for r in due:
        try:
            run = await run_routine(workspace_id, r["id"], trigger="schedule", actor="beat")
            counts[run["status"]] = counts.get(run["status"], 0) + 1
        except LookupError:
            continue
    return counts


# --------------------------------------------------------------------------- templates (researched broker workflows)

TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "daily_portal_sync",
        "name": "Daily live-listings sync",
        "category": "inventory",
        "description": "Every morning pull your live Property Finder listings into inventory, flag missing permits/photos and post a summary to the team.",
        "schedule": {"kind": "daily", "at": "07:30", "tz": "Asia/Dubai"},
        "steps": [
            {"type": "connector.pull_listings", "provider": "property_finder"},
            {"type": "listings.validate"},
            {"type": "llm.summarize", "params": {"focus": "listing quality and what to fix before publishing"}},
            {"type": "connector.notify", "provider": "slack"},
        ],
    },
    {
        "id": "portal_leads_to_crm",
        "name": "Portal leads → qualify → CRM",
        "category": "intake",
        "description": "Pull new portal / CRM leads hourly, AI-qualify them, push to the CRM of record and create broker tasks for hot ones.",
        "schedule": {"kind": "interval", "seconds": 3600},
        "steps": [
            {"type": "connector.pull_leads", "provider": "property_finder"},
            {"type": "leads.select", "params": {"created_within_hours": 2, "limit": 100}},
            {"type": "llm.qualify", "provider": "typesafe_jev"},
            {"type": "connector.push_leads", "provider": "realestate_crm"},
            {"type": "leads.select", "params": {"created_within_hours": 2, "band": "hot", "limit": 50}},
            {"type": "tasks.create", "params": {"title": "Call new hot lead {first_name}", "due_in_hours": 2}},
        ],
    },
    {
        "id": "stale_lead_reengage",
        "name": "Stale-lead WhatsApp re-engagement",
        "category": "engagement",
        "description": "Twice a week find qualified leads untouched for 5+ days, draft a personal WhatsApp in their language and send it (consent-checked).",
        "schedule": {"kind": "weekly", "weekday": 1, "at": "10:00", "tz": "Asia/Dubai"},
        "steps": [
            {"type": "leads.select", "params": {"stage": "qualified", "stale_hours": 120, "limit": 40}},
            {"type": "llm.draft_message", "params": {"channel": "WhatsApp", "tone": "warm, concise"}},
            {"type": "connector.send_message", "provider": "whatsapp", "params": {"use_drafts": True}},
            {"type": "tasks.create", "params": {"title": "Re-engaged {first_name} — check reply", "due_in_hours": 48}},
        ],
    },
    {
        "id": "viewing_calendar",
        "name": "Tomorrow's viewings → calendar + reminders",
        "category": "viewings",
        "description": "Each evening create Google Calendar events for the next 24h of viewings and WhatsApp the buyers a reminder.",
        "schedule": {"kind": "daily", "at": "18:00", "tz": "Asia/Dubai"},
        "steps": [
            {"type": "viewings.select", "params": {"within_hours": 30}},
            {"type": "connector.create_event", "provider": "google_calendar"},
            {"type": "connector.notify", "provider": "slack", "params": {"text": "Viewing schedule for tomorrow is in the calendar."}},
        ],
    },
    {
        "id": "morning_hot_digest",
        "name": "Morning hot-lead digest",
        "category": "reporting",
        "description": "At 08:00 list hot leads, AI-summarise what needs action and e-mail the team lead.",
        "schedule": {"kind": "daily", "at": "08:00", "tz": "Asia/Dubai"},
        "steps": [
            {"type": "leads.select", "params": {"band": "hot", "limit": 50}},
            {"type": "llm.qualify", "provider": "typesafe_jev"},
            {"type": "llm.summarize", "params": {"focus": "which hot leads to call first and why"}},
            {"type": "connector.send_email", "provider": "gmail", "params": {"subject": "Hot leads — today"}},
        ],
    },
    {
        "id": "crm_two_way_sync",
        "name": "CRM two-way sync",
        "category": "sync",
        "description": "Every 15 minutes poll CRM connectors and push score/stage changes back through the outbox.",
        "schedule": {"kind": "interval", "seconds": 900},
        "steps": [
            {"type": "job.run", "params": {"job_id": "poll_pull_connectors"}},
            {"type": "job.run", "params": {"job_id": "crm_writeback"}},
        ],
    },
    {
        "id": "weekly_performance",
        "name": "Weekly pipeline report",
        "category": "reporting",
        "description": "Monday 09:00: pipeline snapshot, stale leads, listing issues — summarised and posted to Slack.",
        "schedule": {"kind": "weekly", "weekday": 0, "at": "09:00", "tz": "Asia/Dubai"},
        "steps": [
            {"type": "leads.select", "params": {"stale_hours": 168, "limit": 200}},
            {"type": "listings.validate"},
            {"type": "llm.summarize", "params": {"focus": "weekly pipeline health, stale leads and listing hygiene"}},
            {"type": "connector.notify", "provider": "slack"},
        ],
    },
    {
        "id": "inbox_leads_to_crm",
        "name": "Portal e-mails & Meta ads → CRM",
        "category": "intake",
        "description": "Every 15 minutes read Bayut / Dubizzle / Property Finder e-mails and Meta Lead Ads, extract structured leads, score them and push new ones to your CRM.",
        "schedule": {"kind": "interval", "seconds": 900, "tz": "Asia/Dubai"},
        "steps": [
            {"type": "connector.pull_leads", "provider": "gmail"},
            {"type": "connector.pull_leads", "provider": "meta_lead_ads"},
            {"type": "leads.select", "params": {"created_within_hours": 1, "limit": 100}},
            {"type": "leads.rescore"},
            {"type": "connector.push_leads", "provider": "generic_crm"},
        ],
    },
    {
        "id": "voice_note_followup",
        "name": "Voice-note follow-up for warm leads",
        "category": "follow_up",
        "description": "Each afternoon, warm leads quiet for 2 days get a personalised AI voice note on WhatsApp and a follow-up cadence.",
        "schedule": {"kind": "daily", "at": "16:00", "tz": "Asia/Dubai"},
        "steps": [
            {"type": "leads.select", "params": {"band": "warm", "stale_hours": 48, "limit": 40}},
            {"type": "llm.draft_message", "params": {"channel": "voice", "tone": "warm", "language": "auto"}},
            {"type": "voice.send_note", "provider": "voice_notes"},
            {"type": "followups.schedule"},
        ],
    },
    {
        "id": "auto_reject_silent",
        "name": "Auto-close cold, silent leads",
        "category": "hygiene",
        "description": "Weekly: leads scored under 30 with no contact for 14 days are closed as lost and their follow-ups cancelled, keeping the pipeline honest.",
        "schedule": {"kind": "weekly", "at": "09:00", "weekday": 0, "tz": "Asia/Dubai"},
        "steps": [
            {"type": "leads.select", "params": {"band": "cold", "stale_hours": 336, "limit": 500}},
            {"type": "leads.reject", "params": {"max_score": 30, "stale_hours": 336}},
            {"type": "connector.notify", "provider": "slack"},
        ],
    },
    {
        "id": "listing_refresh",
        "name": "Listing refresh & price watch",
        "category": "inventory",
        "description": "Nightly: expire listings no portal has shown for 14 days and flag price changes so brokers re-pitch matching leads.",
        "schedule": {"kind": "daily", "at": "23:00", "tz": "Asia/Dubai"},
        "steps": [
            {"type": "connector.pull_listings", "provider": "property_finder"},
            {"type": "listings.refresh", "params": {"stale_days": 14}},
            {"type": "llm.summarize", "params": {"focus": "expired listings and price moves worth telling leads about"}},
        ],
    },
    {
        "id": "palm_demand_digest",
        "name": "Area demand digest",
        "category": "analytics",
        "description": "Monday morning: which areas are hottest this week and who is asking for Palm Jumeirah — e-mailed to the team.",
        "schedule": {"kind": "weekly", "at": "08:00", "weekday": 0, "tz": "Asia/Dubai"},
        "steps": [
            {"type": "analytics.query", "params": {"question": "which areas are most in demand this week"}},
            {"type": "analytics.query", "params": {"question": "who wants Palm Jumeirah", "limit": 10}},
            {"type": "llm.summarize", "params": {"focus": "demand shifts and the leads to prioritise"}},
            {"type": "connector.send_email", "provider": "gmail", "params": {"subject": "Weekly demand digest"}},
        ],
    },
    {
        "id": "compliance_retention",
        "name": "PDPL retention sweep",
        "category": "compliance",
        "description": "Nightly retention purge plus a note to the team when records were anonymised.",
        "schedule": {"kind": "daily", "at": "02:00", "tz": "Asia/Dubai"},
        "steps": [
            {"type": "job.run", "params": {"job_id": "retention_purge"}},
            {"type": "connector.notify", "provider": "slack", "params": {"text": "Nightly PDPL retention sweep completed."}},
        ],
    },
]


async def instantiate_template(workspace_id: str, template_id: str, *, actor: str | None) -> Row:
    tpl = next((t for t in TEMPLATES if t["id"] == template_id), None)
    if not tpl:
        raise LookupError("template not found")
    existing = await conn.list_connections(workspace_id)
    by_provider: dict[str, str] = {}
    for c in existing:
        by_provider.setdefault(c["provider"], c["id"])
    steps = [
        Step(type=s["type"], connection_id=by_provider.get(s.get("provider") or ""), params=dict(s.get("params") or {}))
        for s in tpl["steps"]
    ]
    body = RoutineIn(name=tpl["name"], description=tpl["description"], schedule=Schedule(**tpl["schedule"]), steps=steps, enabled=False, template_id=tpl["id"])
    return await create_routine(workspace_id, body, actor=actor)


def step_catalog() -> dict[str, Any]:
    from app.modules.cowork.jobs import JOBS

    return {
        "steps": [{"type": k, **v} for k, v in STEP_TYPES.items()],
        "templates": TEMPLATES,
        "stages": list(PIPELINE_STAGES),
        "jobs": [{"id": j.id, "label": j.label} for j in JOBS if j.id not in FORBIDDEN_JOBS],
    }
