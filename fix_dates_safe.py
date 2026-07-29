#!/usr/bin/env python3
"""Safely fix mislabeled dates - delete duplicates and relabel."""

from database import get_conn

print('Fixing mislabeled dates (safe method)...')
print()

# Check before
with get_conn() as conn:
    before_prices_4 = conn.execute('SELECT COUNT(*) as c FROM prices WHERE date = "2026-06-04"').fetchone()['c']
    before_prices_3 = conn.execute('SELECT COUNT(*) as c FROM prices WHERE date = "2026-06-03"').fetchone()['c']
    before_idx_4 = conn.execute('SELECT COUNT(*) as c FROM index_prices WHERE date = "2026-06-04"').fetchone()['c']
    before_idx_3 = conn.execute('SELECT COUNT(*) as c FROM index_prices WHERE date = "2026-06-03"').fetchone()['c']

print(f'PRICES table:')
print(f'  Before: 2026-06-04 = {before_prices_4} records, 2026-06-03 = {before_prices_3} records')
print()
print(f'INDEX_PRICES table:')
print(f'  Before: 2026-06-04 = {before_idx_4} records, 2026-06-03 = {before_idx_3} records')
print()

# Step 1: Delete index records for June 4 (since June 3 version exists)
print('Step 1: Remove duplicate index records...')
with get_conn() as conn:
    if before_idx_4 > 0 and before_idx_3 > 0:
        conn.execute('DELETE FROM index_prices WHERE date = "2026-06-04"')
        idx_deleted = conn.execute("SELECT changes()").fetchone()[0]
        print(f'  Deleted {idx_deleted} index records from 2026-06-04')
    elif before_idx_4 > 0 and before_idx_3 == 0:
        # If no June 3 index data, update instead
        conn.execute('UPDATE index_prices SET date = "2026-06-03" WHERE date = "2026-06-04"')
        idx_updated = conn.execute("SELECT changes()").fetchone()[0]
        print(f'  Updated {idx_updated} index records to 2026-06-03')
print()

# Step 2: Update price records
print('Step 2: Fix price records labels...')
with get_conn() as conn:
    conn.execute('UPDATE prices SET date = "2026-06-03" WHERE date = "2026-06-04"')
    prices_fixed = conn.execute("SELECT changes()").fetchone()[0]
    print(f'  Updated {prices_fixed} price records to 2026-06-03')
print()

# Verify
print('Verifying...')
with get_conn() as conn:
    after_prices_4 = conn.execute('SELECT COUNT(*) as c FROM prices WHERE date = "2026-06-04"').fetchone()['c']
    after_prices_3 = conn.execute('SELECT COUNT(*) as c FROM prices WHERE date = "2026-06-03"').fetchone()['c']
    after_idx_4 = conn.execute('SELECT COUNT(*) as c FROM index_prices WHERE date = "2026-06-04"').fetchone()['c']
    after_idx_3 = conn.execute('SELECT COUNT(*) as c FROM index_prices WHERE date = "2026-06-03"').fetchone()['c']
    latest = conn.execute('SELECT MAX(date) as latest FROM prices').fetchone()['latest']

print()
print(f'PRICES table:')
print(f'  After: 2026-06-04 = {after_prices_4} records, 2026-06-03 = {after_prices_3} records')
print()
print(f'INDEX_PRICES table:')
print(f'  After: 2026-06-04 = {after_idx_4} records, 2026-06-03 = {after_idx_3} records')
print()

if after_prices_4 == 0 and after_idx_4 == 0:
    print('[SUCCESS] All mislabeled dates corrected!')
    print(f'Latest date in database: {latest}')
    print()
    print('Dashboard will now correctly show:')
    print('  Stocks Latest Record: 03/06/26')
    print('  Index Latest Record: 03/06/26')
    print('  Data updated: 03/06/26 (from ksestocks.com)')
else:
    print('[WARNING] Some records still have wrong dates:')
    print(f'  Prices with 2026-06-04: {after_prices_4}')
    print(f'  Indices with 2026-06-04: {after_idx_4}')
