#!/usr/bin/env python3
"""Fix mislabeled June 4 data - relabel to correct date June 3, 2026."""

from database import get_conn

print('=' * 70)
print('FIX MISLABELED DATES')
print('=' * 70)
print()

# Check current state
with get_conn() as conn:
    cnt_june4 = conn.execute(
        'SELECT COUNT(*) as c FROM prices WHERE date = ?',
        ('2026-06-04',)
    ).fetchone()['c']

    cnt_june3 = conn.execute(
        'SELECT COUNT(*) as c FROM prices WHERE date = ?',
        ('2026-06-03',)
    ).fetchone()['c']

print('[BEFORE FIX]')
print(f'  2026-06-04: {cnt_june4} records (MISLABELED)')
print(f'  2026-06-03: {cnt_june3} records (MISSING)')
print()

# Show sample of what we're fixing
print('[SAMPLE DATA in 2026-06-04 (actually June 3 data):')
with get_conn() as conn:
    rows = conn.execute(
        'SELECT symbol, close, volume FROM prices WHERE date = ? LIMIT 3',
        ('2026-06-04',)
    ).fetchall()
    for row in rows:
        print(f'  {row["symbol"]}: Close={row["close"]}, Vol={row["volume"]}')
print()

# Confirm before fixing
response = input('Fix mislabeled dates? (yes/no): ').strip().lower()

if response != 'yes':
    print('Cancelled - no changes made')
    exit(1)

print()
print('[FIXING...]')

# Update prices table
with get_conn() as conn:
    conn.execute(
        'UPDATE prices SET date = ? WHERE date = ?',
        ('2026-06-03', '2026-06-04')
    )
    prices_fixed = conn.execute("SELECT changes()").fetchone()[0]

    # Update index_prices table
    conn.execute(
        'UPDATE index_prices SET date = ? WHERE date = ?',
        ('2026-06-03', '2026-06-04')
    )
    indices_fixed = conn.execute("SELECT changes()").fetchone()[0]

print(f'  Fixed {prices_fixed} price records')
print(f'  Fixed {indices_fixed} index records')
print()

# Verify fix
with get_conn() as conn:
    cnt_june4_after = conn.execute(
        'SELECT COUNT(*) as c FROM prices WHERE date = ?',
        ('2026-06-04',)
    ).fetchone()['c']

    cnt_june3_after = conn.execute(
        'SELECT COUNT(*) as c FROM prices WHERE date = ?',
        ('2026-06-03',)
    ).fetchone()['c']

print('[AFTER FIX]')
print(f'  2026-06-04: {cnt_june4_after} records (should be 0)')
print(f'  2026-06-03: {cnt_june3_after} records (should have all data)')
print()

if cnt_june4_after == 0 and cnt_june3_after == cnt_june4:
    print('[SUCCESS] Dates corrected!')
    print()

    # Show new latest date
    with get_conn() as conn:
        latest = conn.execute('SELECT MAX(date) as latest FROM prices').fetchone()['latest']
    print(f'New latest date: {latest}')
    print('Dashboard will now correctly show: 03/06/26')
else:
    print('[ERROR] Fix incomplete - please check manually')

print()
print('=' * 70)
