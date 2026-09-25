"""CSV upload connector: one raw record per row, dedupe key = file hash + row index."""
from __future__ import annotations

import csv
import hashlib
import io
from typing import Literal

from app.modules.ingestion.models import RawRecord


class CsvUploadConnector:
    type = "csv_upload"
    mode: Literal["pull", "push"] = "push"

    async def fetch_since(self, cursor: str | None) -> tuple[list[RawRecord], str | None]:
        return [], cursor

    async def handle_push(self, headers: dict[str, str], body: bytes) -> list[RawRecord]:
        return parse_csv(body)


def parse_csv(body: bytes, *, filename: str | None = None) -> list[RawRecord]:
    text = body.decode("utf-8-sig", errors="replace")
    file_hash = hashlib.sha256(body).hexdigest()[:16]
    reader = csv.DictReader(io.StringIO(text))
    records: list[RawRecord] = []
    for index, row in enumerate(reader):
        cleaned = {(k or "").strip(): (v or "").strip() for k, v in row.items() if k is not None}
        if not any(cleaned.values()):
            continue
        records.append(
            RawRecord(
                external_id=f"{file_hash}:{index}",
                payload=cleaned,
                source_hint="csv",
            )
        )
    return records


def csv_headers(body: bytes) -> list[str]:
    text = body.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    for row in reader:
        return [c.strip() for c in row]
    return []
