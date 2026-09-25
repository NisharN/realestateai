"""Co-work: job registry, run history, task automations and the aggregated API."""
from __future__ import annotations

import asyncio

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
    assert result == {"events": 3, "fired": 1, "skipped": 1, "failed": 0, "rules": 1, "retried": 0, "recovered": 0}

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


async def _raw_rule(name: str, action: str, params: dict) -> dict:
    """Insert a rule bypassing validation (simulates a row written before validation existed)."""
    return await table(automations.RULES_TABLE, WS).insert(
        {"id": f"rule-{name}", "name": name, "trigger": "lead.scored", "conditions": [], "action": action, "action_params": params, "enabled": True, "run_count": 0}
    )


@pytest.mark.asyncio
async def test_set_stage_action_and_failure_isolation():
    lead = await get_lead_repository(WS).create({"first_name": "Y", "phone": "+971500000004", "source": "crm", "status": "new", "score": 75})
    await _raw_rule("bad", "set_stage", {"stage": "nurturing"})  # not a pipeline stage: rejected at execution too
    await automations.create_rule(WS, _rule(name="stage", action="set_stage", action_params={"stage": "qualified"}), actor=None)
    await events.emit(lead["id"], "lead.scored", {}, workspace_id=WS)
    result = await automations.run_automations(WS)
    assert result["fired"] == 1 and result["failed"] == 1
    assert (await get_lead_repository(WS).get_by_id(lead["id"]))["stage"] == "qualified"
    statuses = sorted(r["status"] for r in await automations.list_runs(WS))
    assert statuses == ["failed", "fired"]


def test_rule_validation_rejects_bad_stage_and_self_targeting_job():
    with pytest.raises(ValueError, match="stage must be one of"):
        _rule(action="set_stage", action_params={"stage": "nurturing"})
    with pytest.raises(ValueError, match="cannot run job"):
        _rule(action="run_job", action_params={"job_id": "run_automations"})
    with pytest.raises(ValueError, match="unknown job"):
        _rule(action="run_job", action_params={"job_id": "nope"})
    _rule(action="run_job", action_params={"job_id": "send_due_followups"})  # allowed


@pytest.mark.asyncio
async def test_patch_validates_and_execution_refuses_recursive_job():
    rule = await automations.create_rule(WS, _rule(action="set_stage", action_params={"stage": "qualified"}), actor=None)
    with pytest.raises(ValueError):
        await automations.patch_rule(WS, rule["id"], automations.AutomationPatch(action_params={"stage": "bogus"}))
    with pytest.raises(ValueError):
        await automations.patch_rule(WS, rule["id"], automations.AutomationPatch(action="run_job", action_params={"job_id": "run_automations"}))
    lead = await get_lead_repository(WS).create({"first_name": "R", "phone": "+971500000014", "source": "crm", "status": "new", "score": 80})
    await _raw_rule("loop", "run_job", {"job_id": "run_automations"})
    await events.emit(lead["id"], "lead.scored", {}, workspace_id=WS)
    result = await automations.run_automations(WS)
    assert result["failed"] == 1
    assert not await table(jobs.RUNS_TABLE, WS).select(job_id="run_automations", limit=5)


def test_templates_are_whitelisted_and_cannot_traverse():
    lead = {"first_name": "Amina", "score": 88, "stage": "qualified", "phone": "+9715"}
    assert automations.render_template("Call {first_name} ({score}, {stage})", lead) == "Call Amina (88, qualified)"
    # str.format-style traversal / non-whitelisted keys are left verbatim, never evaluated
    assert automations.render_template("{first_name.__class__} {phone} {missing}", lead) == "{first_name.__class__} {phone} {missing}"
    assert automations.render_template("{score:>10}", lead) == "{score:>10}"


@pytest.mark.asyncio
async def test_conditions_use_event_time_snapshot():
    repo = get_lead_repository(WS)
    lead = await repo.create({"first_name": "S", "phone": "+971500000015", "source": "crm", "status": "new", "score": 90})
    await automations.create_rule(WS, _rule(), actor=None)
    await events.emit(lead["id"], "lead.scored", {}, workspace_id=WS)  # snapshot: score 90
    await repo.update(lead["id"], {"score": 10})  # lead changes before the consumer catches up
    result = await automations.run_automations(WS)
    assert result["fired"] == 1 and result["skipped"] == 0


@pytest.mark.asyncio
async def test_failed_action_is_retried_without_replaying_success(monkeypatch):
    repo = get_lead_repository(WS)
    lead = await repo.create({"first_name": "F", "phone": "+971500000016", "source": "crm", "status": "new", "score": 90})
    await automations.create_rule(WS, _rule(name="ok"), actor=None)
    flaky = await automations.create_rule(WS, _rule(name="flaky", action="set_stage", action_params={"stage": "qualified"}), actor=None)
    await events.emit(lead["id"], "lead.scored", {}, workspace_id=WS)

    real_update = repo.update
    calls = {"n": 0}

    async def failing_update(lead_id, updates):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise RuntimeError("db hiccup")
        return await real_update(lead_id, updates)

    monkeypatch.setattr(repo, "update", failing_update)
    monkeypatch.setattr(automations, "get_lead_repository", lambda _ws: repo)
    first = await automations.run_automations(WS)
    # fails once in the consumer and once in the same-run retry pass
    assert first["fired"] == 1 and first["failed"] == 1 and first["retried"] == 1 and first["recovered"] == 0
    assert (await repo.get_by_id(lead["id"])).get("stage") != "qualified"

    second = await automations.run_automations(WS)
    assert second["events"] == 0 and second["retried"] == 1 and second["recovered"] == 1
    assert (await repo.get_by_id(lead["id"]))["stage"] == "qualified"
    assert len(await automations.list_tasks(WS)) == 1  # the successful rule did not run again
    run = await table(automations.RUNS_TABLE, WS).get(automation_id=flaky["id"])
    assert run["status"] == "fired" and run["attempts"] == 3
    assert (await automations.run_automations(WS))["retried"] == 0  # nothing left to retry


@pytest.mark.asyncio
async def test_claim_is_exclusive_per_rule_and_event():
    lead = await get_lead_repository(WS).create({"first_name": "C", "phone": "+971500000017", "source": "crm", "status": "new", "score": 90})
    rule = await automations.create_rule(WS, _rule(), actor=None)
    event = await events.emit(lead["id"], "lead.scored", {}, workspace_id=WS)
    assert await automations._claim(WS, rule, event) is not None
    assert await automations._claim(WS, rule, event) is None


@pytest.mark.asyncio
async def test_audit_rows_keep_name_after_rule_delete():
    lead = await get_lead_repository(WS).create({"first_name": "D", "phone": "+971500000018", "source": "crm", "status": "new", "score": 90})
    rule = await automations.create_rule(WS, _rule(name="Keep me"), actor=None)
    await events.emit(lead["id"], "lead.scored", {}, workspace_id=WS)
    await automations.run_automations(WS)
    assert await automations.delete_rule(WS, rule["id"])
    runs = await automations.list_runs(WS)
    assert len(runs) == 1 and runs[0]["automation_name"] == "Keep me"


@pytest.mark.asyncio
async def test_job_lease_blocks_concurrent_run(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow(_ws: str) -> dict:
        started.set()
        await release.wait()
        return {"ok": True}

    spec = jobs.get_spec("send_due_followups")
    monkeypatch.setitem(jobs.JOB_INDEX, "send_due_followups", jobs.JobSpec(spec.id, spec.label, spec.description, spec.category, spec.default_interval_s, slow))
    first = asyncio.create_task(jobs.run_job(WS, "send_due_followups"))
    await started.wait()
    second = await jobs.run_job(WS, "send_due_followups")
    assert second["status"] == "skipped" and second["id"] is None
    release.set()
    assert (await first)["status"] == "success"
    assert len(await table(jobs.RUNS_TABLE, WS).select(job_id="send_due_followups", limit=10)) == 1
    assert (await jobs.run_job(WS, "send_due_followups"))["status"] == "success"  # lease released


@pytest.mark.asyncio
async def test_poll_processes_all_landed_ids_in_batches(monkeypatch):
    from app.modules.ingestion.connectors import crm_pull
    from app.modules.ingestion.pipeline import processor

    ids = [f"raw-{i}" for i in range(1203)]
    seen: list[list[str]] = []

    async def due(_ws):
        return [{"id": "c1"}]

    async def poll(_cid, *, workspace_id):
        return {"raw_ids": ids}

    async def process_many(batch, *, workspace_id):
        seen.append(list(batch))
        return list(batch)

    monkeypatch.setattr(crm_pull, "due_pull_connectors", due)
    monkeypatch.setattr(crm_pull, "poll_connector", poll)
    monkeypatch.setattr(processor, "process_many", process_many)
    run = await jobs.run_job(WS, "poll_pull_connectors")
    assert run["status"] == "success" and run["summary"] == {"connectors": 1, "landed": 1203, "processed": 1203}
    assert [len(b) for b in seen] == [500, 500, 203]


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
