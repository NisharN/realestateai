"""Task automations: small, auditable "when X then Y" rules over lead events.

This is deliberately not a graph builder. A rule is one trigger, an optional
set of field conditions, and one action from a fixed catalogue. Rules are
evaluated by the ``run_automations`` job as an idempotent outbox consumer over
``lead_events`` (see ``app.modules.ingestion.events``), so redelivery never
fires an action twice, and every firing is written to ``cowork_automation_runs``
for the audit trail.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.database import get_lead_repository
from app.modules.cowork.jobs import JOB_INDEX, run_job
from app.modules.ingestion import events
from app.modules.leads.stages import PIPELINE_STAGES
from app.modules.store import Row, new_id, now_iso, table

logger = logging.getLogger(__name__)

CONSUMER = "cowork_automations"
RULES_TABLE = "cowork_automations"
RUNS_TABLE = "cowork_automation_runs"
TASKS_TABLE = "cowork_tasks"

TriggerType = Literal["lead.created", "lead.updated", "lead.scored", "handoff.created", "handoff.accepted", "handoff.reassigned", "viewing.confirmed"]
ActionType = Literal["create_task", "notify_broker", "schedule_followups", "set_stage", "run_job"]
Operator = Literal["eq", "ne", "gte", "lte", "in", "contains", "exists"]

TRIGGERS: dict[str, str] = {
    "lead.created": "A new lead is created (any connector, chat, WhatsApp)",
    "lead.updated": "An existing lead is updated by a connector",
    "lead.scored": "The conversation engine re-scores a lead",
    "handoff.created": "A lead is handed off to a broker",
    "handoff.accepted": "A broker accepts a handoff",
    "handoff.reassigned": "A stale handoff is rerouted",
    "viewing.confirmed": "A viewing is confirmed",
}
ACTIONS: dict[str, str] = {
    "create_task": "Create a task for the assigned broker (or unassigned queue)",
    "notify_broker": "WhatsApp the assigned broker",
    "schedule_followups": "Schedule the follow-up cadence for the lead's band",
    "set_stage": "Move the lead to a stage",
    "run_job": "Run a Co-work job now",
}
CONDITION_FIELDS = ("score", "band", "stage", "status", "source", "purpose", "timeline", "budget_max_aed", "assigned_broker", "language", "area_preference")
TEMPLATE_FIELDS = ("first_name", "last_name", "stage", "score", "band", "source", "area_preference", "budget_max_aed", "purpose")
# Jobs an automation may never target: the automation job itself would re-enter
# the same pending event before its offset is written.
FORBIDDEN_JOBS = frozenset({"run_automations", "run_routines"})
MAX_ATTEMPTS = 3
STALE_CLAIM_S = 600

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def render_template(template: str, lead: Row) -> str:
    """Substitute ``{field}`` placeholders from a fixed whitelist of lead fields.

    Unlike ``str.format`` this cannot traverse attributes/indices or evaluate
    format specs, so admin-authored templates cannot reach into objects.
    """

    def repl(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in TEMPLATE_FIELDS:
            return m.group(0)
        v = _get(lead, key)
        return "" if v is None else str(v)

    return _PLACEHOLDER.sub(repl, template)


def validate_action(action: str, params: dict[str, Any]) -> None:
    if action == "set_stage":
        stage = str(params.get("stage") or "").strip()
        if stage not in PIPELINE_STAGES:
            raise ValueError(f"stage must be one of {', '.join(PIPELINE_STAGES)}")
    elif action == "run_job":
        job_id = str(params.get("job_id") or "")
        if job_id in FORBIDDEN_JOBS:
            raise ValueError(f"automations cannot run job {job_id!r}")
        if job_id not in JOB_INDEX:
            raise ValueError(f"unknown job {job_id!r}")


class Condition(BaseModel):
    field: str = Field(..., max_length=64)
    op: Operator = "eq"
    value: Any = None


class AutomationIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(None, max_length=500)
    trigger: TriggerType
    conditions: list[Condition] = Field(default_factory=list, max_length=10)
    action: ActionType
    action_params: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True

    @model_validator(mode="after")
    def _check_action(self) -> AutomationIn:
        validate_action(self.action, self.action_params)
        return self


class AutomationPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=500)
    trigger: TriggerType | None = None
    conditions: list[Condition] | None = None
    action: ActionType | None = None
    action_params: dict[str, Any] | None = None
    enabled: bool | None = None


def _get(lead: Row, field: str) -> Any:
    v = lead.get(field)
    if field == "band" and v is None:
        score = lead.get("score") or lead.get("intent_score")
        if isinstance(score, (int, float)):
            v = "hot" if score >= 70 else "warm" if score >= 40 else "cold"
    return v


def event_view(lead: Row, event: Row) -> Row:
    """Lead as it was when ``event`` was emitted: the current row overlaid with
    the snapshot captured in the event payload (see ``events.emit``)."""
    snap = (event.get("payload") or {}).get("lead") or {}
    return {**lead, **snap} if snap else lead


def matches(conditions: list[dict[str, Any]], lead: Row) -> bool:
    for c in conditions:
        actual, op, expected = _get(lead, c["field"]), c.get("op", "eq"), c.get("value")
        if op == "exists":
            if (actual not in (None, "", [])) != bool(expected if expected is not None else True):
                return False
        elif op == "eq":
            if actual != expected:
                return False
        elif op == "ne":
            if actual == expected:
                return False
        elif op in ("gte", "lte"):
            try:
                a, e = float(actual), float(expected)
            except (TypeError, ValueError):
                return False
            if (op == "gte" and a < e) or (op == "lte" and a > e):
                return False
        elif op == "in":
            if actual not in (expected or []):
                return False
        elif op == "contains":
            if isinstance(actual, list):
                if expected not in actual:
                    return False
            elif expected is None or str(expected).lower() not in str(actual or "").lower():
                return False
    return True


async def list_rules(workspace_id: str) -> list[Row]:
    return await table(RULES_TABLE, workspace_id).select(order="created_at", limit=200)


async def create_rule(workspace_id: str, body: AutomationIn, *, actor: str | None) -> Row:
    row = {
        "id": new_id(),
        **body.model_dump(),
        "conditions": [c.model_dump() for c in body.conditions],
        "created_by": actor,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "run_count": 0,
        "last_run_at": None,
        "last_status": None,
    }
    return await table(RULES_TABLE, workspace_id).insert(row)


async def patch_rule(workspace_id: str, rule_id: str, body: AutomationPatch) -> Row | None:
    t = table(RULES_TABLE, workspace_id)
    current = await t.get(id=rule_id)
    if not current:
        return None
    updates = {k: v for k, v in body.model_dump(exclude_unset=True).items()}
    if "conditions" in updates and updates["conditions"] is not None:
        updates["conditions"] = [c.model_dump() if isinstance(c, Condition) else c for c in body.conditions or []]
    if "action" in updates or "action_params" in updates:
        validate_action(updates.get("action") or current["action"], updates.get("action_params") or current.get("action_params") or {})
    updates["updated_at"] = now_iso()
    rows = await t.update(updates, id=rule_id)
    return rows[0] if rows else None


async def delete_rule(workspace_id: str, rule_id: str) -> bool:
    return (await table(RULES_TABLE, workspace_id).delete(id=rule_id)) > 0


async def _apply(rule: Row, lead: Row, event: Row, workspace_id: str) -> dict[str, Any]:
    params = rule.get("action_params") or {}
    action = rule["action"]
    repo = get_lead_repository(workspace_id)
    if action == "create_task":
        task = await table(TASKS_TABLE, workspace_id).insert(
            {
                "id": new_id(),
                "lead_id": lead["id"],
                "broker_id": lead.get("assigned_broker"),
                "title": render_template(str(params.get("title") or f"Follow up with {lead.get('first_name') or 'lead'}"), lead),
                "due_in_hours": int(params.get("due_in_hours") or 24),
                "status": "open",
                "automation_id": rule["id"],
                "created_at": now_iso(),
            }
        )
        return {"task_id": task["id"]}
    if action == "notify_broker":
        from app.modules.handoff.service import _brokers
        from app.services.whatsapp import get_whatsapp_service

        broker = next((b for b in await _brokers(workspace_id) if b.id == lead.get("assigned_broker")), None)
        if not broker or not broker.phone:
            return {"skipped": "no_assigned_broker_phone"}
        text = render_template(str(params.get("message") or "Lead {first_name} needs attention (stage {stage}, score {score})."), lead)
        msg = await get_whatsapp_service().send_text(broker.phone, text, lead_id=lead["id"])
        return {"message_status": msg.status}
    if action == "schedule_followups":
        from app.modules.handoff.followups import schedule_followups

        band = str(params.get("band") or _get(lead, "band") or "warm")
        rows = await schedule_followups(lead["id"], band, workspace_id=workspace_id)
        return {"scheduled": len(rows), "band": band}
    if action == "set_stage":
        stage = str(params.get("stage") or "").strip()
        if stage not in PIPELINE_STAGES:
            raise ValueError(f"invalid stage {stage!r}")
        await repo.update(lead["id"], {"stage": stage})
        return {"stage": stage}
    if action == "run_job":
        job_id = str(params.get("job_id") or "")
        if job_id in FORBIDDEN_JOBS:
            raise ValueError(f"automations cannot run job {job_id!r}")
        run = await run_job(workspace_id, job_id, trigger="automation", actor=rule["id"])
        return {"job_run_id": run.get("id"), "job_status": run["status"]}
    return {"skipped": f"unknown_action:{action}"}


async def _claim(workspace_id: str, rule: Row, event: Row) -> Row | None:
    """Durable per-rule/event claim. Exactly one process gets a fresh ``running``
    row (unique on automation_id+event_id); everyone else sees the existing row."""
    runs = table(RUNS_TABLE, workspace_id)
    existing = await runs.get(automation_id=rule["id"], event_id=event.get("id"))
    if existing:
        return None
    row = {
        "id": new_id(),
        "automation_id": rule["id"],
        "automation_name": rule.get("name"),
        "event_id": event.get("id"),
        "event_type": event.get("type"),
        "lead_id": event.get("lead_id"),
        "status": "running",
        "attempts": 0,
        "result": {},
        "error": None,
        "created_at": now_iso(),
    }
    try:
        return await runs.insert(row)
    except Exception as exc:  # unique violation: another worker claimed it first
        logger.info("automation %s already claimed event %s: %s", rule["id"], event.get("id"), exc)
        return None


async def _settle(workspace_id: str, rule: Row, run: Row, status: str, result: dict[str, Any] | None, error: str | None) -> None:
    attempts = int(run.get("attempts") or 0) + 1
    await table(RUNS_TABLE, workspace_id).update(
        {"status": status, "attempts": attempts, "result": result or {}, "error": error, "updated_at": now_iso()}, id=run["id"]
    )
    await table(RULES_TABLE, workspace_id).update(
        {"run_count": int(rule.get("run_count") or 0) + 1, "last_run_at": now_iso(), "last_status": status}, id=rule["id"]
    )
    rule["run_count"] = int(rule.get("run_count") or 0) + 1


async def _execute(workspace_id: str, rule: Row, lead: Row, event: Row, run: Row) -> bool:
    try:
        result = await _apply(rule, lead, event, workspace_id)
    except Exception as exc:  # one bad rule must not block the outbox
        logger.warning("automation %s failed on %s: %s", rule["id"], event.get("id"), exc)
        await _settle(workspace_id, rule, run, "failed", None, str(exc)[:500])
        return False
    await _settle(workspace_id, rule, run, "fired", result, None)
    return True


async def retry_failed(workspace_id: str, rules: dict[str, Row], *, limit: int = 100) -> dict[str, int]:
    """Re-run failed firings (and claims abandoned by a crashed worker) up to
    ``MAX_ATTEMPTS``; the shared event offset has already advanced, so this is
    what makes a transient WhatsApp/storage error recoverable."""
    runs_t = table(RUNS_TABLE, workspace_id)
    events_t = table("lead_events", workspace_id)
    repo = get_lead_repository(workspace_id)
    stale_before = (datetime.now(timezone.utc) - timedelta(seconds=STALE_CLAIM_S)).isoformat()
    candidates = await runs_t.select(status="failed", attempts__lte=MAX_ATTEMPTS - 1, order="created_at", limit=limit)
    candidates += [r for r in await runs_t.select(status="running", order="created_at", limit=limit) if (r.get("updated_at") or r.get("created_at") or "") < stale_before]
    retried = recovered = 0
    for run in candidates:
        rule = rules.get(run["automation_id"])
        event = await events_t.get(id=run.get("event_id")) if run.get("event_id") else None
        lead = await repo.get_by_id(run["lead_id"]) if run.get("lead_id") else None
        if not rule or not event or not lead:
            continue
        retried += 1
        if await _execute(workspace_id, rule, lead, event, run):
            recovered += 1
    return {"retried": retried, "recovered": recovered}


async def run_automations(workspace_id: str, limit: int = 200) -> dict[str, Any]:
    rules = [r for r in await list_rules(workspace_id) if r.get("enabled")]
    fired = skipped = failed = 0
    if not rules:
        # Still advance the offset so a later rule does not replay history.
        async def noop(_: Row) -> None:
            return None

        seen = await events.consume(workspace_id, CONSUMER, noop, limit=limit)
        return {"events": seen, "fired": 0, "skipped": 0, "failed": 0, "rules": 0, "retried": 0, "recovered": 0}

    repo = get_lead_repository(workspace_id)
    by_trigger: dict[str, list[Row]] = {}
    for r in rules:
        by_trigger.setdefault(r["trigger"], []).append(r)

    async def handler(event: Row) -> None:
        nonlocal fired, skipped, failed
        candidates = by_trigger.get(event.get("type") or "", [])
        if not candidates:
            return
        lead = await repo.get_by_id(event["lead_id"])
        if not lead:
            return
        at_event = event_view(lead, event)
        for rule in candidates:
            if not matches(rule.get("conditions") or [], at_event):
                skipped += 1
                continue
            run = await _claim(workspace_id, rule, event)
            if run is None:
                continue
            if await _execute(workspace_id, rule, lead, event, run):
                fired += 1
            else:
                failed += 1

    seen = await events.consume(workspace_id, CONSUMER, handler, limit=limit)
    retry = await retry_failed(workspace_id, {r["id"]: r for r in rules})
    return {"events": seen, "fired": fired, "skipped": skipped, "failed": failed, "rules": len(rules), **retry}


async def test_rule(workspace_id: str, rule: Row, *, limit: int = 200) -> dict[str, Any]:
    """Dry run: which current leads would this rule match right now? Never acts."""
    leads = await get_lead_repository(workspace_id).list_all(limit=limit)
    hits = [l for l in leads if matches(rule.get("conditions") or [], l)]
    return {
        "checked": len(leads),
        "matched": len(hits),
        "sample": [{"id": l["id"], "name": f"{l.get('first_name') or ''} {l.get('last_name') or ''}".strip(), "stage": l.get("stage"), "score": l.get("score")} for l in hits[:10]],
    }


async def list_runs(workspace_id: str, *, automation_id: str | None = None, limit: int = 50) -> list[Row]:
    filters: dict[str, Any] = {}
    if automation_id:
        filters["automation_id"] = automation_id
    return await table(RUNS_TABLE, workspace_id).select(order="created_at", desc=True, limit=min(limit, 200), **filters)


async def list_tasks(workspace_id: str, *, status: str | None = None, limit: int = 100) -> list[Row]:
    filters: dict[str, Any] = {}
    if status:
        filters["status"] = status
    return await table(TASKS_TABLE, workspace_id).select(order="created_at", desc=True, limit=min(limit, 500), **filters)


async def update_task(workspace_id: str, task_id: str, *, status: str) -> Row | None:
    rows = await table(TASKS_TABLE, workspace_id).update({"status": status, "updated_at": now_iso()}, id=task_id)
    return rows[0] if rows else None
