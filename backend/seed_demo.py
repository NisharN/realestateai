#!/usr/bin/env python3
"""Seed or reset the demo dataset.

In mock mode the in-memory store is seeded automatically at import, so this
script is mainly for two things:

1. Printing what the demo contains, so you know what to expect on screen.
2. Pushing the same dataset into a real Supabase project, when you want the
   demo backed by a database rather than process memory.

Usage:
    python seed_demo.py            # show what mock mode will serve
    python seed_demo.py --supabase # also write it to the configured database
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from app.config import get_settings
from app.seed_data import (
    mock_dld_transactions,
    mock_leads,
    mock_mandates,
    mock_property_records,
    mock_viewings,
    seed_summary,
)


def show_summary() -> None:
    settings = get_settings()
    counts = seed_summary()

    print("Demo dataset")
    print("=" * 46)
    print(f"  workspace        {settings.WORKSPACE_NAME} ({settings.WORKSPACE_ID})")
    print(f"  properties       {counts['properties']}")
    print(f"  leads            {counts['leads']}")
    print(f"  DLD comps        {counts['dld_transactions']} (sample rows, not live DLD)")
    print(f"  viewings         {counts['viewings']}")
    print(f"  mandates         {counts['mandates']}")
    print()
    print("Data modes")
    print("-" * 46)
    print(f"  properties       {settings.properties_mode}")
    print(f"  whatsapp         {settings.whatsapp_mode}")
    print(f"  dld              {settings.DATA_MODE_DLD}")
    print()

    leads = mock_leads()
    by_status: dict[str, int] = {}
    for lead in leads:
        by_status[lead["status"]] = by_status.get(lead["status"], 0) + 1
    print("Lead pipeline")
    print("-" * 46)
    for status, count in sorted(by_status.items()):
        print(f"  {status:<16} {count}")
    uncontacted = sum(1 for lead in leads if not lead["last_contact_at"])
    print(f"  (uncontacted)    {uncontacted} → the follow-up workflow will act on these")
    print()

    # The seed deliberately includes ambiguous budget phrasing so the
    # extractor's clarification path is visible in a live demo.
    from app.services.budget_extraction import extract_budget

    print("Budget extraction on seeded lead messages")
    print("-" * 46)
    seen = set()
    for lead in leads:
        message = lead.get("initial_message", "")
        if message in seen:
            continue
        seen.add(message)
        result = extract_budget(message)
        flag = "ASKS" if result.needs_clarification else "OK  "
        print(f"  [{flag}] {message[:52]:<54}")
    print()


def push_to_supabase() -> int:
    from app.database import DatabaseClient

    client = DatabaseClient.get_client()
    if client is None:
        print("No Supabase client available — check SUPABASE_URL / SUPABASE_SERVICE_KEY.")
        return 1

    workspace_id = get_settings().WORKSPACE_ID
    now = datetime.now(timezone.utc).isoformat()

    def stamp(rows):
        return [{**row, "workspace_id": workspace_id} for row in rows]

    tables = [
        ("properties", stamp(mock_property_records())),
        ("leads", stamp(mock_leads())),
        ("viewings", stamp(mock_viewings())),
        ("mandates", stamp(mock_mandates())),
        ("dld_transactions", stamp(mock_dld_transactions())),
    ]

    for table, rows in tables:
        try:
            client.table(table).upsert(rows).execute()
            print(f"  {table:<18} {len(rows)} rows")
        except Exception as exc:
            print(f"  {table:<18} skipped ({exc})")

    print(f"\nSeeded workspace {workspace_id} at {now}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--supabase",
        action="store_true",
        help="also write the dataset to the configured Supabase project",
    )
    args = parser.parse_args()

    show_summary()
    if args.supabase:
        print("Writing to Supabase")
        print("-" * 46)
        return push_to_supabase()
    return 0


if __name__ == "__main__":
    sys.exit(main())
