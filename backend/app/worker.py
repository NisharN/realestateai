"""Celery worker: scheduled ingestion and the reminders engine.

Two things were broken here before and are fixed in this file:

1. ``run_ingestion_schedule`` fetched the schedule row and then stopped at a
   comment — it never called ``PropertyIngestionService``, so no scheduled
   import ever actually ran. That was the cause of the reported "schedule"
   error: creating a schedule succeeded (it's just a DB insert) but nothing
   ever executed it.
2. ``docker-compose.yml`` defined no worker and no beat service, so even a
   correct task had no process to run it. Both services are now declared.

This is also where the hardcoded workflow templates get executed. There is no
visual workflow builder (see docs/workflow_builder_validation.md) — the pure
decision logic lives in ``app.services.workflows`` and this module is the
thing that runs it on a timer and performs the resulting side effects.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from celery import Celery

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
celery_app = Celery(
    "dubai_real_estate_ai",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Dubai",
    enable_utc=True,
    beat_schedule={
        "dispatch-due-ingestion-schedules": {
            "task": "app.worker.dispatch_due_ingestion_schedules",
            "schedule": 60.0,
        },
        "run-workflow-templates": {
            "task": "app.worker.run_workflow_templates",
            "schedule": 300.0,  # every 5 minutes
        },
        "reassign-stale-handoffs": {
            "task": "app.worker.reassign_stale_handoffs",
            "schedule": 60.0,
        },
        "send-due-followups": {
            "task": "app.worker.send_due_followups",
            "schedule": 300.0,
        },
        "retry-ingestion-errors": {
            "task": "app.worker.retry_ingestion_errors",
            "schedule": 120.0,
        },
        "poll-pull-connectors": {
            "task": "app.worker.poll_pull_connectors",
            "schedule": 60.0,
        },
    },
)


def _run_async(coro):
    """Run an async coroutine from a synchronous Celery task."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():  # pragma: no cover - not expected in a worker
            raise RuntimeError("loop already running")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# --------------------------------------------------------------------------
# Ingestion scheduling
# --------------------------------------------------------------------------

@celery_app.task(name="app.worker.dispatch_due_ingestion_schedules")
def dispatch_due_ingestion_schedules() -> int:
    """Select due schedules and hand each to a worker."""
    from app.database import DatabaseClient

    client = DatabaseClient.get_client()
    if client is None:
        logger.debug("No database client; skipping ingestion dispatch")
        return 0

    now = datetime.now(timezone.utc).isoformat()
    due = (
        client.table("ingestion_schedules")
        .select("id,workspace_id")
        .eq("enabled", True)
        .lte("next_run_at", now)
        .execute()
        .data
    ) or []

    for schedule in due:
        run_ingestion_schedule.delay(schedule["workspace_id"], schedule["id"])
    return len(due)


@celery_app.task(bind=True, max_retries=5, name="app.worker.run_ingestion_schedule")
def run_ingestion_schedule(self, workspace_id: str, schedule_id: str) -> Dict[str, Any]:
    """Actually execute one ingestion schedule.

    Previously a stub. Now resolves the schedule's source and runs the real
    ``PropertyIngestionService``, records a job run, and advances (or on
    repeated failure, disables) the schedule.
    """
    from app.database import DatabaseClient, get_property_repository
    from app.services.ingestion_jobs import failure_transition, retry_delay_seconds
    from app.services.property_ingestion import PropertyIngestionService

    client = DatabaseClient.get_client()
    if client is None:
        raise self.retry(countdown=retry_delay_seconds(self.request.retries + 1))

    schedule = (
        client.table("ingestion_schedules")
        .select("*")
        .eq("workspace_id", workspace_id)
        .eq("id", schedule_id)
        .eq("enabled", True)
        .maybe_single()
        .execute()
        .data
    )
    if not schedule:
        return {"status": "skipped", "reason": "schedule_not_found_or_disabled"}

    source = schedule.get("source") or "approved_feed"
    started_at = datetime.now(timezone.utc)

    try:
        service = PropertyIngestionService(get_property_repository(workspace_id))
        result = _run_async(_execute_source(service, source, schedule))
        _record_job_run(client, workspace_id, schedule_id, "succeeded", started_at, result, self.request.id)
        _advance_schedule(client, workspace_id, schedule_id, schedule)
        return {"status": "succeeded", "source": source, **result}

    except Exception as exc:
        logger.error("Ingestion schedule %s failed: %s", schedule_id, exc)
        _record_job_run(
            client, workspace_id, schedule_id, "failed", started_at, {"error": str(exc)}, self.request.id
        )
        transition = failure_transition(
            consecutive_failures=int(schedule.get("consecutive_failures") or 0),
            error_code=type(exc).__name__,
            now=datetime.now(timezone.utc),
        )
        client.table("ingestion_schedules").update(transition).eq(
            "workspace_id", workspace_id
        ).eq("id", schedule_id).execute()

        if transition["enabled"]:
            raise self.retry(countdown=retry_delay_seconds(self.request.retries + 1))
        return {"status": "failed", "disabled": True, "error": str(exc)}


async def _execute_source(service: Any, source: str, schedule: Dict[str, Any]) -> Dict[str, Any]:
    """Route a schedule to the right ingestion path.

    Mock mode is honoured here: a scheduled import in a demo deployment
    re-seeds from the bundled dataset rather than calling anything external,
    so the scheduler is demonstrably working without any API keys.
    """
    config = schedule.get("config") or {}

    if get_settings().properties_mode == "mock":
        from app.seed_data import mock_property_records

        return await service.import_records(
            source="mock_seed", records=mock_property_records(), dedupe=True
        )

    if source == "approved_feed":
        from app.scrapers import scrape_approved_feed

        records = await scrape_approved_feed(**config)
        return await service.import_records(source=source, records=records, dedupe=True)

    if source == "rapidapi_uae":
        from app.scrapers import scrape_rapidapi_properties

        records = await scrape_rapidapi_properties(
            endpoint=config.get("endpoint", "properties/list"),
            params=config.get("params"),
        )
        return await service.import_records(source=source, records=records, dedupe=True)

    raise ValueError(f"Unsupported ingestion source: {source}")


def _record_job_run(
    client: Any,
    workspace_id: str,
    schedule_id: str,
    status: str,
    started_at: datetime,
    result: Dict[str, Any],
    task_id: str | None = None,
) -> None:
    try:
        client.table("job_runs").insert(
            job_run_row(workspace_id, schedule_id, status, started_at, result, task_id)
        ).execute()
    except Exception as exc:
        logger.warning("Could not record job run for schedule %s: %s", schedule_id, exc)


def job_run_row(
    workspace_id: str,
    schedule_id: str,
    status: str,
    started_at: datetime,
    result: Dict[str, Any],
    task_id: str | None = None,
) -> Dict[str, Any]:
    """Row for ``job_runs`` matching the migration (idempotency_key + summary)."""
    return {
        "workspace_id": workspace_id,
        "schedule_id": schedule_id,
        "idempotency_key": task_id or f"{schedule_id}:{started_at.isoformat()}",
        "status": status,
        "attempts": 1,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "error_code": result.get("error") if status == "failed" else None,
        "summary": result,
    }


def _advance_schedule(
    client: Any, workspace_id: str, schedule_id: str, schedule: Dict[str, Any]
) -> None:
    """Reset failure state and set the next run time."""
    now = datetime.now(timezone.utc)
    client.table("ingestion_schedules").update(
        advance_schedule_row(schedule, now)
    ).eq("workspace_id", workspace_id).eq("id", schedule_id).execute()


def advance_schedule_row(schedule: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    config = schedule.get("config") or {}
    interval_minutes = int(config.get("interval_minutes") or 60)
    return {
        "consecutive_failures": 0,
        "last_error_code": None,
        "last_success_at": now.isoformat(),
        "next_run_at": (now + timedelta(minutes=interval_minutes)).isoformat(),
        "updated_at": now.isoformat(),
    }


# --------------------------------------------------------------------------
# Reminders engine
# --------------------------------------------------------------------------

@celery_app.task(name="app.worker.run_workflow_templates")
def run_workflow_templates() -> Dict[str, int]:
    """Evaluate the enabled workflow templates and perform their actions."""
    return _run_async(_run_workflow_templates_async())


async def _run_workflow_templates_async() -> Dict[str, int]:
    from app.database import DatabaseClient, current_workspace_id
    from app.services import workflows as wf
    from app.services.whatsapp import get_whatsapp_service
    from app.services.workflow_inputs import load_workflow_inputs

    cfg = get_settings()
    workspace_id = current_workspace_id()
    now = datetime.now(timezone.utc)
    ws = wf.WorkflowSettings.from_settings(cfg)

    client = DatabaseClient.get_client()
    # Same loader the /workflows/preview endpoint uses, so what a broker is
    # shown as "pending" is exactly what actually gets executed.
    leads, viewings, mandates, listings = await load_workflow_inputs(workspace_id)

    actions: List[wf.WorkflowAction] = []
    enabled = set(ws.enabled)
    if wf.WorkflowTemplate.NEW_LEAD_FOLLOWUP in enabled:
        actions += wf.evaluate_new_lead_followup(leads, now, ws)
    if wf.WorkflowTemplate.VIEWING_REMINDER in enabled:
        actions += wf.evaluate_viewing_reminders(viewings, now, ws)
    if wf.WorkflowTemplate.POST_VIEWING_NUDGE in enabled:
        actions += wf.evaluate_post_viewing_nudge(viewings, now, ws)
    if wf.WorkflowTemplate.MANDATE_RENEWAL in enabled:
        actions += wf.evaluate_mandate_renewals(mandates, now, ws)
    if wf.WorkflowTemplate.LISTING_STALE in enabled:
        actions += wf.evaluate_listing_staleness(listings, now, ws)

    whatsapp = get_whatsapp_service()
    counts: Dict[str, int] = {"evaluated": len(actions)}

    for action in actions:
        action = wf.gate_voice_action(
            action,
            voice_outbound_enabled=cfg.VOICE_OUTBOUND_ENABLED,
            require_human_approval=cfg.VOICE_REQUIRE_HUMAN_APPROVAL,
        )
        key = action.action.value
        counts[key] = counts.get(key, 0) + 1

        if action.action == wf.ActionType.SEND_WHATSAPP and action.recipient:
            await whatsapp.send_text(
                to=action.recipient,
                body=action.message or "",
                lead_id=action.subject_id if action.subject_type == "lead" else None,
            )
        elif action.action == wf.ActionType.GENERATE_LISTING_COPY:
            await _generate_and_store_copy(client, workspace_id, action, listings)

    logger.info("Workflow run complete: %s", counts)
    return counts


async def _generate_and_store_copy(
    client: Any,
    workspace_id: str,
    action: Any,
    listings: List[Dict[str, Any]],
) -> None:
    """Generate refreshed listing copy for the broker to paste. Never posts."""
    from app.services.listing_refresh import generate_refresh_copy, polish_with_llm

    listing = next((l for l in listings if str(l.get("id")) == action.subject_id), None)
    if listing is None:
        return

    copy = generate_refresh_copy(
        listing,
        days_stale=int(action.metadata.get("days_stale", 0)),
        refresh_count=int(listing.get("refresh_count") or 0),
    )
    copy = await polish_with_llm(copy)

    if client is None:
        logger.info("[listing-refresh:mock] %s -> %s", copy.property_id, copy.description[:80])
        return
    try:
        payload = copy.to_dict()
        payload["workspace_id"] = workspace_id
        client.table("listing_refresh_suggestions").insert(payload).execute()
    except Exception as exc:
        logger.debug("Could not store refresh suggestion: %s", exc)


# --------------------------------------------------------------------------
# Handoff / follow-up / ingestion timers (single-tenant: WORKSPACE_ID)
# --------------------------------------------------------------------------

@celery_app.task(name="app.worker.reassign_stale_handoffs")
def reassign_stale_handoffs() -> int:
    from app.modules.handoff.service import reassign_stale

    return len(_run_async(reassign_stale(settings.WORKSPACE_ID)))


@celery_app.task(name="app.worker.send_due_followups")
def send_due_followups() -> int:
    from app.modules.handoff.followups import send_due

    return len(_run_async(send_due(settings.WORKSPACE_ID)))


@celery_app.task(name="app.worker.retry_ingestion_errors")
def retry_ingestion_errors() -> int:
    from app.modules.ingestion.pipeline.processor import process_stranded, retry_errors

    async def _run() -> int:
        ws = settings.WORKSPACE_ID
        return len(await retry_errors(ws)) + len(await process_stranded(ws))

    return _run_async(_run())


@celery_app.task(name="app.worker.poll_pull_connectors")
def poll_pull_connectors() -> int:
    """Pull every due CRM connector, land its records, then process them."""
    from app.modules.ingestion.connectors.crm_pull import due_pull_connectors, poll_connector

    async def _run() -> int:
        ws = settings.WORKSPACE_ID
        landed = 0
        for connector in await due_pull_connectors(ws):
            result = await poll_connector(connector["id"], workspace_id=ws)
            ids = result.get("raw_ids", [])
            if ids:
                process_raw_records.delay(ws, ids)
            landed += len(ids)
        return landed

    return _run_async(_run())


@celery_app.task(name="app.worker.process_raw_records")
def process_raw_records(workspace_id: str, raw_ids: list[str]) -> int:
    from app.modules.ingestion.pipeline.processor import process_many

    return len(_run_async(process_many(raw_ids, workspace_id=workspace_id)))
