"""Generic CRM pull connector (§6.2).

Polls any JSON-over-HTTPS CRM export that supports "changed since" paging —
HubSpot/Zoho/Salesforce/Bitrix adapters differ only in `config`:

    config = {
      "url": "https://crm.example.com/api/leads",
      "auth_header": "Authorization",          # header carrying the credential
      "records_path": "data.items",            # dotted path to the list
      "cursor_param": "updated_after",         # query param carrying the cursor
      "cursor_field": "updated_at",            # per-record field used as next cursor
      "next_cursor_path": "paging.next",       # optional: server-provided cursor
      "id_field": "id",
      "extra_params": {"limit": 200},
    }

The credential lives in `connectors.secret`; the page body is never mutated —
each record lands untouched and the pipeline does the rest.
"""
from __future__ import annotations

import ipaddress
import logging
import socket
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from app.modules.ingestion.connectors.base import get_connector, land, record_run
from app.modules.ingestion.models import RawRecord
from app.modules.store import Row, now_iso, table

logger = logging.getLogger(__name__)

PULL_TYPES = ("hubspot", "zoho", "salesforce", "bitrix24", "generic_crm")
TIMEOUT_S = 15.0
MAX_PAGES = 20


def _dig(obj: Any, path: str | None) -> Any:
    if not path:
        return obj
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit():
            cur = cur[int(part)] if int(part) < len(cur) else None
        else:
            return None
    return cur


def _external_id(item: dict[str, Any], id_field: str) -> str | None:
    value = _dig(item, id_field)
    return str(value) if value not in (None, "") else None


class CrmPullConnector:
    type = "generic_crm"
    mode = "pull"

    def __init__(self, connector: Row, *, client: httpx.AsyncClient | None = None) -> None:
        self.connector = connector
        self.config: dict[str, Any] = connector.get("config") or {}
        self.type = connector.get("type") or self.type
        self._client = client

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        secret = self.connector.get("secret")
        if secret:
            headers[self.config.get("auth_header") or "Authorization"] = (
                secret if self.config.get("auth_raw") else f"Bearer {secret}"
            )
        return headers

    async def fetch_since(self, cursor: str | None) -> tuple[list[RawRecord], str | None]:
        url = validate_crm_url(self.config.get("url"))
        pinned = pin_crm_url(url) if self._client is None else PinnedUrl(url, {}, {})
        cursor_param = self.config.get("cursor_param") or "updated_after"
        cursor_field = self.config.get("cursor_field") or "updated_at"
        id_field = self.config.get("id_field") or "id"
        records_path = self.config.get("records_path")
        next_path = self.config.get("next_cursor_path")

        records: list[RawRecord] = []
        next_cursor = cursor
        client = self._client or httpx.AsyncClient(timeout=TIMEOUT_S)
        try:
            for _ in range(MAX_PAGES):
                params = dict(self.config.get("extra_params") or {})
                if next_cursor:
                    params[cursor_param] = next_cursor
                resp = await client.get(pinned.url, params=params, headers={**self._headers(), **pinned.headers}, extensions=pinned.extensions)
                if resp.status_code >= 400:
                    raise CrmHttpError(resp.status_code)
                body = resp.json()
                items = _dig(body, records_path)
                if not isinstance(items, list) or not items:
                    break
                page_cursor: str | None = None
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    records.append(RawRecord(external_id=_external_id(item, id_field), payload=item, source_hint=self.type))
                    stamp = _dig(item, cursor_field)
                    if stamp is not None and (page_cursor is None or str(stamp) > page_cursor):
                        page_cursor = str(stamp)
                if next_path:
                    server_cursor = _dig(body, next_path)
                    if not server_cursor or str(server_cursor) == next_cursor:
                        break
                    next_cursor = str(server_cursor)
                else:
                    # Changed-since paging: keep asking "after the newest seen" until the
                    # CRM returns nothing new. Requires ascending order by cursor_field.
                    if not page_cursor or page_cursor == next_cursor:
                        break
                    next_cursor = page_cursor
        finally:
            if self._client is None:
                await client.aclose()
        return records, next_cursor

    async def handle_push(self, headers: dict[str, str], body: bytes) -> list[RawRecord]:
        raise NotImplementedError("pull connector")

    async def write_back(self, lead: dict[str, Any], fields: dict[str, Any]) -> None:
        url = self.config.get("write_back_url")
        external_id = lead.get("crm_external_id")
        if not url or not external_id:
            return
        validate_crm_url(url)
        target = url.replace("{id}", quote(str(external_id), safe=""))
        if urlsplit(target)[:2] != urlsplit(url)[:2]:
            raise ValueError("CRM external id altered the write-back host")
        pinned = pin_crm_url(target) if self._client is None else PinnedUrl(target, {}, {})
        client = self._client or httpx.AsyncClient(timeout=TIMEOUT_S)
        try:
            resp = await client.patch(pinned.url, json=fields, headers={**self._headers(), **pinned.headers}, extensions=pinned.extensions)
            if resp.status_code >= 400:
                raise CrmHttpError(resp.status_code)
        finally:
            if self._client is None:
                await client.aclose()


async def poll_connector(connector_id: str, *, workspace_id: str, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """One scheduled pull: fetch → land → advance cursor. Cursor only moves after landing."""
    row = await get_connector(connector_id, workspace_id)
    if not row or row.get("mode") != "pull" or row.get("status") != "active":
        return {"connector_id": connector_id, "skipped": True}
    connector = CrmPullConnector(row, client=client)
    try:
        records, cursor = await connector.fetch_since(row.get("cursor"))
        result = await land(records, connector_id=connector_id, workspace_id=workspace_id)
        await table("connectors", workspace_id).update({"cursor": cursor, "updated_at": now_iso()}, id=connector_id)
        await record_run(connector_id, workspace_id, ok=True)
        return {"connector_id": connector_id, "fetched": len(records), "landed": len(result.landed), "duplicates": result.duplicates, "cursor": cursor, "raw_ids": result.ids}
    except Exception as exc:
        message = safe_error(exc)
        logger.warning("pull failed for connector %s: %s", connector_id, message)
        await record_run(connector_id, workspace_id, ok=False, error=message)
        return {"connector_id": connector_id, "error": message, "raw_ids": []}


async def due_pull_connectors(workspace_id: str) -> list[Row]:
    rows = await table("connectors", workspace_id).select(mode="pull", status="active", limit=200)
    now = now_iso()
    due = []
    for r in rows:
        every = int(r.get("schedule_seconds") or 0)
        if every <= 0 or r.get("type") not in PULL_TYPES:
            continue
        last = r.get("last_run_at")
        if not last or _seconds_between(last, now) >= every:
            due.append(r)
    return due


class CrmHttpError(Exception):
    """HTTP failure without the request URL, so tokens in query strings never reach logs or last_error."""

    def __init__(self, status: int) -> None:
        super().__init__(f"CRM returned HTTP {status}")
        self.status = status


def safe_error(exc: Exception) -> str:
    if isinstance(exc, (CrmHttpError, ValueError)):
        return str(exc)
    if isinstance(exc, httpx.HTTPError):
        return f"{type(exc).__name__} while contacting CRM"
    return f"{type(exc).__name__}: {exc}"


@dataclass(frozen=True)
class PinnedUrl:
    """A validated URL whose connection is pinned to the address we checked.

    ``url`` has the resolved public IP as host; ``headers``/``extensions`` carry
    the original hostname for the Host header and TLS SNI, so a DNS answer that
    changes between the check and the connect cannot redirect us inward.
    """

    url: str
    headers: dict[str, str]
    extensions: dict[str, str]


def pin_crm_url(url: str) -> PinnedUrl:
    parts = urlsplit(validate_crm_url(url, resolve=True))
    host = (parts.hostname or "").lower()
    try:
        ipaddress.ip_address(host.strip("[]"))
        return PinnedUrl(url, {}, {})
    except ValueError:
        pass
    infos = socket.getaddrinfo(host, parts.port or 443, proto=socket.IPPROTO_TCP)
    ips = [ipaddress.ip_address(i[4][0]) for i in infos]
    for ip in ips:
        _reject_internal(ip)
    ip = ips[0]
    netloc = f"[{ip}]" if ip.version == 6 else str(ip)
    if parts.port:
        netloc += f":{parts.port}"
    pinned = urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    host_header = host if not parts.port else f"{host}:{parts.port}"
    return PinnedUrl(pinned, {"Host": host_header}, {"sni_hostname": host})


def validate_crm_url(url: Any, *, resolve: bool = False) -> str:
    """Only public HTTPS hosts: the poller runs inside the backend network.

    ``resolve=True`` additionally resolves the hostname and rejects any address
    that is not public (DNS pointing at internal services). Redirects are never
    followed (httpx default), so a public host cannot bounce us inward. Live
    requests go through :func:`pin_crm_url` so the checked address is the one
    connected to.
    """
    if not url or not isinstance(url, str):
        raise ValueError("connector config.url is required")
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        raise ValueError("CRM url must be https://")
    if host in ("localhost", "metadata.google.internal") or host.endswith((".local", ".internal", ".localhost")) or "." not in host:
        raise ValueError("CRM url must point at a public host")
    try:
        _reject_internal(ipaddress.ip_address(host.strip("[]")))
        return url
    except ValueError as exc:
        if str(exc).startswith("CRM url"):
            raise
    if resolve:
        try:
            infos = socket.getaddrinfo(host, parts.port or 443, proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            raise ValueError("CRM host could not be resolved") from exc
        for info in infos:
            _reject_internal(ipaddress.ip_address(info[4][0]))
    return url


def _reject_internal(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified or not ip.is_global:
        raise ValueError("CRM url must point at a public host")


def _seconds_between(a: str, b: str) -> float:
    return (datetime.fromisoformat(b.replace("Z", "+00:00")) - datetime.fromisoformat(a.replace("Z", "+00:00"))).total_seconds()
