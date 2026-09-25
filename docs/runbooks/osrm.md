# OSRM runbook — self-hosted travel times

Travel times shown to buyers come from the `travel_times` table, precomputed
weekly from a **self-hosted** OSRM. The public OSRM demo server is never used at
runtime or in the batch. Until the table is populated, answers fall back to
labelled straight-line estimates (`approx=true`, "roughly ~N min").

## 1. Build the UAE routing graph (once, ~10 min)

```bash
mkdir -p osrm-data && cd osrm-data
curl -L -o uae.osm.pbf https://download.geofabrik.de/asia/gcc-states-latest.osm.pbf
docker run --rm -t -v "$PWD:/data" osrm/osrm-backend osrm-extract   -p /opt/car.lua /data/uae.osm.pbf
docker run --rm -t -v "$PWD:/data" osrm/osrm-backend osrm-partition /data/uae.osrm
docker run --rm -t -v "$PWD:/data" osrm/osrm-backend osrm-customize /data/uae.osrm
```

The Geofabrik GCC extract covers the UAE (there is no UAE-only extract).
Re-download quarterly; road changes in Dubai are frequent.

## 2. Serve it

```bash
docker compose --profile osrm up -d osrm
curl "http://localhost:5000/route/v1/driving/55.2744,25.1972;55.1403,25.0805?overview=false" | head -c 200
```

`--max-table-size 200` in `docker-compose.yml` is required: the precompute
sends 40 communities + landmarks per `/table` call.

## 3. Precompute the table

```bash
cd backend
OSRM_URL=http://localhost:5000 venv/bin/python -m scripts.osrm_precompute
```

- One `/table` call per batch of 40 communities, 60 s timeout.
- On **any** failure the existing `travel_times` rows are left untouched
  (the script exits non-zero; the previous week's data keeps serving).
- Rows are written with `method="osrm"`, `approx=false`.

Without OSRM (dev / first deploy):

```bash
venv/bin/python -m scripts.osrm_precompute --straight-line
```

seeds labelled estimates so area answers still work, clearly marked approximate.

## 4. Schedule

Run step 3 weekly (cron on the host or a CI job). It does not run inside Celery
beat on purpose: OSRM is not part of the production request path and should be
able to be down without any alert.

## Verify

```sql
select method, approx, count(*) from travel_times group by 1, 2;
```

Expect `osrm | false | ≥ (communities × landmarks)`. Ask the buyer chat
"how far is JVC from Downtown?" and confirm the answer no longer says "roughly".
