"""Co-work: job registry, run history, task automations and the aggregated API."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import get_lead_repository
from app.main import app
from app.modules.cowork import automations, jobs
from app.modules.ingestion import events
from app.modules.store import reset_memory, table

client = TestClient(app, raise_server_exceptions=False)
WS = get_settings().WORKSPACE_ID


@pytest.fixture(autouse=True)
def _clean():
    reset_memory()
    yield
    reset_memory()


# ---------------------------------------------------------------- jobs


def test_job_registry_matches_beat_expectations():
    ids = {j.id for j in jobs.JOBS}
    assert {"poll_pull_connectors", "retry_ingestion_errors", "send_due_followups", "crm_writeback", "retention_purge", "run_automations"} <= ids
    assert all(j.default_interval_s >= 30 for j in jobs.JOBS)


@pytest.mark.asyncio
async def test_run_job_records_success_and_is_due_honours_interval():
    run = await jobs.run_job(WS, "retry_ingestion_errors", trigger="manual", actor="u1")
    assert run["status"] == "success"
    assert run["summary"] == {"retried": 0, "stranded": 0}
    assert run["duration_ms"] is not None and run["finished_at"]

    assert await jobs.is_due(WS, "retry_ingestion_errors") is False  # just ran (120s interval)
    listed = await jobs.list_jobs(WS)
    job = next(j for j in listed if j["id"] == "retry_ingestion_errors")
    assert job["last_run"]["id"] == run["id"] and job["next_run_at"]


@pytest.mark.asyncio
async def test_disabled_job_is_never_due_and_settings_persist():
    updated = await jobs.update_job(WS, "crm_writeback", enabled=False, interval_s=10)
    assert updated["enabled"] is False
    assert updated["interval_s"] == 30  # clamped to the floor
    assert await jobs.is_due(WS, "crm_writeback") is False
    assert await jobs.run_if_due(WS, "crm_writeback") is None
    job = next(j for j in await jobs.list_jobs(WS) if j["id"] == "crm_writeback")
    assert job["enabled"] is False and job["next_run_at"] is None


@pytest.mark.asyncio
async def test_failed_job_is_recorded_not_raised(monkeypatch):
    async def boom(_: str) -> dict:
        raise RuntimeError("connector exploded")

    spec = jobs.JOB_INDEX["poll_pull_connectors"]
    monkeypatch.setitem(jobs.JOB_INDEX, "poll_pull_connectors", jobs.JobSpec(spec.id, spec.label, spec.description, spec.category, spec.default_interval_s, boom))
    run = await jobs.run_job(WS, "poll_pull_connectors")
    assert run["status"] == "failed" and "connector exploded" in run["error"]
    stats = await jobs.run_stats(WS)
    assert stats["runs"] == 1 and stats["failed"] == 1 and stats["last_failure"]["id"] == run["id"]


def test_unknown_job_raises():
    with pytest.raises(KeyError):
        jobs.get_spec("nope")


# ---------------------------------------------------------------- automations


def _rule(**overrides) -> automations.AutomationIn:
    base = {
        "name": "Hot lead task",
        "trigger": "lead.scored",
        "conditions": [{"field": "score", "op": "gte", "value": 70}],
        "action": "create_task",
        "action_params": {"title": "Call {first_name} now", "due_in_hours": 2},
    }
    base.update(overrides)
    return automations.AutomationIn(**base)


def test_condition_matching():
    lead = {"score": 82, "stage": "qualified", "area_preference": ["Dubai Marina"], "assigned_broker": None}
    assert automations.matches([{"field": "score", "op": "gte", "value": 70}], lead)
    assert not automations.matches([{"field": "score", "op": "lte", "value": 50}], lead)
    assert automations.matches([{"field": "band", "op": "eq", "value": "hot"}], lead)
    assert automations.matches([{"field": "stage", "op": "in", "value": ["qualified", "handed_off"]}], lead)
    assert automations.matches([{"field": "area_preference", "op": "contains", "value": "Dubai Marina"}], lead)
    assert automations.matches([{"field": "assigned_broker", "op": "exists", "value": False}], lead)
    assert not automations.matches([{"field": "assigned_broker", "op": "exists", "value": True}], lead)
    assert not automations.matches([{"field": "score", "op": "gte", "value": "x"}], lead)


@pytest.mark.asyncio
async def test_automation_fires_once_per_event_and_is_audited():
    repo = get_lead_repository(WS)
    hot = await repo.create({"first_name": "Amina", "phone": "+971500000001", "source": "crm", "status": "new", "score": 85})
    cold = await repo.create({"first_name": "Bob", "phone": "+971500000002", "source": "crm", "status": "new", "score": 20})
    rule = await automations.create_rule(WS, _rule(), actor="admin")

    await events.emit(hot["id"], "lead.scored", {}, workspace_id=WS)
    await events.emit(cold["id"], "lead.scored", {}, workspace_id=WS)
    await events.emit(hot["id"], "lead.updated", {}, workspace_id=WS)  # different trigger

    result = await automations.run_automations(WS)
    assert result == {"events": 3, "fired": 1, "skipped": 1, "failed": 0, "rules": 1}

    tasks = await automations.list_tasks(WS)
    assert len(tasks) == 1
    assert tasks[0]["title"] == "Call Amina now" and tasks[0]["lead_id"] == hot["id"] and tasks[0]["due_in_hours"] == 2

    runs = await automations.list_runs(WS)
    assert len(runs) == 1 and runs[0]["status"] == "fired" and runs[0]["automation_id"] == rule["id"]
    stored = await table(automations.RULES_TABLE, WS).get(id=rule["id"])
    assert stored["run_count"] == 1 and stored["last_status"] == "fired"

    # Re-running does not replay consumed events.
    again = await automations.run_automations(WS)
    assert again["events"] == 0 and len(await automations.list_tasks(WS)) == 1


@pytest.mark.asyncio
async def test_disabled_rules_still_advance_offset():
    lead = await get_lead_repository(WS).create({"first_name": "Z", "phone": "+971500000003", "source": "crm", "status": "new", "score": 90})
    await events.emit(lead["id"], "lead.scored", {}, workspace_id=WS)
    assert (await automations.run_automations(WS))["rules"] == 0
    await automations.create_rule(WS, _rule(), actor=None)
    assert (await automations.run_automations(WS))["fired"] == 0  # old event is not replayed


@pytest.mark.asyncio
async def test_set_stage_action_and_failure_isolation():
    lead = await get_lead_repository(WS).create({"first_name": "Y", "phone": "+971500000004", "source": "crm", "status": "new", "score": 75})
    await automations.create_rule(WS, _rule(name="bad", action="run_job", action_params={"job_id": "does_not_exist"}), actor=None)
    await automations.create_rule(WS, _rule(name="stage", action="set_stage", action_params={"stage": "nurturing"}), actor=None)
    await events.emit(lead["id"], "lead.scored", {}, workspace_id=WS)
    result = await automations.run_automations(WS)
    assert result["fired"] == 1 and result["failed"] == 1
    assert (await get_lead_repository(WS).get_by_id(lead["id"]))["stage"] == "nurturing"
    statuses = sorted(r["status"] for r in await automations.list_runs(WS))
    assert statuses == ["failed", "fired"]


@pytest.mark.asyncio
async def test_dry_run_never_acts():
    await get_lead_repository(WS).create({"first_name": "Hot", "phone": "+971500000005", "source": "crm", "status": "new", "score": 95})
    await get_lead_repository(WS).create({"first_name": "Cold", "phone": "+971500000006", "source": "crm", "status": "new", "score": 5})
    rule = await automations.create_rule(WS, _rule(), actor=None)
    preview = await automations.test_rule(WS, rule)
    assert preview["checked"] >= 2 and preview["matched"] >= 1 and any(s["name"] == "Hot" for s in preview["sample"])
    assert await automations.list_tasks(WS) == []


# ---------------------------------------------------------------- API


def test_cowork_api_end_to_end():
    ov = client.get("/api/v1/cowork/overview")
    assert ov.status_code == 200
    assert ov.json()["jobs"]["total"] == len(jobs.JOBS)

    integ = client.get("/api/v1/cowork/integrations").json()
    ids = {c["id"] for c in integ["integrations"]}
    assert {"channel:whatsapp", "ai:llm", "ai:voice", "data:store", "crm:standalone"} <= ids
    assert integ["counts"]["not_configured"] >= 1  # standalone CRM not linked

    r = client.patch("/api/v1/cowork/jobs/send_due_followups", json={"enabled": False})
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert client.patch("/api/v1/cowork/jobs/nope", json={"enabled": False}).status_code == 404

    run = client.post("/api/v1/cowork/jobs/retry_ingestion_errors/run")
    assert run.status_code == 200 and run.json()["status"] == "success" and run.json()["trigger"] == "manual"
    runs = client.get("/api/v1/cowork/runs?job_id=retry_ingestion_errors").json()
    assert len(runs) == 1

    cat = client.get("/api/v1/cowork/automations/catalog").json()
    assert "lead.scored" in cat["triggers"] and "create_task" in cat["actions"]

    bad = client.post("/api/v1/cowork/automations", json={"name": "x", "trigger": "lead.scored", "action": "run_job", "action_params": {"job_id": "nope"}})
    assert bad.status_code == 422
    created = client.post("/api/v1/cowork/automations", json={"name": "Hot", "trigger": "lead.scored", "conditions": [{"field": "score", "op": "gte", "value": 70}], "action": "create_task"})
    assert created.status_code == 201
    rule_id = created.json()["id"]
    assert "matched" in client.post(f"/api/v1/cowork/automations/{rule_id}/test").json()
    assert client.patch(f"/api/v1/cowork/automations/{rule_id}", json={"enabled": False}).json()["enabled"] is False

    audit = client.get("/api/v1/cowork/audit").json()
    assert audit and audit[0]["kind"] == "job"

    assert client.delete(f"/api/v1/cowork/automations/{rule_id}").status_code == 200
    assert client.get("/api/v1/cowork/automations").json() == []
