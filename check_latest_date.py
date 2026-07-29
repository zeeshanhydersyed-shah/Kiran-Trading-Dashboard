#!/usr/bin/env python3
from database import get_latest_stock_date, get_conn

latest = get_latest_stock_date()
print(f'get_latest_stock_date() returns: {latest}')
print()

# Check how many records for each recent date
with get_conn() as conn:
    for test_date in ['2026-06-04', '2026-06-03', '2026-06-02']:
        cnt = conn.execute(
            'SELECT COUNT(*) as c FROM prices WHERE date = ?',
            (test_date,)
        ).fetchone()
        count = cnt['c']
        print(f'{test_date}: {count} records')
