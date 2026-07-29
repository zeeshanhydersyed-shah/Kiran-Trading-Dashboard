#!/usr/bin/env python3
"""Remove June 4 data from database (from PSX test) to match ksestocks.com."""

from database import get_conn
from datetime import date

print('=' * 70)
print('CLEAN TEST DATA - Remove June 4, 2026 Data')
print('=' * 70)
print()

# Show what we're removing
with get_conn() as conn:
    # Count records for June 4
    result = conn.execute(
        'SELECT COUNT(*) as cnt FROM prices WHERE date = ?',
        ('2026-06-04',)
    ).fetchone()

    stock_count = result['cnt'] if result else 0

    result_idx = conn.execute(
        'SELECT COUNT(*) as cnt FROM index_prices WHERE date = ?',
        ('2026-06-04',)
    ).fetchone()

    index_count = result_idx['cnt'] if result_idx else 0

print(f'Records to delete:')
print(f'  Stock prices (2026-06-04): {stock_count} rows')
print(f'  Index prices (2026-06-04): {index_count} rows')
print()

if stock_count == 0 and index_count == 0:
    print('[INFO] No June 4 data found - nothing to delete')
    exit(0)

# Delete June 4 data
print('Deleting June 4, 2026 data...')
with get_conn() as conn:
    # Delete from prices
    conn.execute('DELETE FROM prices WHERE date = ?', ('2026-06-04',))
    prices_deleted = conn.execute("SELECT changes()").fetchone()[0]

    # Delete from index_prices
    conn.execute('DELETE FROM index_prices WHERE date = ?', ('2026-06-04',))
    indices_deleted = conn.execute("SELECT changes()").fetchone()[0]

print(f'  Deleted {prices_deleted} price records')
print(f'  Deleted {indices_deleted} index records')
print()

# Verify deletion
with get_conn() as conn:
    result = conn.execute(
        'SELECT COUNT(*) as cnt FROM prices WHERE date = ?',
        ('2026-06-04',)
    ).fetchone()

    remaining = result['cnt'] if result else 0

if remaining == 0:
    print('[SUCCESS] June 4 data removed!')
    print()

    # Show new latest date
    with get_conn() as conn:
        latest = conn.execute('SELECT MAX(date) as latest FROM prices').fetchone()
        if latest and latest['latest']:
            print(f'New latest date in database: {latest["latest"]}')
            print('This matches ksestocks.com (June 3, 2026)')
else:
    print('[ERROR] Some data still remains!')

print()
print('=' * 70)
