#!/usr/bin/env python3
"""Debug what happens when refresh runs."""

import logging
from datetime import date
from database import get_latest_prices, get_latest_scraped_date
from scraper import dates_since, scrape_date_range, build_session

# Enable detailed logging
logging.basicConfig(level=logging.DEBUG)

print("=" * 80)
print("DEBUG: Simulating refresh operation")
print("=" * 80)
print()

# Step 1: Get current database state
latest_str = get_latest_scraped_date()
print(f"[1] Current DB state: {latest_str}")

# Step 2: Get dates to scrape
latest_date = date.fromisoformat(latest_str)
new_dates = dates_since(latest_date)
print(f"[2] Dates to scrape: {new_dates}")

if not new_dates:
    print("NO NEW DATES TO SCRAPE")
    exit(0)

print()

# Step 3: Get previous prices
prev_prices = get_latest_prices()
print(f"[3] Previous prices from DB: {len(prev_prices)} records")
if prev_prices:
    sample = prev_prices[0]
    print(f"    Sample: {sample[0]} on {sample[1]}")

print()

# Step 4: Scrape new dates
print(f"[4] Scraping {len(new_dates)} dates...")
session = build_session()
sector_rows, price_rows, index_rows = scrape_date_range(new_dates, session, prev_prices=prev_prices)

print(f"    Got: {len(price_rows)} price records, {len(index_rows)} index records")
if price_rows:
    sample = price_rows[0]
    print(f"    Sample: {sample[0]} on {sample[1]}")

print()
print("[!] Check the logs above for:")
print("    - 'Stale data detected' message?")
print("    - 'Relabeling data' message?")
print()
print("[!] If NO stale detection:")
print("    - Then June 4 is NOT identical to June 3")
print("    - Then June 4 should be valid new data")
print()
print("[!] If stale detected but NOT relabeled:")
print("    - Then prev_prices might be empty")
print("    - Then stale detection didn't trigger")
