"""Shared property ingestion pipeline for multiple data sources."""
from __future__ import annotations

import csv
import io
import json
import logging
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

from app.models.property import PropertyImportRecord
from app.scrapers import scrape_bayut, scrape_dubizzle, scrape_propertyfinder

logger = logging.getLogger(__name__)


class PropertyIngestionService:
    """Normalize, dedupe, and persist properties from multiple sources."""

    def __init__(self, property_repo: Any):
        self.property_repo = property_repo

    async def import_records(
        self,
        source: str,
        records: Iterable[Dict[str, Any]],
        dedupe: bool = True,
    ) -> Dict[str, Any]:
        received = 0
        saved = 0
        skipped = 0
        errors: List[str] = []

        for idx, raw in enumerate(records):
            received += 1
            try:
                record = self._normalize_record(source, raw)
                if not self._is_useful(record):
                    skipped += 1
                    continue

                payload = record.model_dump(exclude_none=True)
                existing = None
                if dedupe:
                    existing = await self.property_repo.get_by_source_ref(
                        source=payload["source"],
                        source_id=payload.get("source_id"),
                        source_url=payload.get("source_url"),
                    )

                if existing:
                    await self.property_repo.update(existing["id"], payload)
                else:
                    await self.property_repo.create(payload)
                saved += 1
            except Exception as exc:
                errors.append(f"record {idx}: {exc}")

        return {
            "source": source,
            "received": received,
            "saved": saved,
            "skipped": skipped,
            "errors": errors,
        }

    async def import_csv_bytes(
        self,
        source: str,
        data: bytes,
        dedupe: bool = True,
    ) -> Dict[str, Any]:
        text = data.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        return await self.import_records(source, list(reader), dedupe=dedupe)

    async def import_manual_urls(
        self,
        urls: List[str],
        fetch_details: bool = True,
        dedupe: bool = True,
    ) -> Dict[str, Any]:
        grouped: Dict[str, List[str]] = {"bayut": [], "dubizzle": [], "propertyfinder": []}
        unsupported: List[str] = []

        for url in urls:
            source = self._detect_source_from_url(url)
            if source in grouped:
                grouped[source].append(url)
            else:
                unsupported.append(url)

        saved = 0
        skipped = len(unsupported)
        errors = [f"unsupported url: {url}" for url in unsupported]
        received = len(urls)

        for source, source_urls in grouped.items():
            if not source_urls:
                continue
            scraper_cls = {
                "bayut": self._scrape_detail_bayut,
                "dubizzle": self._scrape_detail_dubizzle,
                "propertyfinder": self._scrape_detail_propertyfinder,
            }[source]
            records: List[Dict[str, Any]] = []
            for url in source_urls:
                try:
                    detail = await scraper_cls(url) if fetch_details else {"url": url}
                    detail["url"] = url
                    detail["id"] = self._source_id_from_url(url)
                    detail["source_url"] = url
                    records.append(detail)
                except Exception as exc:
                    errors.append(f"{source} detail failed for {url}: {exc}")

            result = await self.import_records(source, records, dedupe=dedupe)
            saved += result["saved"]
            skipped += result["skipped"]
            errors.extend(result["errors"])

        return {
            "source": "manual_url_import",
            "received": received,
            "saved": saved,
            "skipped": skipped,
            "errors": errors,
        }

    async def scrape_source(
        self,
        source: str,
        property_type: str = "buy_apartment",
        area: Optional[str] = None,
        pages: int = 1,
        dedupe: bool = True,
    ) -> Dict[str, Any]:
        scrapers = {
            "propertyfinder": scrape_propertyfinder,
            "bayut": scrape_bayut,
            "dubizzle": scrape_dubizzle,
        }
        if source not in scrapers:
            raise ValueError(f"Unsupported scrape source: {source}")
        listings = await scrapers[source](property_type=property_type, area=area, pages=pages)
        return await self.import_records(source, listings, dedupe=dedupe)

    def _normalize_record(self, source: str, raw: Dict[str, Any]) -> PropertyImportRecord:
        images = self._listify(raw.get("images") or raw.get("image_urls") or raw.get("photos"))
        amenities = self._listify(raw.get("amenities") or raw.get("features"))
        source_url = raw.get("source_url") or raw.get("url") or raw.get("listing_url")
        return PropertyImportRecord(
            source=source,
            source_id=self._string(raw.get("source_id") or raw.get("id") or self._source_id_from_url(source_url)),
            source_url=source_url,
            title=raw.get("title") or raw.get("name") or raw.get("headline"),
            description=raw.get("description") or raw.get("details"),
            price=self._float(raw.get("price")),
            price_per_sqft=self._float(raw.get("price_per_sqft") or raw.get("ppsf")),
            area=raw.get("area") or raw.get("location") or raw.get("community"),
            property_type=(raw.get("property_type") or raw.get("type") or "").lower() or None,
            bedrooms=self._int(raw.get("bedrooms") or raw.get("beds")),
            bathrooms=self._int(raw.get("bathrooms") or raw.get("baths")),
            size_sqft=self._int(raw.get("size_sqft") or raw.get("size") or raw.get("area_sqft")),
            images=images or None,
            video_url=raw.get("video_url"),
            floor_plan_url=raw.get("floor_plan_url"),
            map_lat=self._float(raw.get("map_lat") or raw.get("latitude")),
            map_lng=self._float(raw.get("map_lng") or raw.get("longitude")),
            amenities=amenities or None,
            developer=raw.get("developer"),
            completion_date=self._string(raw.get("completion_date")),
            raw_payload=raw,
        )

    def _is_useful(self, record: PropertyImportRecord) -> bool:
        return bool(record.title and record.area and record.price and record.source_url)

    def _listify(self, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            if value.strip().startswith("["):
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, list):
                        return [str(item).strip() for item in parsed if str(item).strip()]
                except Exception:
                    pass
            return [item.strip() for item in value.split(",") if item.strip()]
        return [str(value).strip()]

    def _float(self, value: Any) -> Optional[float]:
        if value in (None, ""):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = "".join(ch for ch in str(value) if ch.isdigit() or ch in {".", ","}).replace(",", "")
        try:
            return float(text) if text else None
        except ValueError:
            return None

    def _int(self, value: Any) -> Optional[int]:
        parsed = self._float(value)
        return int(parsed) if parsed is not None else None

    def _string(self, value: Any) -> Optional[str]:
        if value in (None, ""):
            return None
        return str(value)

    def _detect_source_from_url(self, url: str) -> Optional[str]:
        host = urlparse(url).netloc.lower()
        if "propertyfinder" in host:
            return "propertyfinder"
        if "bayut" in host:
            return "bayut"
        if "dubizzle" in host:
            return "dubizzle"
        return None

    def _source_id_from_url(self, url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        path = urlparse(url).path.rstrip("/")
        return path.split("/")[-1] if path else None

    async def _scrape_detail_bayut(self, url: str) -> Dict[str, Any]:
        from app.scrapers.bayut_scraper import BayutScraper

        async with BayutScraper() as scraper:
            return await scraper.scrape_detail(url)

    async def _scrape_detail_dubizzle(self, url: str) -> Dict[str, Any]:
        from app.scrapers.dubizzle_scraper import DubizzleScraper

        async with DubizzleScraper() as scraper:
            return await scraper.scrape_detail(url)

    async def _scrape_detail_propertyfinder(self, url: str) -> Dict[str, Any]:
        from app.scrapers.propertyfinder_scraper import PropertyFinderScraper

        async with PropertyFinderScraper() as scraper:
            return await scraper.scrape_detail(url)
