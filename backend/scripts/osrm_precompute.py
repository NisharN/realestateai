"""Weekly batch: community centroids × landmarks → ``travel_times`` (architecture §7).

Runs against a *self-hosted* OSRM (``docker run osrm/osrm-backend`` on a UAE
extract) — never the public demo server. One ``/table`` call per batch, bounded
timeout, and on any failure the existing table is left untouched.

    OSRM_URL=http://localhost:5000 python -m scripts.osrm_precompute
    python -m scripts.osrm_precompute --straight-line   # no OSRM: seed labelled estimates
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from typing import Any

import httpx

from app.modules.geo.communities import COMMUNITIES
from app.modules.geo.travel import LANDMARKS, store_travel_times, straight_line

logger = logging.getLogger("osrm_precompute")
TIMEOUT_S = 60.0
BATCH = 40  # OSRM default max-table-size is 100 coordinates; 40 sources + 12 landmarks fits


def _coords(points: list[Any]) -> str:
    return ";".join(f"{p.lng},{p.lat}" for p in points)


async def osrm_table(client: httpx.AsyncClient, base_url: str, sources: list[Any]) -> list[dict[str, Any]]:
    points = [*sources, *LANDMARKS]
    src_idx = ";".join(str(i) for i in range(len(sources)))
    dst_idx = ";".join(str(len(sources) + j) for j in range(len(LANDMARKS)))
    url = f"{base_url.rstrip('/')}/table/v1/driving/{_coords(points)}"
    resp = await client.get(url, params={"sources": src_idx, "destinations": dst_idx, "annotations": "duration,distance"})
    if resp.status_code >= 400:
        raise RuntimeError(f"OSRM returned HTTP {resp.status_code}")
    body = resp.json()
    if body.get("code") != "Ok":
        raise RuntimeError(f"OSRM error: {body.get('code')}")
    rows: list[dict[str, Any]] = []
    for i, src in enumerate(sources):
        for j, dst in enumerate(LANDMARKS):
            dur = body["durations"][i][j]
            dist = body["distances"][i][j]
            if dur is None or dist is None:
                continue
            rows.append({"from_id": src.id, "to_id": dst.id, "minutes": max(1, round(dur / 60)), "km": round(dist / 1000, 1)})
    return rows


async def run(base_url: str | None) -> int:
    if not base_url:
        rows = [straight_line(c, l).model_dump() for c in COMMUNITIES for l in LANDMARKS]
        return await store_travel_times(rows, method="straight_line")
    rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        for i in range(0, len(COMMUNITIES), BATCH):
            rows.extend(await osrm_table(client, base_url, list(COMMUNITIES[i : i + BATCH])))
    # Only write after every batch succeeded: a half-refreshed table is worse than last week's.
    return await store_travel_times(rows, method="osrm")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--osrm-url", default=os.environ.get("OSRM_URL"))
    parser.add_argument("--straight-line", action="store_true", help="skip OSRM and seed labelled estimates")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    base = None if args.straight_line else args.osrm_url
    try:
        n = asyncio.run(run(base))
    except Exception as exc:
        logger.error("refresh failed, keeping existing travel_times: %s", exc)
        return 1
    logger.info("stored %d travel_times rows (%s)", n, "osrm" if base else "straight_line")
    return 0


if __name__ == "__main__":
    sys.exit(main())
