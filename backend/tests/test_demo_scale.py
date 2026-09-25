import pytest

from app.config import get_settings
from app.database import get_lead_repository
from app.demo_scale import scale_leads, scale_properties, scale_related
from app.mock_store import _leads, _properties, load_scale_data, load_seed_data
from app.modules.leads.stages import CLOSED_STAGES, PIPELINE_STAGES, lead_stage
from app.modules.store import _MEMORY, reset_memory


def test_generators_are_deterministic():
    a = list(scale_leads(200))
    b = list(scale_leads(200))
    assert [l["id"] for l in a] == [l["id"] for l in b]
    assert [(l["phone"], l["budget_max_aed"], l["stage"]) for l in a] == [
        (l["phone"], l["budget_max_aed"], l["stage"]) for l in b
    ]
    assert [p["price"] for p in scale_properties(100)] == [p["price"] for p in scale_properties(100)]


def test_generated_records_are_varied_and_coherent():
    leads = list(scale_leads(2000))
    assert {l["preferred_language"] for l in leads} == {"en", "ar"}
    assert {l["stage"] for l in leads} == set(PIPELINE_STAGES)
    assert all(l["budget_min_aed"] <= l["budget_max_aed"] for l in leads)
    assert all(l["assigned_broker"] in {"broker-1", "broker-2"} for l in leads if l["stage"] not in {"new", "qualifying"} and l["assigned_broker"])
    related = scale_related(leads)
    lead_ids = {l["id"] for l in leads}
    assert related["handoffs"] and related["viewings"] and related["followups"]
    for rows in related.values():
        assert all(r["lead_id"] in lead_ids for r in rows)
    props = list(scale_properties(500))
    assert all(p["map_lat"] is not None and p["community_id"] for p in props)
    assert {p["listing_type"] for p in props} == {"sale", "rent"}


@pytest.fixture
def scaled():
    reset_memory()
    load_seed_data()
    counts = load_scale_data(1000, _MEMORY)
    yield counts
    reset_memory()
    load_seed_data()


@pytest.mark.asyncio
async def test_mock_repository_scale_queries(scaled):
    assert scaled["leads"] >= 1000
    assert "prop-1" in _properties and len(_properties) > 250
    repo = get_lead_repository(get_settings().WORKSPACE_ID)
    totals = await repo.count_by_stage()
    assert sum(totals.values()) == len([l for l in _leads.values() if l["workspace_id"] == get_settings().WORKSPACE_ID])
    hot = await repo.list_hot(min_score=70, limit=20)
    assert 0 < len(hot) <= 20
    assert all(lead_stage(l) not in CLOSED_STAGES for l in hot)
    mine = await repo.list_all(limit=50, assigned_broker_id="broker-1")
    assert mine and all(l["assigned_broker"] == "broker-1" for l in mine)
    summary = await repo.summary()
    assert summary["total_leads"] == sum(totals.values())


@pytest.mark.asyncio
async def test_scale_load_is_idempotent(scaled):
    again = load_scale_data(1000, _MEMORY)
    assert again == scaled
