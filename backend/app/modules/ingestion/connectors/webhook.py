"""Generic push webhook connector: HMAC-SHA256 signed JSON, single object or list."""
from __future__ import annotations

import json
from typing import Any, Literal

from app.modules.ingestion.connectors.base import SignatureError, verify_hmac_sha256
from app.modules.ingestion.models import RawRecord

ID_KEYS = ("id", "external_id", "lead_id", "record_id", "uuid")


class WebhookConnector:
    type = "webhook"
    mode: Literal["pull", "push"] = "push"

    def __init__(self, secret: str | None) -> None:
        self.secret = secret

    async def fetch_since(self, cursor: str | None) -> tuple[list[RawRecord], str | None]:
        return [], cursor

    async def handle_push(self, headers: dict[str, str], body: bytes) -> list[RawRecord]:
        if self.secret:
            provided = headers.get("x-signature-256") or headers.get("x-hub-signature-256") or headers.get("x-signature")
            if not verify_hmac_sha256(self.secret, body, provided):
                raise SignatureError("invalid signature")
        try:
            data = json.loads(body.decode("utf-8") or "null")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("invalid json") from exc
        items: list[Any]
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("records") if isinstance(data.get("records"), list) else [data]
        else:
            raise ValueError("payload must be an object or list")
        records: list[RawRecord] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            ext = next((str(item[k]) for k in ID_KEYS if item.get(k) not in (None, "")), None)
            records.append(RawRecord(external_id=ext, payload=item, source_hint="webhook"))
        return records
