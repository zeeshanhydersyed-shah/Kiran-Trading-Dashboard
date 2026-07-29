#!/usr/bin/env python3
"""Directly fix mislabeled June 4 data to June 3."""

from database import get_conn

print('Fixing mislabeled dates...')
print()

# Check before
with get_conn() as conn:
    before_4 = conn.execute('SELECT COUNT(*) as c FROM prices WHERE date = "2026-06-04"').fetchone()['c']
    before_3 = conn.execute('SELECT COUNT(*) as c FROM prices WHERE date = "2026-06-03"').fetchone()['c']

print(f'Before: 2026-06-04 has {before_4} records, 2026-06-03 has {before_3} records')

# Fix it
with get_conn() as conn:
    conn.execute('UPDATE prices SET date = "2026-06-03" WHERE date = "2026-06-04"')
    prices_fixed = conn.execute("SELECT changes()").fetchone()[0]

    conn.execute('UPDATE index_prices SET date = "2026-06-03" WHERE date = "2026-06-04"')
    indices_fixed = conn.execute("SELECT changes()").fetchone()[0]

print(f'Fixed {prices_fixed} price records and {indices_fixed} index records')
print()

# Verify
with get_conn() as conn:
    after_4 = conn.execute('SELECT COUNT(*) as c FROM prices WHERE date = "2026-06-04"').fetchone()['c']
    after_3 = conn.execute('SELECT COUNT(*) as c FROM prices WHERE date = "2026-06-03"').fetchone()['c']
    latest = conn.execute('SELECT MAX(date) as latest FROM prices').fetchone()['latest']

print(f'After: 2026-06-04 has {after_4} records, 2026-06-03 has {after_3} records')
print(f'Latest date in database: {latest}')
print()

if after_4 == 0 and after_3 == before_4:
    print('[SUCCESS] All dates corrected!')
    print('Dashboard will now show: 03/06/26')
else:
    print('[WARNING] Verify results above')
