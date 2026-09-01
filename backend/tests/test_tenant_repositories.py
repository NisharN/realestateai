import pytest

from app.database import LeadRepository
from app.mock_store import MockBrokerRepository, MockLeadRepository, MockPropertyRepository


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, data):
        self.data = data
        self.filters = []

    def select(self, *_args):
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def maybe_single(self):
        return self

    def execute(self):
        return _Result(self.data)


class _Database:
    def __init__(self, data):
        self.query = _Query(data)

    def table(self, _name):
        return self.query


@pytest.mark.asyncio
async def test_lead_repository_never_returns_another_workspaces_lead():
    workspace_a = MockLeadRepository("workspace-a")
    workspace_b = MockLeadRepository("workspace-b")

    created = await workspace_a.create(
        {"source": "website", "phone": "+971500000001"}
    )

    assert created["workspace_id"] == "workspace-a"
    assert await workspace_b.get_by_id(created["id"]) is None
    assert await workspace_b.get_by_phone("+971500000001") is None


@pytest.mark.asyncio
async def test_property_deduplication_is_scoped_to_workspace():
    workspace_a = MockPropertyRepository("workspace-a")
    workspace_b = MockPropertyRepository("workspace-b")

    await workspace_a.create(
        {"source": "crm", "source_id": "listing-1", "title": "Workspace A"}
    )
    await workspace_b.create(
        {"source": "crm", "source_id": "listing-1", "title": "Workspace B"}
    )

    match_a = await workspace_a.get_by_source_ref("crm", source_id="listing-1")
    match_b = await workspace_b.get_by_source_ref("crm", source_id="listing-1")

    assert match_a["title"] == "Workspace A"
    assert match_b["title"] == "Workspace B"
    assert match_a["id"] != match_b["id"]


@pytest.mark.asyncio
async def test_supabase_lead_lookup_always_filters_by_workspace():
    database = _Database({"id": "lead-1", "workspace_id": "workspace-a"})
    repository = LeadRepository(database, "workspace-a")

    await repository.get_by_id("lead-1")

    assert ("workspace_id", "workspace-a") in database.query.filters
    assert ("id", "lead-1") in database.query.filters


@pytest.mark.asyncio
async def test_agent_lead_list_only_contains_assigned_leads():
    repository = MockLeadRepository("workspace-agent-list")
    mine = await repository.create(
        {"source": "website", "status": "new", "assigned_broker": "broker-1"}
    )
    await repository.create(
        {"source": "website", "status": "new", "assigned_broker": "broker-2"}
    )

    visible = await repository.list_by_status(
        "new", assigned_broker_id="broker-1"
    )

    assert [lead["id"] for lead in visible] == [mine["id"]]


@pytest.mark.asyncio
async def test_mock_brokers_are_isolated_by_workspace():
    workspace_a = MockBrokerRepository("workspace-a")
    workspace_b = MockBrokerRepository("workspace-b")

    broker_a = await workspace_a.get_available_broker()
    broker_b = await workspace_b.get_available_broker()

    assert broker_a is not None
    assert broker_b is not None
    assert broker_a["workspace_id"] == "workspace-a"
    assert broker_b["workspace_id"] == "workspace-b"
    assert broker_a is not broker_b
