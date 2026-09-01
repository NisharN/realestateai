# Scraper Operations

Date verified: July 28, 2026

## Current Reality

- `Property Finder` can be scraped live from this codebase today.
- `Bayut` is currently challenge-protected by CAPTCHA on the public browse path.
- `Dubizzle` is currently challenge-protected by Incapsula on the public browse path.

That means Bayut and Dubizzle do not become reliable just from selector fixes. They need an operational bypass that stays within your legal and contractual boundaries.

## Supported Paths

### 1. Residential Proxy

Set `PROXY_LIST` in `backend/.env` as a comma-separated list.

Supported formats:

- `http://host:port`
- `http://user:pass@host:port`
- `socks5://user:pass@host:port`

Example:

```env
PROXY_LIST=http://user:pass@res-proxy-1:8000,http://user:pass@res-proxy-2:8000
SCRAPER_BROWSER_CHANNEL=chrome
```

Then run:

```bash
python scripts/run_live_scrape_check.py
```

### 2. Manually Solved Browser Session

Use this when the site lets you pass after an interactive challenge.

Set a state path in `backend/.env`:

```env
SCRAPER_STORAGE_STATE_PATH=./runtime/scraper-state/bayut.json
SCRAPER_BROWSER_CHANNEL=chrome
SCRAPER_HEADLESS=false
```

Capture the session:

```bash
python scripts/capture_scraper_session.py bayut
python scripts/capture_scraper_session.py dubizzle
```

Process:

1. A visible browser opens on the portal.
2. Solve any CAPTCHA/challenge manually.
3. Wait until listings are visible.
4. Press Enter in the terminal.
5. Cookies/local storage are saved and will be reused by the scraper.

After that, switch back to headless if you want:

```env
SCRAPER_HEADLESS=true
```

Test:

```bash
python scripts/run_live_scrape_check.py --site bayut
python scripts/run_live_scrape_check.py --site dubizzle
```

### 3. Persistent Chrome Profile

Use this when the exported-session flow is awkward or when the portal behaves
better with your real local Chrome profile.

Set in `backend/.env`:

```env
SCRAPER_BROWSER_CHANNEL=chrome
SCRAPER_USER_DATA_DIR=C:/Users/your-user/AppData/Local/Google/Chrome/User Data
SCRAPER_PROFILE_NAME=Default
SCRAPER_HEADLESS=false
```

Quick setup on Windows:

```powershell
.\scripts\use_chrome_profile.ps1 -Portal bayut
```

Important:

1. Close all Chrome windows before running the scraper, or Chrome may lock the profile.
2. Open Chrome normally first if you need to solve Bayut or Dubizzle manually.
3. Then run the scraper test using the same profile.

Test:

```powershell
cd backend
.\venv\Scripts\python.exe ..\scripts\run_live_scrape_check.py --site bayut
.\venv\Scripts\python.exe ..\scripts\run_live_scrape_check.py --site dubizzle
```

### 4. Approved Alternate Feed

If the portals remain challenge-protected, you can ingest a provider-approved JSON feed instead.

Set:

```env
APPROVED_FEED_URL=https://your-provider.example.com/listings.json
APPROVED_FEED_TOKEN=your-token-if-needed
```

Then call:

`POST /api/v1/properties/scrape/approved-feed`

This path is implemented in the backend and is safer than pretending public browse scraping still works when the sites are actively blocking automation.

## Operational Guidance

- Use `Property Finder` as the baseline live scraper.
- Treat `Bayut` and `Dubizzle` as anti-bot-sensitive sources.
- Prefer residential proxies plus saved browser state for those two.
- If challenges become frequent again, move them to an approved feed or partner export.

## Scripts Added

- `scripts/capture_scraper_session.py`
  - opens a real browser and saves cookies/storage

- `scripts/capture_portal_sessions.ps1`
  - convenience wrapper to capture one or all portal sessions

- `scripts/configure_scraper_env.ps1`
  - updates `backend/.env` for proxy/session-based scraping

- `scripts/use_chrome_profile.ps1`
  - points the scraper at your real Chrome user-data directory

- `scripts/run_live_scrape_check.py`
  - runs a smoke test for `propertyfinder`, `bayut`, and `dubizzle`

## Fastest Next Steps

### Session-backed route

1. Point the backend env at a portal state file:

```powershell
.\scripts\configure_scraper_env.ps1 -Portal bayut -UseChrome
```

2. Open a real browser and save the solved session:

```powershell
.\scripts\capture_portal_sessions.ps1 -Portal bayut
```

3. Test it:

```powershell
cd backend
.\venv\Scripts\python.exe ..\scripts\run_live_scrape_check.py --site bayut
```

Repeat the same flow for `dubizzle`.

### Residential-proxy route

```powershell
.\scripts\configure_scraper_env.ps1 -Portal bayut -UseChrome -Headless -ProxyList "http://user:pass@host:port"
cd backend
.\venv\Scripts\python.exe ..\scripts\run_live_scrape_check.py --site bayut
```

### Persistent-Chrome-profile route

```powershell
.\scripts\use_chrome_profile.ps1 -Portal bayut
cd backend
.\venv\Scripts\python.exe ..\scripts\run_live_scrape_check.py --site bayut
```

## Backend Support Added

- authenticated proxy parsing from `PROXY_LIST`
- reusable browser storage state via `SCRAPER_STORAGE_STATE_PATH`
- approved feed ingestion via `APPROVED_FEED_URL`
- explicit anti-bot/challenge detection for Bayut and Dubizzle
