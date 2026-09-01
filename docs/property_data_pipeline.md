# Property Data Pipeline

Date: July 28, 2026

## Goal

This pipeline lets you ingest property listings from:

- broker CSV uploads
- CRM exports
- partner/property feeds
- manual listing URL imports
- your own inventory database exports
- supported live scrapers such as Property Finder
- RapidAPI-backed UAE real-estate sources

All sources are normalized into the same `properties` table.

## Endpoints

### 1. CSV upload

`POST /api/v1/properties/import/csv?source=broker_csv`

Use for:

- broker CSV uploads
- CRM CSV exports
- inventory CSV dumps

Form-data fields:

- `file`: CSV file

Query params:

- `source`: `broker_csv`, `crm_export`, `inventory_db`, or another label you want to track
- `dedupe`: `true` or `false`

Expected columns can include:

- `id` or `source_id`
- `url` or `source_url`
- `title`
- `description`
- `price`
- `price_per_sqft`
- `area` or `location`
- `property_type`
- `bedrooms`
- `bathrooms`
- `size_sqft` or `size`
- `images`
- `amenities`
- `developer`

For `images` and `amenities`, comma-separated strings are accepted.

### 2. JSON import

`POST /api/v1/properties/import/json`

Use for:

- CRM exports
- partner/property feeds
- internal ETL jobs

Example body:

```json
{
  "source": "crm_export",
  "dedupe": true,
  "records": [
    {
      "id": "crm-1001",
      "source_url": "https://example.com/listing/1001",
      "title": "2BR Marina Apartment",
      "price": 1850000,
      "area": "Dubai Marina",
      "property_type": "apartment",
      "bedrooms": 2,
      "bathrooms": 2,
      "size_sqft": 1120,
      "images": ["https://example.com/img1.jpg"]
    }
  ]
}
```

### 3. Manual URL import

`POST /api/v1/properties/import/manual-urls`

Use for:

- manually collected listing URLs
- small batches shared by brokers
- handpicked listings from supported portals

Example body:

```json
{
  "urls": [
    "https://www.propertyfinder.ae/en/plp/buy/apartment-for-sale-dubai-....html"
  ],
  "fetch_details": true
}
```

Currently recognized:

- `propertyfinder`
- `bayut`
- `dubizzle`

### 4. Inventory import

`POST /api/v1/properties/import/inventory`

Use for:

- your own inventory database export
- internal listings created outside scraped portals

Example body:

```json
{
  "dedupe": true,
  "records": [
    {
      "source_id": "inventory-501",
      "source_url": "https://yourcompany.example/listings/501",
      "title": "Townhouse in Arabian Ranches",
      "price": 3200000,
      "area": "Arabian Ranches",
      "property_type": "townhouse",
      "bedrooms": 3,
      "bathrooms": 4,
      "size_sqft": 2400
    }
  ]
}
```

### 5. Approved feed import

`POST /api/v1/properties/scrape/approved-feed`

Use when:

- public scrape pages are blocked
- a partner/provider gives you a JSON feed instead

Environment variables:

- `APPROVED_FEED_URL`
- `APPROVED_FEED_TOKEN`

### 6. RapidAPI import

`POST /api/v1/properties/scrape/rapidapi`

Use when:

- you have a provider-backed RapidAPI source
- direct browse scraping is blocked
- you want another ingestion path besides portal scraping

Environment variables:

- `RAPIDAPI_UAE_REAL_ESTATE_KEY`
- `RAPIDAPI_UAE_REAL_ESTATE_HOST`

Example body:

```json
{
  "endpoint": "developer-search-by-name",
  "params": {
    "query": "emaar",
    "page": 1,
    "langs": "en"
  },
  "dedupe": true
}
```

Developer lookup helper:

`POST /api/v1/properties/lookup/rapidapi/developer`

Example body:

```json
{
  "query": "emaar",
  "page": 1,
  "langs": "en"
}
```

### 7. Multi-source run

`POST /api/v1/properties/ingest/multi-source`

Use to trigger several sources in one call.

Example body:

```json
{
  "sources": ["propertyfinder", "approved_feed", "rapidapi_uae"],
  "property_type": "buy_apartment",
  "area": "Dubai Marina",
  "pages": 1,
  "dedupe": true
}
```

## Dedupe Behavior

The pipeline tries to dedupe by:

- `source + source_id`
- or `source + source_url`

If a match already exists, the listing is updated instead of inserted again.

## Recommended Source Strategy

Best working mix right now:

- `Property Finder` for live discovery
- `broker_csv` and `crm_export` for scale
- `inventory_db` for first-party listings
- `approved_feed` for partner/provider sources
- `rapidapi_uae` for provider-backed supplemental discovery
- `manual_url_import` for handpicked portal listings

**Bayut and Dubizzle scraping are deferred by default** as of the product/market
review (August 2026). Both endpoints now return a 400 unless
`ENABLE_BAYUT_DUBIZZLE_SCRAPING=true` is set — see `docs/scraper_operations.md`
for why (CAPTCHA/Incapsula on both public browse paths) and what real opt-in
requires (proxies or manually-solved sessions). For onboarding a new broker
workspace, lead with CSV/CRM import — it's faster to set up, has no legal
gray area, and is exactly what the `/configure` workflow builder collects.

## Suggested Production Workflow

1. Run `Property Finder` on a schedule.
2. Import broker CSVs daily.
3. Import CRM export snapshots daily or hourly.
4. Import your own inventory continuously.
5. Add an approved feed or RapidAPI-backed provider for blocked portal sources.
6. Use manual URL import for high-priority listings shared by brokers.
