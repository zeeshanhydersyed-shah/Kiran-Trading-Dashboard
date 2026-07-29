#!/usr/bin/env python3
"""
Test Phase 2 implementation.

This script validates:
1. dates_since() now includes today if after 16:30 PKT
2. Improved stale detection (92% threshold + OHLCV)
3. Both scenarios: data available and not available
"""

import sys
from datetime import date, datetime, time as dtime, timedelta
from database import get_latest_stock_date, count_prices
from scraper import dates_since, scrape_date_range, _price_fingerprint, _is_stale
from main import cmd_update
from refresh_manager import execute_refresh_with_tracking

print("=" * 80)
print("PHASE 2 TEST: dates_since() + Improved Stale Detection")
print("=" * 80)
print()

# Test 1: dates_since() behavior
print("[Test 1] dates_since() - Should include today if after 16:30 PKT")
print("-" * 80)

today = date.today()
yesterday = today - timedelta(days=1)
now = datetime.now()

latest_db_str = get_latest_stock_date()
latest_db = date.fromisoformat(latest_db_str) if latest_db_str else yesterday
print(f"Current time: {now.strftime('%H:%M:%S')} PKT")
print(f"Market close: 16:30 PKT")
print(f"Latest in DB: {latest_db}")
print(f"Today: {today}")
print(f"Yesterday: {yesterday}")
print()

dates_to_scrape = dates_since(latest_db)
print(f"dates_since({latest_db}) returned: {dates_to_scrape}")

if now.time() >= dtime(16, 30):
    if today in dates_to_scrape:
        print("[PASS] Today is included (after 16:30 PKT)")
    else:
        print("[FAIL] Today should be included but isn't")
else:
    if today not in dates_to_scrape:
        print("[PASS] Today excluded (before 16:30 PKT)")
    else:
        print("[FAIL] Today should not be included (before 16:30 PKT)")

print()
print()

# Test 2: Stale detection logic
print("[Test 2] Improved Stale Detection")
print("-" * 80)

# Create test fingerprints with 20+ symbols to exceed minimum threshold
fp_today = {
    f"SYM{i}": (100.0 + i, 105.0 + i, 102.0 + i, 103.0 + i, 10000.0 + i * 100)
    for i in range(25)
}

# Exact copy (stale data - 100% match)
fp_stale = fp_today.copy()

# Partial update (about 20% changed - 5 out of 25)
fp_partial = {}
for i in range(25):
    if i < 5:  # First 5 symbols changed
        fp_partial[f"SYM{i}"] = (100.0 + i + 1, 105.0 + i + 1, 102.0 + i + 1, 103.0 + i + 1, 10000.0 + i * 100 + 50)
    else:  # Rest unchanged
        fp_partial[f"SYM{i}"] = (100.0 + i, 105.0 + i, 102.0 + i, 103.0 + i, 10000.0 + i * 100)

# Fresh data (all changed)
fp_fresh = {
    f"SYM{i}": (100.0 + i + 1, 105.0 + i + 1, 102.0 + i + 1, 103.0 + i + 1, 10000.0 + i * 100 + 100)
    for i in range(25)
}

print("Test Case 1: 100% match (stale data)")
result = _is_stale(fp_stale, fp_today)
print(f"  _is_stale(100% match) = {result}")
print(f"  Expected: True (market didn't update)")
print(f"  Status: {'[PASS]' if result else '[FAIL]'}")
print()

print("Test Case 2: 80% match (partial update - 5/25 symbols changed)")
result = _is_stale(fp_partial, fp_today)
print(f"  _is_stale(80% match) = {result}")
print(f"  Expected: False (data is fresh enough)")
print(f"  Status: {'[PASS]' if not result else '[FAIL]'}")
print()

print("Test Case 3: 0% match (all fresh)")
result = _is_stale(fp_fresh, fp_today)
print(f"  _is_stale(0% match) = {result}")
print(f"  Expected: False (fresh data)")
print(f"  Status: {'[PASS]' if not result else '[FAIL]'}")
print()
print()

# Test 3: End-to-end refresh with messaging
print("[Test 3] End-to-End Refresh with Messaging")
print("-" * 80)

print("Current database state:")
print(f"  Latest date: {get_latest_stock_date()}")
print(f"  Total prices: {count_prices()}")
print()

print("Executing refresh with tracking...")
result = execute_refresh_with_tracking(cmd_update)
print()
print(f"Refresh Result:")
print(f"  Status: {result.status}")
print(f"  Message: {result.message}")
print(f"  Data date: {result.data_date}")
print(f"  Timestamp: {result.timestamp}")
print()

from refresh_manager import get_refresh_message
msg_text, msg_type = get_refresh_message(result)
print(f"Streamlit display (type={msg_type}):")
print(f"{msg_text}")

print()
print("=" * 80)
print("PHASE 2 TEST COMPLETE")
print("=" * 80)
