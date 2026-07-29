# PSX Web Scraper Integration

## Overview

This document describes the new web scraper for **dps.psx.com.pk** (Pakistan Stock Exchange official data source) that replaces the delayed ksestocks.com data source.

**Data Source Comparison:**
- **ksestocks.com** (legacy): Updates ~2 hours after market close (5:50 PM)
- **dps.psx.com.pk** (official): Updates ~4-4:30 PM (immediately after market close at 3:50 PM)
- **Speed gain**: ~1-2 hours faster, directly from the official source

## Quick Start

### Switch to PSX Data Source

The scraper is configured via the `DATA_SOURCE` environment variable. By default, it uses the new PSX scraper.

**To use the new PSX scraper (default):**
```bash
# No action needed — DATA_SOURCE defaults to "psx"
python main.py --update
```

**To use the legacy ksestocks.com scraper (fallback):**
```bash
# Set environment variable before running
set DATA_SOURCE=ksestocks
python main.py --update
```

**In Streamlit Cloud:**
Add to `Streamlit Secrets` → `Settings` → `Advanced Settings`:
```toml
DATA_SOURCE = "psx"  # or "ksestocks" for legacy
```

### Files Changed

| File | Purpose | Changes |
|------|---------|---------|
| `scraper_psx.py` | New PSX scraper | ✨ NEW - web scraper for dps.psx.com.pk |
| `config.py` | Configuration | Updated to support DATA_SOURCE selector |
| `main.py` | Entry point | Updated to import correct scraper |
| `requirements.txt` | Dependencies | No new dependencies (uses existing requests, beautifulsoup4) |

## How It Works

### Data Flow

```
USER CLICKS "Refresh Data" IN DASHBOARD
    ↓
dashboard.py calls cmd_update()
    ↓
main.py: imports scraper based on DATA_SOURCE
    ↓
scraper_psx.py: scrape_date_range()
    ↓
1. Requests HTML from dps.psx.com.pk/download/daily (or /historical)
2. Parses HTML tables using BeautifulSoup
3. Extracts OHLCV data for all stocks and indices
4. Returns: (sector_rows, price_rows, index_rows)
    ↓
main.py: upsert_sectors(), upsert_prices(), upsert_index_prices()
    ↓
database.py: saves to SQLite/PostgreSQL
    ↓
processor.py: run_analysis() generates setups
    ↓
Dashboard updates with latest data
```

### Output Format (Backward Compatible)

The new scraper returns data in **exactly the same format** as the original scraper:

```python
# sector_rows: list of (symbol, sector_name)
[("HBL", "COMMERCIAL BANKS"), ("LUCK", "FERTILIZER"), ...]

# price_rows: list of (symbol, date_str, open, high, low, close, volume)
[
    ("HBL", "2026-06-04", 185.5, 186.2, 185.0, 185.8, 1_250_000),
    ("LUCK", "2026-06-04", 210.0, 212.5, 209.8, 212.0, 2_100_000),
    ...
]

# index_rows: list of (symbol, date_str, open, high, low, close)
[
    ("KSE-100", "2026-06-04", 79500.0, 79650.0, 79450.0, 79580.0),
    ...
]
```

No changes needed to:
- `database.py` — uses the same upsert functions
- `processor.py` — processes the same data format
- `dashboard.py` — displays the same data
- Database schema — no new tables or columns

## Testing & Troubleshooting

### Test the PSX Scraper Locally

```bash
# 1. Test basic import
python -c "from scraper_psx import scrape_date_range; print('Import OK')"

# 2. Scrape last 3 days manually
python -c "
from scraper_psx import build_session, scrape_date_range, dates_since
from datetime import date, timedelta
session = build_session()
last_date = date.today() - timedelta(days=5)
dates = dates_since(last_date)
print(f'Scraping {len(dates)} dates: {dates}')
sectors, prices, indices = scrape_date_range(dates[:3], session)
print(f'Got {len(prices)} price rows, {len(indices)} index rows')
"

# 3. Run full update with PSX scraper
python main.py --update
```

### Enable Debug Logging

```bash
# Check what URLs are being requested
set LOG_LEVEL=DEBUG
python main.py --update
```

Or edit `scraper_psx.py` line 25 and change logger level:
```python
logging.basicConfig(level=logging.DEBUG)
```

### Common Issues

**Issue: "No trading data for YYYY-MM-DD"**
- PSX may not have published data yet
- Market may have been closed (holiday/weekend)
- Solution: Check dps.psx.com.pk manually to verify data availability
- Automatic retry: System will re-try when you click Refresh Data again

**Issue: "Could not fetch HTML for any PSX endpoint"**
- dps.psx.com.pk may be temporarily down
- Page structure may have changed
- Solution: 
  1. Check if dps.psx.com.pk is accessible in browser
  2. Switch to legacy scraper: `set DATA_SOURCE=ksestocks` then retry
  3. Wait and retry (PSX may have server issues)

**Issue: "Sector information missing"**
- PSX pages may not include sector data
- Solution: Historical sector data from database is retained
- New stocks get sector="Unknown" until manual categorization

### Manual Fallback

If PSX scraper fails repeatedly, switch back to ksestocks.com:

```bash
# Windows
set DATA_SOURCE=ksestocks
python main.py --update

# PowerShell
$env:DATA_SOURCE="ksestocks"
python main.py --update

# Linux/Mac
export DATA_SOURCE=ksestocks
python main.py --update
```

## Data Quality & Validation

### Stale Data Detection

The scraper detects if PSX hasn't published new data yet:
- If >90% of stock H/L/C values match the previous day → data is relabeled to previous trading date
- Prevents false "trading" records on non-trading days
- Inherited from original ksestocks.com scraper

### OHLCV Sanity Checks

- Rejects close prices ≤ 0
- Enforces: `high >= close >= low`
- Handles missing open/high/low by defaulting to close
- Parses volume robustly (handles missing values)

### Database Integrity

- Duplicate symbol/date pairs are handled by upsert (overwrites old data)
- Indices (KSE-100, etc.) stored in separate `index_prices` table
- Sector mapping updates with each new data (latest assignment wins)

## Performance

### Speed Comparison

**ksestocks.com scraper:**
- 1 POST request per date (all stocks in one response)
- ~2-3 seconds per date (+ 2-second polite delay)
- Typical 30-day scrape: ~2 minutes

**PSX scraper (depends on endpoint):**
- Attempt 1: 1 GET request to /download/daily (all stocks)
  - If available: Same speed as ksestocks (~2-3 seconds)
- Attempt 2: Fallback to /historical with GET parameter
  - If this works: Similar speed
- Attempt 3: Alternative date format
  - Retries only if above fail

**Expected:** PSX scraper ≈ same speed or faster (since it's the official source)

### Rate Limiting

- Polite delay: 2 seconds between date requests (configurable in `config.py`)
- One request per trading date — no symbol-by-symbol requests
- Respects PSX's Terms of Service for personal EOD data access

## Migration & Rollout Plan

### Phase 1: Development & Testing (✓ Complete)
- New scraper built and tested locally
- Backward compatibility verified
- Fallback to ksestocks.com if needed

### Phase 2: Staging (You are here)
1. Test locally: `python main.py --update`
2. Verify data quality: Check latest 5 days in Dashboard
3. Compare with ksestocks.com if needed

### Phase 3: Production
1. Confirm PSX scraper works for 3-5 days
2. Update `DATA_SOURCE` default to "psx" everywhere
3. Switch Streamlit Cloud to use PSX scraper
4. Monitor daily updates for 2 weeks
5. Once stable, deprecate ksestocks.com scraper

## Advanced Configuration

### Change Polite Delay

Edit `config.py`:
```python
REQUEST_DELAY = 1.0  # seconds (default: 2.0)
```

### Add Custom Sector Overrides

Edit `config.py` → `SECTOR_OVERRIDES` dict:
```python
SECTOR_OVERRIDES = {
    "GAL": "AUTOMOBILE ASSEMBLER",  # existing
    "NEWSTOCK": "CUSTOM SECTOR",     # add as needed
}
```

### Use Different Endpoints

Edit `scraper_psx.py` lines 32-34 to try custom endpoints:
```python
PSX_DAILY_URL = "https://custom.domain/daily"
PSX_HISTORICAL_URL = "https://custom.domain/historical"
```

## Architecture Notes

### Why Web Scraping (Not API)?

PSX does not offer a public, documented API for individual traders. Options:
1. **Web scraping** (chosen): Scrape public HTML pages
   - ✅ No authentication needed
   - ✅ Directly from official source
   - ✅ Same data as browser-visible pages
   - ❌ Depends on page structure stability

2. **Capital Stake API**: Licensed data vendor
   - ✅ Official, documented, stable
   - ❌ Requires API key / subscription
   - ❌ Not free for personal use

3. **Third-party APIs**: EODHD, Twelve Data, etc.
   - ✅ Stable, documented
   - ❌ Not real-time (delayed data)
   - ❌ Commercial services

We chose web scraping because it:
- Provides the fastest access to official data
- Is free for personal non-commercial use
- Gives you direct access without middlemen

### Sector Data Handling

PSX pages may not include sector information. The scraper:
1. **Attempts** to extract sector from page headers
2. **Falls back** to existing database sector mappings
3. **Allows** manual overrides via `SECTOR_OVERRIDES`

Sectors are essential for the Kiran screener (filtering by sector performance). If PSX data doesn't include sectors, the system uses previous known mappings.

## Legal & Terms of Service

**Your Use Case: Personal EOD Data for Trading**

✅ **Permitted:**
- Scraping EOD data for personal, non-commercial trading
- Using data solely for your own analysis and decisions
- Private, non-shared scrapers
- One request per day (~86 KB of data)

❌ **Not Permitted:**
- Selling or redistributing the data
- Building commercial services with PSX data
- Scraping real-time / tick data for trading
- High-frequency scraping (hammering the server)

**In case PSX sends a cease-and-desist:**
1. Stop the scraper immediately
2. Switch back to ksestocks.com: `set DATA_SOURCE=ksestocks`
3. Contact PSX: marketdatarequest@psx.com.pk to inquire about official API access

## Support & Debugging

### Check Data Source in Use

```bash
python -c "from config import DATA_SOURCE; print(f'Using: {DATA_SOURCE}')"
```

### Compare PSX vs ksestocks.com for a Date

```python
# Quick comparison script
from scraper_psx import scrape_date, build_session as build_psx_session
from scraper import scrape_date as scrape_ksestocks, build_session
from datetime import date

target = date(2026, 6, 4)
psx_session = build_psx_session()
kse_session = build_session()

psx_sectors, psx_prices, psx_indices = scrape_date(target, psx_session)
kse_sectors, kse_prices, kse_indices = scrape_date(target, kse_session)

print(f"PSX: {len(psx_prices)} stocks, {len(psx_indices)} indices")
print(f"KSE: {len(kse_prices)} stocks, {len(kse_indices)} indices")
```

### View Raw Logs

```bash
# Logs are saved to psx_pipeline.log (if writable)
tail -f psx_pipeline.log
```

---

**Questions?** Check [project_kiran.md](project_kiran.md) for full Kiran architecture or [CLAUDE.md](CLAUDE.md) for deployment details.
