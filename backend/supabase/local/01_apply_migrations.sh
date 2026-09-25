#!/bin/sh
# Applies backend/supabase/migrations in filename order on first container start.
set -eu
for f in $(ls /docker-entrypoint-initdb.d/migrations/*.sql | sort); do
  echo "applying $(basename "$f")"
  psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f "$f"
done
