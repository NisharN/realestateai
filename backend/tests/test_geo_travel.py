"""Offline travel-time lookups: precomputed table first, labelled straight-line fallback otherwise."""
from __future__ import annotations

import httpx
import pytest

from app.modules.geo.communities import COMMUNITIES, get_community
from app.modules.geo.travel import (
    LANDMARKS,
    haversine_km,
    nearest_communities,
    store_travel_times,
    straight_line,
    travel_time,
)
from app.modules.store import reset_memory
from app.modules.tools.area_profile import area_profile
from scripts.osrm_precompute import osrm_table, run

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _clean():
    reset_memory()
    yield
    reset_memory()


def test_haversine_marina_to_downtown_is_about_19km():
    assert 17 < haversine_km(25.0805, 55.1403, 25.1972, 55.2744) < 20


def test_nearest_communities_are_deterministic_and_exclude_self():
    near = nearest_communities("dubai_marina")
    ids = [c.id for c, _ in near]
    assert "dubai_marina" not in ids and ids[0] in {"jbr", "dubai_harbour", "jlt"} and len(near) == 3


async def test_fallback_is_labelled_approx_and_table_overrides_it():
    tt = await travel_time("dubai_marina", "downtown")
    assert tt and tt.approx and tt.method == "straight_line" and 15 <= tt.minutes <= 45
    await store_travel_times([{"from_id": "dubai_marina", "to_id": "downtown", "minutes": 22, "km": 17.4}], method="osrm")
    tt2 = await travel_time("dubai_marina", "downtown")
    assert tt2 and not tt2.approx and tt2.minutes == 22 and tt2.km == 17.4 and tt2.computed_at
    assert await travel_time("nowhere", "downtown") is None


async def test_area_profile_carries_travel_and_neighbours():
    profile = await area_profile("marina", "00000000-0000-0000-0000-000000000001")
    assert profile and [t.to_id for t in profile.travel] == ["downtown", "dxb", "marina", "difc"]
    assert all(t.approx for t in profile.travel) and profile.nearby_communities


async def test_osrm_batch_parses_table_and_keeps_old_rows_on_failure():
    await store_travel_times([{"from_id": "jvc", "to_id": "dxb", "minutes": 30, "km": 28}], method="osrm")

    def ok(request: httpx.Request) -> httpx.Response:
        n_src = len(request.url.params["sources"].split(";"))
        return httpx.Response(200, json={
            "code": "Ok",
            "durations": [[600.0 + j for j in range(len(LANDMARKS))] for _ in range(n_src)],
            "distances": [[8000.0 for _ in LANDMARKS] for _ in range(n_src)],
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(ok)) as http:
        rows = await osrm_table(http, "https://osrm.internal", list(COMMUNITIES[:2]))
    assert len(rows) == 2 * len(LANDMARKS) and rows[0]["minutes"] == 10 and rows[0]["km"] == 8.0

    with pytest.raises(RuntimeError):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"code": "NoTable"}))) as http:
            await osrm_table(http, "https://osrm.internal", list(COMMUNITIES[:1]))
    tt = await travel_time("jvc", "dxb")
    assert tt and tt.minutes == 30 and tt.method == "osrm"


async def test_straight_line_seed_covers_every_pair():
    n = await run(None)
    assert n == len(LANDMARKS) * len(COMMUNITIES)
    tt = await travel_time("jvc", "moe")
    jvc = get_community("jvc")
    assert jvc and tt and tt.method == "straight_line" and tt.minutes == straight_line(jvc, LANDMARKS[6]).minutes
