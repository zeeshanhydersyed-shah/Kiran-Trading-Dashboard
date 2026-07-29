#!/usr/bin/env python3
"""Compare June 3 and June 4 data from ksestocks to see if they're identical."""

from datetime import date
from scraper import scrape_date, build_session, _price_fingerprint, _is_stale

session = build_session()

print("=" * 80)
print("COMPARING JUNE 3 AND JUNE 4 DATA FROM ksestocks")
print("=" * 80)
print()

# Scrape both dates
s_rows_3, p_rows_3, i_rows_3 = scrape_date(date(2026, 6, 3), session)
s_rows_4, p_rows_4, i_rows_4 = scrape_date(date(2026, 6, 4), session)

print(f"June 3: {len(p_rows_3)} price records")
print(f"June 4: {len(p_rows_4)} price records")
print()

# Create fingerprints
fp_3 = _price_fingerprint(p_rows_3)
fp_4 = _price_fingerprint(p_rows_4)

print(f"June 3 fingerprint: {len(fp_3)} symbols")
print(f"June 4 fingerprint: {len(fp_4)} symbols")
print()

# Compare
print("Comparing fingerprints:")
common = set(fp_3) & set(fp_4)
matches = sum(1 for sym in common if fp_3[sym] == fp_4[sym])
match_ratio = matches / len(common) if common else 0

print(f"  Common symbols: {len(common)}")
print(f"  Identical OHLCV: {matches} ({match_ratio*100:.1f}%)")
print()

# Use stale detection logic
is_stale_result = _is_stale(fp_4, fp_3)
print(f"Would _is_stale(June4, June3) = {is_stale_result}?")

if is_stale_result:
    print("  [YES] Stale detection would CATCH this (correct)")
else:
    print("  [NO] Stale detection would MISS this (bug!)")
    print()
    print("Why it was missed:")
    print(f"  - Match ratio: {match_ratio*100:.1f}%")
    print(f"  - Threshold: 92%")
    print(f"  - Stale if >= 92%, but got {match_ratio*100:.1f}%")

print()

# Show sample data to understand
if p_rows_3 and p_rows_4:
    print("Sample records:")
    print(f"  June 3 first record: {p_rows_3[0]}")
    print(f"  June 4 first record: {p_rows_4[0]}")
