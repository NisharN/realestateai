"""API routes for property management."""
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from app.database import get_db, PropertyRepository
from app.scrapers import scrape_bayut, scrape_propertyfinder, scrape_dubizzle

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/search")
async def search_properties(
    area: Optional[str] = None,
    property_type: Optional[str] = None,
    min_price: Optional[float] = Query(None, ge=0),
    max_price: Optional[float] = Query(None, ge=0),
    bedrooms: Optional[int] = Query(None, ge=0),
    limit: int = Query(10, ge=1, le=50),
    db=Depends(get_db)
):
    """Search properties from database."""
    prop_repo = PropertyRepository(db)
    return await prop_repo.search_by_criteria(
        area=area,
        property_type=property_type,
        min_price=min_price,
        max_price=max_price,
        bedrooms=bedrooms,
        limit=limit
    )


@router.post("/scrape/bayut")
async def scrape_bayut_endpoint(
    property_type: str = "buy_apartment",
    area: Optional[str] = None,
    pages: int = Query(1, ge=1, le=5),
    db=Depends(get_db)
):
    """Trigger Bayut scraper and save results."""
    try:
        listings = await scrape_bayut(
            property_type=property_type,
            area=area,
            pages=pages
        )

        prop_repo = PropertyRepository(db)
        saved = []
        for listing in listings:
            try:
                prop = await prop_repo.create(listing)
                saved.append(prop)
            except Exception as e:
                logger.warning(f"Error saving property: {e}")
                continue

        return {
            "scraped": len(listings),
            "saved": len(saved),
            "source": "bayut"
        }

    except Exception as e:
        logger.error(f"Bayut scrape endpoint error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scrape/propertyfinder")
async def scrape_pf_endpoint(
    property_type: str = "buy_apartment",
    area: Optional[str] = None,
    pages: int = Query(1, ge=1, le=5),
    db=Depends(get_db)
):
    """Trigger PropertyFinder scraper."""
    try:
        listings = await scrape_propertyfinder(
            property_type=property_type,
            area=area,
            pages=pages
        )

        prop_repo = PropertyRepository(db)
        saved = []
        for listing in listings:
            try:
                prop = await prop_repo.create(listing)
                saved.append(prop)
            except Exception as e:
                continue

        return {"scraped": len(listings), "saved": len(saved), "source": "propertyfinder"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{property_id}")
async def get_property(property_id: str, db=Depends(get_db)):
    """Get property by ID."""
    prop_repo = PropertyRepository(db)
    prop = await prop_repo.get_by_id(property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return prop
