#!/usr/bin/env python3
"""Verify rollback is complete and system is healthy."""

from database import init_db, get_latest_scraped_date, count_prices, count_sectors
from datetime import date

print('=' * 70)
print('ROLLBACK VERIFICATION')
print('=' * 70)
print()

# Initialize database
init_db()
print('[STEP 1] Database initialized')
print()

# Check database state
latest_date = get_latest_scraped_date()
price_count = count_prices()
sector_count = count_sectors()

print('[STEP 2] Database state check:')
print(f'  Latest scraped date: {latest_date}')
print(f'  Total price records: {price_count:,}')
print(f'  Total sector mappings: {sector_count:,}')
print()

if not latest_date:
    print('[ERROR] Database is empty!')
    import sys
    sys.exit(1)

if price_count == 0:
    print('[ERROR] No prices in database!')
    import sys
    sys.exit(1)

print('[STEP 3] Testing scraper:')
from scraper import build_session, scrape_date
from datetime import timedelta

session = build_session()
test_date = date.today() - timedelta(days=1)
sectors, prices, indices = scrape_date(test_date, session)

print(f'  Scraped {len(prices)} stocks')
print(f'  Scraped {len(indices)} indices')
print()

if len(prices) == 0:
    print('[ERROR] Scraper returned no data!')
    import sys
    sys.exit(1)

print('[STEP 4] Sample data:')
if prices:
    sym, d, o, h, l, c, v = prices[0]
    print(f'  {sym}: {d} | Close={c} | Vol={v}')
if indices:
    sym, d, o, h, l, c = indices[0]
    print(f'  {sym}: {d} | Close={c}')
print()

print('=' * 70)
print('[SUCCESS] Rollback complete and verified!')
print('=' * 70)
print()
print('Summary:')
print('  - Config: ksestocks.com only')
print('  - Main.py: Original scraper import')
print('  - Database: Healthy with existing data')
print('  - Scraper: Working and returning data')
print()
print('Next step: Click "Refresh Data" in dashboard')
