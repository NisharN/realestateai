"""compare tool — side-by-side of 2–3 shown properties from stored data."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.database import get_property_repository


class CompareRow(BaseModel):
    property_id: str
    title: str
    price: float | None
    price_psf: float | None
    area: str | None
    bedrooms: int | None
    bathrooms: int | None
    size_sqft: int | None
    property_type: str | None
    amenities: list[str] = Field(default_factory=list)


class CompareResult(BaseModel):
    rows: list[CompareRow]
    cheapest_id: str | None = None
    largest_id: str | None = None


async def compare(property_ids: list[str], workspace_id: str) -> CompareResult:
    repo = get_property_repository(workspace_id)
    rows: list[CompareRow] = []
    for pid in property_ids[:3]:
        prop: dict[str, Any] | None = await repo.get_by_id(pid)
        if not prop:
            continue
        price, size = prop.get("price"), prop.get("size_sqft")
        rows.append(
            CompareRow(
                property_id=str(prop["id"]),
                title=prop.get("title") or "Listing",
                price=price,
                price_psf=prop.get("price_per_sqft") or (round(price / size) if price and size else None),
                area=prop.get("area"),
                bedrooms=prop.get("bedrooms"),
                bathrooms=prop.get("bathrooms"),
                size_sqft=size,
                property_type=prop.get("property_type"),
                amenities=list(prop.get("amenities") or [])[:6],
            )
        )
    priced = [r for r in rows if r.price]
    sized = [r for r in rows if r.size_sqft]
    return CompareResult(
        rows=rows,
        cheapest_id=min(priced, key=lambda r: r.price or 0).property_id if priced else None,
        largest_id=max(sized, key=lambda r: r.size_sqft or 0).property_id if sized else None,
    )
